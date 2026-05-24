import os
import hashlib
from datetime import datetime

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import config


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


class IngestionService:
    def __init__(self):
        os.makedirs(config.PERSIST_DIRECTORY, exist_ok=True)
        self.chroma = Chroma(
            collection_name=config.COLLECTION_NAME,
            embedding_function=DashScopeEmbeddings(model="text-embedding-v4"),
            persist_directory=config.PERSIST_DIRECTORY,
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            separators=config.SEPARATORS,
            length_function=len,
        )

    def upload_by_str(self, data: str, file_name: str) -> str:
        md5_hex = _get_string_md5(data)

        if _check_md5(md5_hex):
            return "[跳过]内容已存在知识库"
        if len(data) < 10:
            return "[失败]内容过短"

        if len(data) > config.MAX_SPLIT_CHAR_NUMBER:
            chunks: list[str] = self.splitter.split_text(data)
        else:
            chunks = [data]

        metadata = {
            "source": file_name,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "zhuohao",
        }
        self.chroma.add_texts(
            chunks,
            metadatas=[metadata for _ in chunks],
        )
        _save_md5(md5_hex)
        return "[成功]已成功载入向量库"
