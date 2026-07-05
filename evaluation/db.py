"""评测模块独立数据库层。

只操作 eval_results 表，不依赖 core.database。
"""

import logging

import pymysql

from evaluation import config

logger = logging.getLogger(__name__)


def _get_conn() -> pymysql.connections.Connection:
    """获取 MySQL 连接（每次新建，简单可靠）。"""
    return pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def ensure_table() -> None:
    """幂等建表。"""
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_results (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    dataset_name    VARCHAR(255) NOT NULL,
                    question        TEXT NOT NULL,
                    answer          MEDIUMTEXT,
                    contexts        JSON,
                    reference       TEXT,
                    faithfulness        DOUBLE DEFAULT NULL,
                    answer_relevancy    DOUBLE DEFAULT NULL,
                    context_precision   DOUBLE DEFAULT NULL,
                    context_recall      DOUBLE DEFAULT NULL,
                    eval_latency_ms     INT DEFAULT 0,
                    error_message       VARCHAR(1000) DEFAULT NULL,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_eval_dataset (dataset_name),
                    INDEX idx_eval_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        conn.commit()
        logger.debug("eval_results 表已确认存在")
    except Exception:
        logger.error("eval_results 建表失败", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()


def insert_eval_results(rows: list[dict]) -> None:
    """批量插入评测结果。"""
    if not rows:
        return
    ensure_table()

    _defaults = {
        "dataset_name": "", "question": "", "answer": None, "contexts": None,
        "reference": None, "faithfulness": None, "answer_relevancy": None,
        "context_precision": None, "context_recall": None,
        "eval_latency_ms": 0, "error_message": None,
    }
    normalized = [{**_defaults, **row} for row in rows]

    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO eval_results
                    (dataset_name, question, answer, contexts, reference,
                     faithfulness, answer_relevancy, context_precision,
                     context_recall, eval_latency_ms, error_message)
                VALUES (%(dataset_name)s, %(question)s, %(answer)s, %(contexts)s,
                        %(reference)s, %(faithfulness)s, %(answer_relevancy)s,
                        %(context_precision)s, %(context_recall)s,
                        %(eval_latency_ms)s, %(error_message)s)
                """,
                normalized,
            )
        conn.commit()
        logger.info("已写入 %d 条评测结果", len(rows))
    finally:
        if conn:
            conn.close()


def get_eval_results(dataset_name: str | None = None, limit: int = 100) -> list[dict]:
    """查询评测结果明细。"""
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if dataset_name:
                cur.execute(
                    "SELECT * FROM eval_results WHERE dataset_name = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (dataset_name, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM eval_results ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            return cur.fetchall()
    except Exception:
        logger.error("查询评测结果失败", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


def get_eval_summary(dataset_name: str | None = None) -> dict:
    """获取评测指标汇总（平均值）。"""
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if dataset_name:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_samples,
                        COALESCE(AVG(faithfulness), 0) AS avg_faithfulness,
                        COALESCE(AVG(answer_relevancy), 0) AS avg_answer_relevancy,
                        COALESCE(AVG(context_precision), 0) AS avg_context_precision,
                        COALESCE(AVG(context_recall), 0) AS avg_context_recall,
                        COALESCE(AVG(eval_latency_ms), 0) AS avg_latency_ms
                    FROM eval_results
                    WHERE dataset_name = %s AND error_message IS NULL
                    """,
                    (dataset_name,),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_samples,
                        COALESCE(AVG(faithfulness), 0) AS avg_faithfulness,
                        COALESCE(AVG(answer_relevancy), 0) AS avg_answer_relevancy,
                        COALESCE(AVG(context_precision), 0) AS avg_context_precision,
                        COALESCE(AVG(context_recall), 0) AS avg_context_recall,
                        COALESCE(AVG(eval_latency_ms), 0) AS avg_latency_ms
                    FROM eval_results
                    WHERE error_message IS NULL
                    """
                )
            return cur.fetchone()
    except Exception:
        logger.error("查询评测汇总失败", exc_info=True)
        return {}
    finally:
        if conn:
            conn.close()
