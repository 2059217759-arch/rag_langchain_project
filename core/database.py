import pymysql
import threading # 多线程
from core import config

_initialized = False
_init_lock = threading.Lock()


def get_connection():
    """返回 MySQL 连接，首次调用自动建库建表。"""
    global _initialized
    if not _initialized:
        # 使用锁确保多线程下只初始化一次
        with _init_lock:
            if not _initialized:  # 双重检查锁定
                _init_db()
                _initialized = True
    return _make_connection(config.MYSQL_DATABASE)


# 连接数据库
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
            # 简单校验数据库名，防止注入
            db_name = config.MYSQL_DATABASE
            if not db_name.isidentifier():
                raise ValueError("Invalid database name")
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
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
                CREATE TABLE IF NOT EXISTS chat_summary (
                    session_id              VARCHAR(128) PRIMARY KEY,
                    summary                 TEXT,
                    last_summarized_msg_id  BIGINT DEFAULT 0,
                    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
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