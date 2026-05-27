import os
import re
import hashlib
from datetime import datetime

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import config
from core.database import insert_parents


def _check_md5(md5_str: str) -> bool:
    if not os.path.exists(config.MD5_PATH):
        open(config.MD5_PATH, "w", encoding="utf-8").close()
        return False
    for line in open(config.MD5_PATH, "r", encoding="utf-8").readlines():
        if line.strip() == md5_str:
            return True
    return False


def _save_md5(md5_str: str):
    with open(config.MD5_PATH, "a", encoding="utf-8") as f:
        f.write(md5_str + "\n")


def _get_string_md5(input_str: str, encoding: str = "utf-8") -> str:
    md5_obj = hashlib.md5()
    md5_obj.update(input_str.encode(encoding=encoding))
    return md5_obj.hexdigest()


class ParentChildSplitter:
    """父子块切分器：父块按 Markdown 标题 → 段落边界切分，子块在父块内按句子切分。"""

    _HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def __init__(
        self,
        parent_max: int = 4000,
        child_size: int = 300,
        child_overlap: int = 50,
    ):
        self.parent_max = parent_max
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap,
            separators=[
                "\n", "。", "！", "？", ".", "!", "?", "；", ";", "，", ",", " "
            ],
            length_function=len,
        )

    def split(self, text: str) -> list[dict]:
        """返回 [{parent_id, parent_title, parent_content, children: [...]}]"""
        raw_parents = self._split_parents(text)
        result = []
        for rp in raw_parents:
            parent_id = _get_string_md5(rp["content"])
            children = self.child_splitter.split_text(rp["content"])
            result.append({
                "parent_id": parent_id,
                "parent_title": rp["title"],
                "parent_content": rp["content"],
                "children": children,
            })
        return result

    # ── Parent 切分 ──────────────────────────────────

    def _split_parents(self, text: str) -> list[dict]:
        """Markdown 标题优先，超长则段落切分兜底。"""
        sections = self._split_by_headers(text)

        result = []
        for title, content in sections:
            if len(content) <= self.parent_max:
                result.append({"title": title, "content": content})
            else:
                result.extend(self._split_by_paragraphs(content, title))
        return result

    def _split_by_headers(self, text: str) -> list[tuple]:
        """按 Markdown 标题切分，返回 [(title, content), ...]。"""
        matches = list(self._HEADER_RE.finditer(text))

        if not matches:
            return [("", text)]

        sections = []
        for i, m in enumerate(matches):
            title = m.group(0).strip()
            start = m.start()  # 包含标题行本身
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append((title, content))

        # 第一个标题之前的文本作为无标题 preamble
        if matches and matches[0].start() > 0:
            preamble = text[:matches[0].start()].strip()
            if preamble:
                sections.insert(0, ("", preamble))

        return sections

    def _split_by_paragraphs(self, text: str, title: str) -> list[dict]:
        """超长 section 按 \n\n 段落边界二次切分。"""
        paragraphs = re.split(r"\n\s*\n", text)
        result = []
        buf = ""
        buf_title = title

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(buf) + len(para) <= self.parent_max:
                buf = buf + "\n\n" + para if buf else para
            else:
                if buf:
                    result.append({"title": buf_title, "content": buf})
                if len(para) > self.parent_max:
                    # 单段落超长，强制按句子切分
                    subs = self._force_split_long(para)
                    for i, sub in enumerate(subs):
                        result.append({
                            "title": f"{title}（续）" if i > 0 else title,
                            "content": sub,
                        })
                    buf = ""
                else:
                    buf = para
                buf_title = title

        if buf:
            result.append({"title": buf_title, "content": buf})
        return result

    def _force_split_long(self, text: str) -> list[str]:
        """对超长单段落按句子标点强制截断。"""
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        chunks = []
        buf = ""
        for sent in sentences:
            if len(buf) + len(sent) <= self.parent_max:
                buf += sent
            else:
                if buf:
                    chunks.append(buf)
                buf = sent
        if buf:
            chunks.append(buf)
        return chunks or [text]


# ── Ingestion Service ────────────────────────────────────

class IngestionService:
    def __init__(self):
        os.makedirs(config.PERSIST_DIRECTORY, exist_ok=True)
        self.chroma = Chroma(
            collection_name=config.COLLECTION_NAME,
            embedding_function=DashScopeEmbeddings(model="text-embedding-v4"),
            persist_directory=config.PERSIST_DIRECTORY,
        )
        self.splitter = ParentChildSplitter(
            parent_max=config.PARENT_MAX_SIZE,
            child_size=config.CHILD_CHUNK_SIZE,
            child_overlap=config.CHILD_CHUNK_OVERLAP,
        )

    def upload_by_str(self, data: str, file_name: str) -> str:
        md5_hex = _get_string_md5(data)

        if _check_md5(md5_hex):
            return "[跳过]内容已存在知识库"
        if len(data) < 10:
            return "[失败]内容过短"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parents = self.splitter.split(data)

        all_children = []
        parent_records = []
        seen_ids = set()

        for p in parents:
            if p["parent_id"] in seen_ids:
                continue
            seen_ids.add(p["parent_id"])

            parent_records.append({
                "parent_id": p["parent_id"],
                "parent_content": p["parent_content"],
                "parent_title": p["parent_title"],
                "source": file_name,
                "create_time": now,
                "operator": "zhuohao",
                "child_count": len(p["children"]),
            })

            for idx, child_text in enumerate(p["children"]):
                all_children.append((child_text, {
                    "source": file_name,
                    "create_time": now,
                    "operator": "zhuohao",
                    "parent_id": p["parent_id"],
                    "chunk_index": idx,
                    "chunk_count": len(p["children"]),
                }))

        # 父块写入 MySQL
        insert_parents(parent_records)

        # 子块写入 ChromaDB
        if all_children:
            texts, metadatas = zip(*all_children)
            self.chroma.add_texts(list(texts), metadatas=list(metadatas))

        _save_md5(md5_hex)
        return f"[成功]已载入向量库（{len(parent_records)} 个父块，{len(all_children)} 个子块）"
