import json
import logging

from core.database import get_connection

logger = logging.getLogger(__name__)


def save_metrics(
    session_id: str,
    question: str,
    total_ms: int,
    retrieval_ms: int,
    llm_ms: int,
    tool_call_count: int,
    tool_details: list[str],
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    reasoning_tokens: int,
) -> None:
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO metrics
                        (session_id, question, total_latency_ms, retrieval_latency_ms,
                         llm_latency_ms, tool_call_count, tool_details,
                         input_tokens, output_tokens, cache_read_tokens, reasoning_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        question[:500],
                        total_ms,
                        retrieval_ms,
                        llm_ms,
                        tool_call_count,
                        json.dumps(tool_details, ensure_ascii=False) if tool_details else None,
                        input_tokens,
                        output_tokens,
                        cache_read_tokens,
                        reasoning_tokens,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Failed to save metrics", exc_info=True)


def _build_where(days: int, session_id: str | None) -> tuple[str, list]:
    where = "WHERE created_at >= NOW() - INTERVAL %s DAY"
    params: list = [days]
    if session_id:
        where += " AND session_id = %s"
        params.append(session_id)
    return where, params


def get_metrics_summary(session_id: str | None = None, days: int = 7) -> dict:
    conn = get_connection()
    try:
        where, params = _build_where(days, session_id)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS total_queries,
                    COALESCE(AVG(total_latency_ms), 0) AS avg_latency_ms,
                    COALESCE(MIN(total_latency_ms), 0) AS min_latency_ms,
                    COALESCE(MAX(total_latency_ms), 0) AS max_latency_ms,
                    COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                    COALESCE(SUM(cache_read_tokens), 0) AS total_cache_read_tokens,
                    COALESCE(AVG(tool_call_count), 0) AS avg_tool_calls,
                    COALESCE(AVG(retrieval_latency_ms), 0) AS avg_retrieval_ms,
                    COALESCE(AVG(llm_latency_ms), 0) AS avg_llm_ms
                FROM metrics
                {where}
                """,
                params,
            )
            row = cur.fetchone()

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT total_latency_ms FROM metrics {where} ORDER BY total_latency_ms",
                params,
            )
            latencies = [r["total_latency_ms"] for r in cur.fetchall()]

        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        p99 = _percentile(latencies, 0.99)

        buckets = {"0-1s": 0, "1-3s": 0, "3-5s": 0, "5-10s": 0, "10-30s": 0, "30s+": 0}
        for lat in latencies:
            if lat < 1000:
                buckets["0-1s"] += 1
            elif lat < 3000:
                buckets["1-3s"] += 1
            elif lat < 5000:
                buckets["3-5s"] += 1
            elif lat < 10000:
                buckets["5-10s"] += 1
            elif lat < 30000:
                buckets["10-30s"] += 1
            else:
                buckets["30s+"] += 1

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    DATE(created_at) AS day,
                    COUNT(*) AS queries,
                    COALESCE(AVG(total_latency_ms), 0) AS avg_latency_ms,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens
                FROM metrics
                {where}
                GROUP BY DATE(created_at)
                ORDER BY day
                """,
                params,
            )
            daily_rows = cur.fetchall()

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT tool_call_count, COUNT(*) AS cnt
                FROM metrics
                {where}
                GROUP BY tool_call_count
                ORDER BY tool_call_count
                """,
                params,
            )
            tool_dist = {r["tool_call_count"]: r["cnt"] for r in cur.fetchall()}

        return {
            **(row or {}),
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "latency_buckets": buckets,
            "daily_trend": [
                {
                    "day": str(r["day"]),
                    "queries": r["queries"],
                    "avg_latency_ms": int(r["avg_latency_ms"]),
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                }
                for r in daily_rows
            ],
            "tool_distribution": tool_dist,
        }
    finally:
        conn.close()


def get_recent_metrics(session_id: str | None = None, limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if session_id:
                cur.execute(
                    "SELECT * FROM metrics WHERE session_id = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (session_id, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM metrics ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        return [
            {
                "session_id": r["session_id"],
                "question": r["question"],
                "total_latency_ms": r["total_latency_ms"],
                "retrieval_latency_ms": r["retrieval_latency_ms"],
                "llm_latency_ms": r["llm_latency_ms"],
                "tool_call_count": r["tool_call_count"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cache_read_tokens": r["cache_read_tokens"],
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _percentile(sorted_data: list, pct: float) -> int:
    if not sorted_data:
        return 0
    idx = int(len(sorted_data) * pct)
    return sorted_data[min(idx, len(sorted_data) - 1)]
