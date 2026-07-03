import os
import pickle
import logging
import threading
import time
from typing import List, Optional

import chromadb
import jieba
from langchain_core.documents import Document
from langchain_chroma import Chroma
from rank_bm25 import BM25Okapi

from core import config
from core.cache import EmbeddingCache, RerankerCache

logger = logging.getLogger(__name__)


class VectorStoreService: # 向量存储服务
    def __init__(self, embedding):
        self.embedding = embedding
        # 包装 embedding，自动缓存 text → vector 映射到 Redis
        self._cached_embedding = EmbeddingCache(embedding)
        _client = chromadb.HttpClient(host=config.CHROMA_HOST, port=config.CHROMA_PORT)
        self.vector_store = Chroma(
            client=_client,
            collection_name=config.COLLECTION_NAME,
            embedding_function=self._cached_embedding,
        )
        self._bm25 = None
        self._bm25_texts = None
        self._bm25_metadatas = None
        self._bm25_doc_count = 0
        self._bm25_lock = threading.Lock()
        self._reranker = None
        self._reranker_cache = RerankerCache()
        logger.info(
            "VectorStoreService 已初始化 chroma=%s:%d collection=%s",
            config.CHROMA_HOST, config.CHROMA_PORT, config.COLLECTION_NAME,
        )

    # ── BM25 index management ──────────────────────────
    #  判断是否需要重建BM25索引
    def _bm25_needs_rebuild(self):
        # 获取当前向量库中的文档数量
        actual_count = self.vector_store._collection.count()
        return actual_count != self._bm25_doc_count

    def _build_bm25(self):
        actual_count = self.vector_store._collection.count()
        if actual_count == 0:
            self._bm25 = None
            self._bm25_texts = []
            self._bm25_metadatas = []
            self._bm25_doc_count = 0
            return

        # 加载磁盘索引文件，如果文档数量未变则复用
        if os.path.exists(config.BM25_INDEX_PATH):
            try:
                with open(config.BM25_INDEX_PATH, "rb") as f:
                    cache = pickle.load(f)
                if cache.get("doc_count") == actual_count:
                    self._bm25 = cache["index"]
                    self._bm25_texts = cache["texts"]
                    self._bm25_metadatas = cache["metadatas"]
                    self._bm25_doc_count = actual_count
                    logger.debug("BM25 索引缓存命中 doc_count=%d", actual_count)
                    return
            except Exception:
                logger.warning("BM25 缓存加载失败，将重建索引", exc_info=True)

        # 从 ChromaDB 全量拉取，构建 BM25
        raw = self.vector_store.get() # 从 ChromaDB 中获取所有数据
        texts = raw.get("documents", []) # 获取子块列表
        metadatas = raw.get("metadatas", []) # 获取元数据列表
        if not texts:
            self._bm25 = None
            self._bm25_texts = []
            self._bm25_metadatas = []
            self._bm25_doc_count = 0
            return
        
        # 使用结巴分词对文档内容进行分词
        corpus = [list(jieba.lcut_for_search(t)) for t in texts]
        # index是一个BM25索引对象，里面存的都是一些单词在子块的统计信息
        # 里面有方法用于计算BM25分数
        index = BM25Okapi(corpus) 

        cache = {
            "doc_count": actual_count,
            "index": index,
            "texts": texts,
            "metadatas": metadatas,
        }
        with open(config.BM25_INDEX_PATH, "wb") as f:
            # #dump()函数将Python对象转换为字节流，并写入文件句柄f中，
            # 完成数据的序列化和存储。
            pickle.dump(cache, f) 

        self._bm25 = index
        self._bm25_texts = texts
        self._bm25_metadatas = metadatas
        self._bm25_doc_count = actual_count
        logger.info("BM25 索引重建完成 doc_count=%d", actual_count)

    def refresh_bm25(self):
        """ingestion 写入新文档后调用，强制重建 BM25 索引。"""
        self._build_bm25()

    # ── Hybrid search ──────────────────────────────────
    # 相似度检索BM25和向量检索

    def hybrid_search(self, query: str, top_k: int = None) -> list[Document]:
        t0 = time.time()
        if self._bm25_needs_rebuild():
            with self._bm25_lock:
                if self._bm25_needs_rebuild():
                    self._build_bm25()

        vec_k = config.TOP_K_CHILDREN
        bm25_k = config.TOP_K_BM25

        # ── 向量路 ──
        vector_docs = self.vector_store.similarity_search(query, k=vec_k)

        # ── BM25 路 ──
        bm25_docs = []
        if self._bm25 is not None and self._bm25_texts: 

            # tokens是一个列表，里面是对查询语句进行分词后的结果。
            # jieba.lcut_for_search()函数会将输入的查询语句切分成一个个词语，返回一个列表。
            tokens = list(jieba.lcut_for_search(query))
            # 遍历所有的BM25子块计算得分，得到一个分数列表scores
            scores = self._bm25.get_scores(tokens)
            
            # 排序算法，三个参数，第一个参数是待排序的索引列表，第二个参数是排序的键值列表，
            # 第三个参数是排序规则，默认为升序。【】切片，保留bm25_k个分数最大的索引
            top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:bm25_k]
            for idx in top_idx:
                # 实在太拉的就弃掉
                if scores[idx] > 0:
                    bm25_docs.append(Document(
                        page_content=self._bm25_texts[idx],
                        metadata=self._bm25_metadatas[idx],
                    ))

        # ── RRF 融合 ──
        rrf_scores = {} # 评分字典
        doc_map = {} # 内容字典

        for rank, doc in enumerate(vector_docs, start=1):
            # key是父块ID_子块ID拼接的而成的字典的key
            key = f"{doc.metadata.get('parent_id', '')}_{doc.metadata.get('chunk_index', '')}"
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (config.RRF_K + rank)
            doc_map[key] = doc

        for rank, doc in enumerate(bm25_docs, start=1):
            key = f"{doc.metadata.get('parent_id', '')}_{doc.metadata.get('chunk_index', '')}"
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (config.RRF_K + rank)
            if key not in doc_map:
                doc_map[key] = doc
        # 排序，根据RRF分数从高到低排序，返回最终的文档列表，每个元素都是一个Document对象
        # 里面存储了子块内容、元数据等信息
        sorted_keys = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
        result = [doc_map[key] for key in sorted_keys]

        logger.debug(
            "混合检索完成 query=%s vector=%d bm25=%d fusion=%d elapsed=%dms",
            query[:80], len(vector_docs), len(bm25_docs), len(result),
            int((time.time() - t0) * 1000),
        )
        return result

    # ── Reranker ──────────────────────────────────────

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """用 CrossEncoder 对候选文档列表重新打分，返回分数列表。

        优先从 Redis 缓存读取，未命中时调用模型推理并回写缓存。
        """
        # 1. 查缓存
        cached_scores = self._reranker_cache.get_scores(query, documents)

        # 2. 找出未命中的索引
        uncached_idx = [i for i, s in enumerate(cached_scores) if s is None]
        if not uncached_idx:
            return cached_scores  # 全部命中

        # 3. 对未命中的调用 CrossEncoder 推理
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(config.RERANKER_MODEL)

        uncached_docs = [documents[i] for i in uncached_idx]
        pairs = [[query, doc] for doc in uncached_docs]
        fresh_scores = self._reranker.predict(pairs).tolist()

        # 4. 回写缓存
        self._reranker_cache.set_scores(query, uncached_docs, fresh_scores)

        # 5. 合并结果
        for i, score in zip(uncached_idx, fresh_scores):
            cached_scores[i] = score
        return cached_scores

    # ── LangChain retriever (for backward compat) ──────

    def get_retriever(self):
        return self.vector_store.as_retriever(
            search_type="similarity", # 使用相似度搜索
            search_kwargs={"k": config.TOP_K_CHILDREN}, 
        )
