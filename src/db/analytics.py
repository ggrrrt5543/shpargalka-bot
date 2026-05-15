"""
Аналитика и статистика использования бота.
"""
from .database import get_db


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
    """Логирует событие в таблицу analytics."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO analytics
               (user_id, question_type, subject, response_time_ms,
                cache_hit, rag_used, rag_chunks_count, verifier_corrected, action_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                question_type,
                subject,
                response_time_ms,
                int(cache_hit),
                int(rag_used),
                rag_chunks_count,
                int(verifier_corrected),
                action_type,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_stats(period: str = "all") -> dict:
    """Возвращает общую статистику.

    period: '24h', '7d', 'all'
    """
    if period == "24h":
        where = "AND created_at > datetime('now', '-1 day')"
    elif period == "7d":
        where = "AND created_at > datetime('now', '-7 days')"
    else:
        where = ""

    db = await get_db()
    try:
        # Общее количество запросов
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM analytics WHERE action_type = 'query' {where}"
        )
        row = await cursor.fetchone()
        total_queries = row[0] if row else 0

        # Уникальные пользователи
        cursor = await db.execute(
            f"SELECT COUNT(DISTINCT user_id) FROM analytics WHERE action_type = 'query' {where}"
        )
        row = await cursor.fetchone()
        unique_users = row[0] if row else 0

        # Среднее время ответа
        cursor = await db.execute(
            f"""SELECT AVG(response_time_ms) FROM analytics
                WHERE action_type = 'query' AND response_time_ms IS NOT NULL {where}"""
        )
        row = await cursor.fetchone()
        avg_response_ms = int(row[0]) if row and row[0] else 0

        # Cache hit rate
        cursor = await db.execute(
            f"""SELECT
                SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as hits,
                COUNT(*) as total
                FROM analytics WHERE action_type = 'query' {where}"""
        )
        row = await cursor.fetchone()
        cache_hits = row[0] or 0 if row else 0
        cache_total = row[1] or 1 if row else 1
        cache_hit_rate = round(cache_hits / cache_total * 100, 1)

        # Топ-3 предмета
        cursor = await db.execute(
            f"""SELECT subject, COUNT(*) as cnt FROM analytics
                WHERE action_type = 'query' AND subject IS NOT NULL {where}
                GROUP BY subject ORDER BY cnt DESC LIMIT 3"""
        )
        rows = await cursor.fetchall()
        top_subjects = [(r[0], r[1]) for r in rows]

        # Исправления верификатора
        cursor = await db.execute(
            f"""SELECT SUM(verifier_corrected) FROM analytics
                WHERE action_type = 'query' {where}"""
        )
        row = await cursor.fetchone()
        verifier_corrections = row[0] or 0 if row else 0

        # RAG usage
        cursor = await db.execute(
            f"""SELECT SUM(rag_used) FROM analytics
                WHERE action_type = 'query' {where}"""
        )
        row = await cursor.fetchone()
        rag_queries = row[0] or 0 if row else 0

        return {
            "total_queries": total_queries,
            "unique_users": unique_users,
            "avg_response_ms": avg_response_ms,
            "cache_hit_rate": cache_hit_rate,
            "top_subjects": top_subjects,
            "verifier_corrections": verifier_corrections,
            "rag_queries": rag_queries,
        }
    finally:
        await db.close()


async def get_user_stats(user_id: int) -> dict:
    """Возвращает статистику конкретного пользователя."""
    db = await get_db()
    try:
        # Всего задач
        cursor = await db.execute(
            "SELECT COUNT(*) FROM analytics WHERE user_id = ? AND action_type = 'query'",
            (user_id,),
        )
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # Любимый предмет
        cursor = await db.execute(
            """SELECT subject, COUNT(*) as cnt FROM analytics
               WHERE user_id = ? AND action_type = 'query' AND subject IS NOT NULL
               GROUP BY subject ORDER BY cnt DESC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        fav_subject = row[0] if row else None

        # Среднее время
        cursor = await db.execute(
            """SELECT AVG(response_time_ms) FROM analytics
               WHERE user_id = ? AND action_type = 'query' AND response_time_ms IS NOT NULL""",
            (user_id,),
        )
        row = await cursor.fetchone()
        avg_ms = int(row[0]) if row and row[0] else 0

        return {
            "total_queries": total,
            "favorite_subject": fav_subject,
            "avg_response_ms": avg_ms,
        }
    finally:
        await db.close()
