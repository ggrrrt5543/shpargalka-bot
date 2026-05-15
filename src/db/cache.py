"""
Кэширование ответов в SQLite.
"""
import hashlib

from .database import get_db


def _hash_question(question: str) -> str:
    """SHA-256 хеш нормализованного вопроса."""
    normalized = " ".join(question.lower().strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_cached(question: str, ttl_hours: int = 24) -> str | None:
    """Возвращает кэшированный ответ или None если нет/истёк."""
    h = _hash_question(question)
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT answer FROM cache
               WHERE question_hash = ?
                 AND created_at > datetime('now', ? || ' hours')""",
            (h, f"-{ttl_hours}"),
        )
        row = await cursor.fetchone()
        return row[0] if row else None
    finally:
        await db.close()


async def put_cached(
    question: str, answer: str, subject: str | None = None
) -> None:
    """Сохраняет ответ в кэш."""
    h = _hash_question(question)
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO cache
               (question_hash, question_text, answer, subject, created_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (h, question[:500], answer, subject),
        )
        await db.commit()
    finally:
        await db.close()


async def clear_all() -> int:
    """Очищает весь кэш. Возвращает количество удалённых записей."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM cache")
        row = await cursor.fetchone()
        count = row[0] if row else 0
        await db.execute("DELETE FROM cache")
        await db.commit()
        return count
    finally:
        await db.close()


async def clear_expired(ttl_hours: int = 24) -> int:
    """Удаляет просроченные записи."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM cache WHERE created_at < datetime('now', ? || ' hours')",
            (f"-{ttl_hours}",),
        )
        await db.commit()
        return cursor.rowcount
    finally:
        await db.close()


async def get_cache_size() -> int:
    """Возвращает количество записей в кэше."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM cache")
        row = await cursor.fetchone()
        return row[0] if row else 0
    finally:
        await db.close()
