import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ── API Keys ───────────────────────────────────────
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
os.environ["DASHSCOPE_API_KEY"] = DASHSCOPE_API_KEY or ""

# ── ChromaDB ───────────────────────────────────────
COLLECTION_NAME = "rag"
PERSIST_DIRECTORY = os.path.join(DATA_DIR, "chroma_db")

# ── Parent-Child Chunking ─────────────────────────
PARENT_MAX_SIZE = 4000       # 父块超过此值触发二次切分
CHILD_CHUNK_SIZE = 300       # 子块目标大小（字符）
CHILD_CHUNK_OVERLAP = 50     # 子块重叠量
TOP_K_CHILDREN = 8           # 向量检索时返回多少个子块
TOP_K_BM25 = 8               # BM25 检索时返回多少个子块
TOP_K_PARENTS = 4            # 最终返回多少个父块给 LLM
RRF_K = 60                   # RRF 融合常数
RERANKER_MODEL = os.path.join(DATA_DIR, "models", "bce-reranker-base_v1")

# ── Chat Model ─────────────────────────────────────
CHAT_MODEL_NAME = "qwen-max"

# ── Chat Window ────────────────────────────────────
WINDOW_SIZE = 10  # 滑动窗口保留最近消息条数（≈5轮问答）

# ── BM25 Index ────────────────────────────────────
BM25_INDEX_PATH = os.path.join(DATA_DIR, "bm25_index.pkl")

# ── MD5 Dedup ─────────────────────────────────────
MD5_PATH = os.path.join(DATA_DIR, "md5.text")

# ── MySQL ───────────────────────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "rag_db")

# ── JWT ────────────────────────────────────────────
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default-secret")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
