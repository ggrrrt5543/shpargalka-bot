"""
Кэширование ответов в SQLite. Ключ = хеш(вопрос + предмет).
"""
import hashlib

from .database import db_read, db_read_all, db_write


def _hash_question(question: str, subject: str | None = None) -> str:
    """SHA-256 хеш нормализованного вопроса + предмет."""
    normalized = " ".join(question.lower().strip().split())
    if subject and subject != "auto":
        normalized += f"||{subject}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_cached(question: str, ttl_hours: int = 24, subject: str | None = None) -> str | None:
    h = _hash_question(question, subject)
    row = await db_read(
        """SELECT answer FROM cache
           WHERE question_hash = ? AND created_at > datetime('now', ? || ' hours')""",
        (h, f"-{ttl_hours}"),
    )
    return row[0] if row else None


async def put_cached(question: str, answer: str, subject: str | None = None) -> None:
    h = _hash_question(question, subject)
    await db_write(
        """INSERT OR REPLACE INTO cache
           (question_hash, question_text, answer, subject, created_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (h, question[:500], answer, subject),
    )


async def clear_all() -> int:
    row = await db_read("SELECT COUNT(*) FROM cache")
    count = row[0] if row else 0
    await db_write("DELETE FROM cache", ())
    return count


async def get_cache_size() -> int:
    row = await db_read("SELECT COUNT(*) FROM cache")
    return row[0] if row else 0
