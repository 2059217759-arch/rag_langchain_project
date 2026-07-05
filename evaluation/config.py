"""评测模块独立配置。

从项目根 .env 读取评测相关变量，不依赖 core.config。
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── 路径 ────────────────────────────────────────────
# 项目根目录（evaluation/ 的上级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# ── DeepSeek (评测 LLM) ─────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# ── DashScope (评测 Embeddings) ─────────────────────
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
os.environ.setdefault("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY)

# ── MySQL (eval_results 表) ─────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "rag_db")
