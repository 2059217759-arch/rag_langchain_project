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

# ── Text Splitter ──────────────────────────────────
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
SEPARATORS = ["\n\n", "\n", ".", "!", "?", "。", "！", "？", " ", ""]
MAX_SPLIT_CHAR_NUMBER = 1000

# ── Chat Model ─────────────────────────────────────
CHAT_MODEL_NAME = "qwen-max"

# ── Chat Window ────────────────────────────────────
WINDOW_SIZE = 10  # 滑动窗口保留最近消息条数（≈5轮问答）

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
