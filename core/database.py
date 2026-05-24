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

    # 2. 建表users
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
        conn.commit()
    finally:
        if conn:
            conn.close()