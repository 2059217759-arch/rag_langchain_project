import logging
import pymysql
import threading
from dbutils.pooled_db import PooledDB

from core import config

logger = logging.getLogger(__name__)

_pool = None
_initialized = False
_init_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _init_lock:
            if _pool is None:
                _pool = PooledDB(
                    creator=pymysql,
                    mincached=config.MYSQL_POOL_MIN,
                    maxconnections=config.MYSQL_POOL_MAX,
                    host=config.MYSQL_HOST,
                    port=config.MYSQL_PORT,
                    user=config.MYSQL_USER,
                    password=config.MYSQL_PASSWORD,
                    database=config.MYSQL_DATABASE,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor,
                )
                logger.info(
                    "MySQL 连接池已创建 host=%s:%d db=%s min=%d max=%d",
                    config.MYSQL_HOST, config.MYSQL_PORT, config.MYSQL_DATABASE,
                    config.MYSQL_POOL_MIN, config.MYSQL_POOL_MAX,
                )
    return _pool


def get_connection():
    """从连接池获取 MySQL 连接，首次调用自动建库建表。"""
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                _init_db()
                _initialized = True
    return _get_pool().connection()


def _make_connection(database: str):
    conn = None
    try:
        conn = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn
    except Exception as e:
        if conn:
            conn.close()
        raise e


def _init_db():
    """建库 + 建用户表，幂等。"""
    # 1. 建库
    conn = None
    try:
        conn = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            charset="utf8mb4",
        )
        with conn.cursor() as cur:
            db_name = config.MYSQL_DATABASE
            if not db_name.isidentifier():
                raise ValueError("Invalid database name")
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        logger.debug("数据库已确认存在 db=%s", db_name)
    except Exception:
        logger.error("数据库初始化失败", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()

    # 2. 建表
    conn = None
    try:
        conn = _make_connection(config.MYSQL_DATABASE)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    username    VARCHAR(64)  NOT NULL UNIQUE,
                    password    VARCHAR(256) NOT NULL,
                    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
                    session_id  VARCHAR(128) NOT NULL,
                    message     JSON NOT NULL,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_session_id (session_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_parents (
                    parent_id       VARCHAR(32) PRIMARY KEY,
                    parent_content  MEDIUMTEXT NOT NULL,
                    parent_title    VARCHAR(500) DEFAULT '',
                    source          VARCHAR(255) DEFAULT '',
                    create_time     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    operator        VARCHAR(50) DEFAULT 'zhuohao',
                    child_count     INT DEFAULT 0,
                    INDEX idx_source (source)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
                    session_id          VARCHAR(128) NOT NULL,
                    question            VARCHAR(500) NOT NULL,
                    total_latency_ms    INT NOT NULL,
                    retrieval_latency_ms INT DEFAULT 0,
                    llm_latency_ms      INT DEFAULT 0,
                    tool_call_count     INT DEFAULT 0,
                    tool_details        JSON,
                    input_tokens        INT DEFAULT 0,
                    output_tokens       INT DEFAULT 0,
                    cache_read_tokens   INT DEFAULT 0,
                    reasoning_tokens    INT DEFAULT 0,
                    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_metrics_session (session_id),
                    INDEX idx_metrics_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        conn.commit()
    finally:
        if conn:
            conn.close()


def insert_parents(parents: list[dict]) -> None:
    """批量插入父块到 document_parents 表。"""
    if not parents:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO document_parents
                    (parent_id, parent_content, parent_title, source, create_time, operator, child_count)
                VALUES (%(parent_id)s, %(parent_content)s, %(parent_title)s,
                        %(source)s, %(create_time)s, %(operator)s, %(child_count)s)
                """,
                parents,
            )
        conn.commit()
    finally:
        conn.close()


def get_parents_by_ids(parent_ids: list[str]) -> dict:
    """按 parent_id 列表查询父块，返回 {parent_id: row} 字典。"""
    if not parent_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(parent_ids))
            cur.execute(
                f"SELECT parent_id, parent_content, parent_title, source "
                f"FROM document_parents WHERE parent_id IN ({placeholders})",
                parent_ids,
            )
            rows = cur.fetchall()
        return {row["parent_id"]: row for row in rows}
    finally:
        conn.close()
