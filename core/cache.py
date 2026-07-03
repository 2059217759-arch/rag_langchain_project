"""
Redis 缓存层，为 RAG 核心链路提供三层缓存：
  1. EmbeddingCache  — 查询文本 → 向量（降低 DashScope API 调用）
  2. SearchResultCache — 查询 → 检索结果（跳过 embedding + Chroma + BM25 + rerank）
  3. RerankerCache  — (query, doc) → 分数（降低 CrossEncoder 推理）

所有缓存通过 doc_version 管理一致性：文档入库后 version 递增，检索缓存自然失效。

Redis Key 命名规范：
  rag:doc_version               — 文档版本号（int）
  rag:emb:{md5(text)}           — embedding 向量（JSON array）
  rag:search:v{ver}:{md5(q)}    — 检索结果（str）
  rag:rerank:{md5(query+doc)}   — rerank 分数（float str）
  rag:metrics:{layer}           — 各层命中率统计（hash: hits/misses）
"""

import hashlib
import json
import logging
import threading
from typing import List, Optional

import redis

from core import config

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# Redis 连接（进程级单例）
# ══════════════════════════════════════════════════════════

_redis_client: Optional[redis.Redis] = None
_redis_lock = threading.Lock()


def get_redis_client() -> redis.Redis:
    """获取 Redis 客户端（线程安全单例）。

    redis-py 的 Redis() 自带连接池，所有线程安全共享。
    """
    global _redis_client
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                _redis_client = redis.Redis(
                    host=config.REDIS_HOST,
                    port=config.REDIS_PORT,
                    db=config.REDIS_DB,
                    password=config.REDIS_PASSWORD or None,
                    socket_timeout=config.REDIS_SOCKET_TIMEOUT,
                    decode_responses=False,
                )
                try:
                    _redis_client.ping()
                    logger.info(
                        "Redis 连接成功 %s:%d db=%d",
                        config.REDIS_HOST, config.REDIS_PORT, config.REDIS_DB,
                    )
                except Exception:
                    logger.warning(
                        "Redis 不可用 %s:%d，缓存降级为 no-op",
                        config.REDIS_HOST, config.REDIS_PORT, exc_info=True,
                    )
    return _redis_client


def _redis_ok() -> bool:
    try:
        return get_redis_client().ping()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
# 文档版本号
# ══════════════════════════════════════════════════════════

_VERSION_KEY = "rag:doc_version"


def get_doc_version() -> int:
    """获取当前文档版本号。

    版本号是检索结果缓存的 key 组成部分，确保文档更新后旧缓存自动失效。
    返回 0 表示 Redis 不可用。
    """
    if not _redis_ok():
        return 0
    try:
        val = get_redis_client().get(_VERSION_KEY)
        if val is None:
            # 首次启动时初始化版本号为 1
            get_redis_client().set(_VERSION_KEY, 1)
            return 1
        return int(val)
    except Exception:
        logger.warning("读取 doc_version 失败", exc_info=True)
        return 0


def bump_doc_version() -> int:
    """递增文档版本号（文档入库后调用），使所有检索结果缓存失效。"""
    if not _redis_ok():
        return 0
    try:
        # 确保 key 存在（首次调用时）
        if not get_redis_client().exists(_VERSION_KEY):
            get_redis_client().set(_VERSION_KEY, 1)
        new_version = get_redis_client().incr(_VERSION_KEY)
        logger.info("doc_version %d → %d，检索缓存已失效", new_version - 1, new_version)
        return new_version
    except Exception:
        logger.warning("递增 doc_version 失败", exc_info=True)
        return 0


# ══════════════════════════════════════════════════════════
# 通用工具
# ══════════════════════════════════════════════════════════

def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _safe_redis(callable, default=None):
    """执行 Redis 操作，异常时静默返回 default。"""
    try:
        return callable()
    except Exception:
        logger.debug("Redis 操作异常（已降级）", exc_info=True)
        return default


# ══════════════════════════════════════════════════════════
# Layer 1: EmbeddingCache
# ══════════════════════════════════════════════════════════

_METRICS_EMB_KEY = "rag:metrics:emb"


class EmbeddingCache:
    """包装 DashScopeEmbeddings，缓存 text → embedding 映射。

    用法：
        raw_embeddings = DashScopeEmbeddings(model="text-embedding-v4")
        cached_embeddings = EmbeddingCache(raw_embeddings)
        chroma = Chroma(embedding_function=cached_embeddings, ...)
    """

    def __init__(self, delegate):
        """
        Args:
            delegate: 原始 embeddings 实例（如 DashScopeEmbeddings）
        """
        self._delegate = delegate
        self._enabled = config.EMBEDDING_CACHE_ENABLED

    @property
    def enabled(self) -> bool:
        return self._enabled and _redis_ok()

    # ── LangChain Embeddings 接口 ──────────────────────

    def embed_query(self, text: str) -> List[float]:
        """嵌入单条查询文本。"""
        if not self.enabled:
            return self._delegate.embed_query(text)

        key = f"rag:emb:{_hash(text)}"
        cached = _safe_redis(lambda: get_redis_client().get(key))
        if cached:
            _record_hit(_METRICS_EMB_KEY)
            return json.loads(cached)

        _record_miss(_METRICS_EMB_KEY)
        vector = self._delegate.embed_query(text)
        _safe_redis(lambda: get_redis_client().setex(
            key, config.EMBEDDING_CACHE_TTL, json.dumps(vector),
        ))
        return vector

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入。已缓存的直接复用，未命中的走原始 API。"""
        if not self.enabled or not texts:
            return self._delegate.embed_documents(texts)

        results = [None] * len(texts)
        uncached_idx: List[int] = []
        uncached_texts: List[str] = []

        client = get_redis_client()
        for i, text in enumerate(texts):
            key = f"rag:emb:{_hash(text)}"
            cached = _safe_redis(lambda: client.get(key))
            if cached:
                results[i] = json.loads(cached)
                _record_hit(_METRICS_EMB_KEY)
            else:
                uncached_idx.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            _safe_redis(lambda: client.hincrby(_METRICS_EMB_KEY, "misses", len(uncached_texts)))
            new_vectors = self._delegate.embed_documents(uncached_texts)
            pipe = client.pipeline(transaction=False)
            for j, idx in enumerate(uncached_idx):
                vec = new_vectors[j]
                results[idx] = vec
                key = f"rag:emb:{_hash(uncached_texts[j])}"
                pipe.setex(key, config.EMBEDDING_CACHE_TTL, json.dumps(vec))
            _safe_redis(lambda: pipe.execute())

        return results


# ══════════════════════════════════════════════════════════
# Layer 2: SearchResultCache
# ══════════════════════════════════════════════════════════

_METRICS_SEARCH_KEY = "rag:metrics:search"


class SearchResultCache:
    """缓存 _search_knowledge_base(query) → 格式化上下文。

    Key = rag:search:v{doc_version}:{md5(query)}
    文档入库 → bump_doc_version() → 所有旧 key 自然失效。
    """

    def __init__(self):
        self._enabled = config.SEARCH_CACHE_ENABLED

    @property
    def enabled(self) -> bool:
        return self._enabled and _redis_ok()

    def get(self, query: str) -> Optional[str]:
        if not self.enabled:
            return None
        doc_ver = get_doc_version()
        key = f"rag:search:v{doc_ver}:{_hash(query)}"
        result = _safe_redis(lambda: get_redis_client().get(key))
        if result:
            _record_hit(_METRICS_SEARCH_KEY)
            logger.debug("SearchResultCache HIT query=%.80s", query)
            return result.decode("utf-8") if isinstance(result, bytes) else result
        _record_miss(_METRICS_SEARCH_KEY)
        return None

    def set(self, query: str, result: str):
        if not self.enabled:
            return
        doc_ver = get_doc_version()
        key = f"rag:search:v{doc_ver}:{_hash(query)}"
        _safe_redis(lambda: get_redis_client().setex(
            key, config.SEARCH_CACHE_TTL, result,
        ))


# ══════════════════════════════════════════════════════════
# Layer 3: RerankerCache
# ══════════════════════════════════════════════════════════

_METRICS_RERANK_KEY = "rag:metrics:rerank"


class RerankerCache:
    """缓存 (query, doc) → score，减少 CrossEncoder 模型推理。"""

    def __init__(self):
        self._enabled = config.RERANKER_CACHE_ENABLED

    @property
    def enabled(self) -> bool:
        return self._enabled and _redis_ok()

    def _key(self, query: str, doc: str) -> str:
        # 取 doc 前 500 字符做 hash，控制 key 长度
        return f"rag:rerank:{_hash(query + doc[:500])}"

    def get_scores(self, query: str, documents: List[str]) -> List[Optional[float]]:
        """批量读取缓存，未命中返回 None。"""
        if not self.enabled:
            return [None] * len(documents)

        client = get_redis_client()
        results: List[Optional[float]] = []
        hit_count = 0
        for doc in documents:
            val = _safe_redis(lambda: client.get(self._key(query, doc)))
            if val is not None:
                results.append(float(val))
                hit_count += 1
            else:
                results.append(None)
        if hit_count > 0:
            _safe_redis(lambda: client.hincrby(_METRICS_RERANK_KEY, "hits", hit_count))
        return results

    def set_scores(self, query: str, documents: List[str], scores: List[float]):
        """批量写入缓存。"""
        if not self.enabled:
            return
        client = get_redis_client()
        pipe = client.pipeline(transaction=False)
        for doc, score in zip(documents, scores):
            pipe.setex(self._key(query, doc), config.RERANKER_CACHE_TTL, str(score))
        miss_count = len(documents)
        _safe_redis(lambda: (
            pipe.execute(),
            client.hincrby(_METRICS_RERANK_KEY, "misses", miss_count),
        ))


# ══════════════════════════════════════════════════════════
# 命中率统计
# ══════════════════════════════════════════════════════════

def _record_hit(metrics_key: str):
    _safe_redis(lambda: get_redis_client().hincrby(metrics_key, "hits", 1))


def _record_miss(metrics_key: str):
    _safe_redis(lambda: get_redis_client().hincrby(metrics_key, "misses", 1))


def get_cache_metrics() -> dict:
    """获取所有缓存层的命中率汇总。

    Returns:
        {
            "doc_version": 3,
            "embedding": {"hits": 100, "misses": 20, "hit_rate": 0.8333},
            "search":    {"hits": 50,  "misses": 10, "hit_rate": 0.8333},
            "rerank":    {"hits": 200, "misses": 50, "hit_rate": 0.8},
        }
    """
    if not _redis_ok():
        return {"doc_version": 0, "embedding": {}, "search": {}, "rerank": {}}

    def _read_metrics(key: str) -> dict:
        client = get_redis_client()
        raw = _safe_redis(lambda: client.hgetall(key), default={})
        if not raw:
            return {"hits": 0, "misses": 0, "hit_rate": 0.0}
        hits = int(raw.get(b"hits", raw.get("hits", 0)))
        misses = int(raw.get(b"misses", raw.get("misses", 0)))
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
        }

    return {
        "doc_version": get_doc_version(),
        "embedding": _read_metrics(_METRICS_EMB_KEY),
        "search": _read_metrics(_METRICS_SEARCH_KEY),
        "rerank": _read_metrics(_METRICS_RERANK_KEY),
    }


def reset_cache_metrics():
    """重置所有缓存命中率计数器。"""
    if not _redis_ok():
        return
    client = get_redis_client()
    for key in (_METRICS_EMB_KEY, _METRICS_SEARCH_KEY, _METRICS_RERANK_KEY):
        _safe_redis(lambda k=key: client.delete(k))
