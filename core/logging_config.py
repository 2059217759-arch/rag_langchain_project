import logging
import os
from logging.handlers import RotatingFileHandler

from core import config

_logging_initialized = False


def setup_logging():
    """集中配置日志系统，幂等（重复调用安全）。

    日志目录: logs/
      app.log   — INFO 及以上，日常运维
      error.log — WARNING 及以上，告警 + 错误
      debug.log — DEBUG 及以上，开发调试

    通过环境变量 LOG_LEVEL 控制级别（默认 INFO）。
    """
    global _logging_initialized
    if _logging_initialized:
        return

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    log_dir = os.path.join(config.BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # root 放开到 DEBUG，各 handler 自己控制输出级别
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ── console: INFO+ → stderr ──────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    # ── app.log: INFO+ ───────────────────────────────
    root.addHandler(_rotating(os.path.join(log_dir, "app.log"), logging.INFO, fmt))

    # ── error.log: WARNING+ ──────────────────────────
    root.addHandler(_rotating(os.path.join(log_dir, "error.log"), logging.WARNING, fmt))

    # ── debug.log: DEBUG+ ────────────────────────────
    root.addHandler(_rotating(os.path.join(log_dir, "debug.log"), logging.DEBUG, fmt))

    # ── llm_trace.log: 独立 logger，记录 LLM 请求/响应原始 JSON ──
    trace_fmt = logging.Formatter("%(message)s")
    llm_logger = logging.getLogger("llm_trace")
    llm_logger.setLevel(logging.DEBUG)
    llm_logger.propagate = False  # 不重复输出到 root handler
    llm_logger.addHandler(_rotating(os.path.join(log_dir, "llm_trace.log"), logging.DEBUG, trace_fmt))

    _logging_initialized = True
    logging.getLogger(__name__).info(
        "日志系统已就绪 (level=%s, dir=%s)", log_level, log_dir
    )


def _rotating(path: str, level: int, fmt: logging.Formatter) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(fmt)
    return handler
