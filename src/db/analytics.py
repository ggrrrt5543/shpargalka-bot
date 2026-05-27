"""
Аналитика и статистика.
"""
from .database import db_read, db_read_all, db_write


async def log_event(
    user_id: int,
    question_type: str = "text",
    subject: str | None = None,
    response_time_ms: int | None = None,
    cache_hit: bool = False,
    rag_used: bool = False,
    rag_chunks_count: int = 0,
    verifier_corrected: bool = False,
    action_type: str = "query",
) -> None:
    await db_write(
        """INSERT INTO analytics
           (user_id, question_type, subject, response_time_ms,
            cache_hit, rag_used, rag_chunks_count, verifier_corrected, action_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, question_type, subject, response_time_ms,
         int(cache_hit), int(rag_used), rag_chunks_count,
         int(verifier_corrected), action_type),
    )


async def get_stats(period: str = "all") -> dict:
    if period == "24h":
        w = "AND created_at > datetime('now', '-1 day')"
    elif period == "7d":
        w = "AND created_at > datetime('now', '-7 days')"
    else:
        w = ""

    total = (await db_read(f"SELECT COUNT(*) FROM analytics WHERE action_type='query' {w}"))[0]
    users = (await db_read(f"SELECT COUNT(DISTINCT user_id) FROM analytics WHERE action_type='query' {w}"))[0]
    avg_row = await db_read(f"SELECT AVG(response_time_ms) FROM analytics WHERE action_type='query' AND response_time_ms IS NOT NULL {w}")
    avg_ms = int(avg_row[0]) if avg_row and avg_row[0] else 0

    cache_row = await db_read(f"SELECT SUM(CASE WHEN cache_hit=1 THEN 1 ELSE 0 END), COUNT(*) FROM analytics WHERE action_type='query' {w}")
    hits = cache_row[0] or 0
    tot = cache_row[1] or 1
    cache_rate = round(hits / tot * 100, 1)

    subjects = await db_read_all(f"SELECT subject, COUNT(*) as c FROM analytics WHERE action_type='query' AND subject IS NOT NULL {w} GROUP BY subject ORDER BY c DESC LIMIT 3")
    top_subjects = [(r[0], r[1]) for r in subjects]

    ver_row = await db_read(f"SELECT SUM(verifier_corrected) FROM analytics WHERE action_type='query' {w}")
    verifier_corrections = ver_row[0] or 0

    rag_row = await db_read(f"SELECT SUM(rag_used) FROM analytics WHERE action_type='query' {w}")
    rag_queries = rag_row[0] or 0

    return {
        "total_queries": total, "unique_users": users,
        "avg_response_ms": avg_ms, "cache_hit_rate": cache_rate,
        "top_subjects": top_subjects, "verifier_corrections": verifier_corrections,
        "rag_queries": rag_queries,
    }


async def get_user_stats(user_id: int) -> dict:
    total = (await db_read("SELECT COUNT(*) FROM analytics WHERE user_id=? AND action_type='query'", (user_id,)))[0]
    fav = await db_read("SELECT subject FROM analytics WHERE user_id=? AND action_type='query' AND subject IS NOT NULL GROUP BY subject ORDER BY COUNT(*) DESC LIMIT 1", (user_id,))
    avg = await db_read("SELECT AVG(response_time_ms) FROM analytics WHERE user_id=? AND action_type='query' AND response_time_ms IS NOT NULL", (user_id,))
    return {
        "total_queries": total,
        "favorite_subject": fav[0] if fav else None,
        "avg_response_ms": int(avg[0]) if avg and avg[0] else 0,
    }
