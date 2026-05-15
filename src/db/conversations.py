"""
CRUD для таблицы conversations (история диалога).
"""
from .database import get_db


async def add_message(user_id: int, role: str, content: str) -> None:
    """Сохраняет сообщение в историю."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content[:2000]),
        )
        await db.commit()
    finally:
        await db.close()


async def get_history(
    user_id: int, limit: int = 10, timeout_minutes: int = 30
) -> list[dict]:
    """Возвращает историю в формате [{role, content}] (хронологический порядок)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT role, content FROM conversations
               WHERE user_id = ?
                 AND created_at > datetime('now', ? || ' minutes')
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, f"-{timeout_minutes}", limit * 2),
        )
        rows = await cursor.fetchall()
        # Reverse to chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    finally:
        await db.close()


async def clear(user_id: int) -> None:
    """Очищает историю диалога пользователя."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM conversations WHERE user_id = ?", (user_id,)
        )
        await db.commit()
    finally:
        await db.close()


async def cleanup_old(days: int = 7) -> int:
    """Удаляет записи старше N дней. Возвращает количество удалённых."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM conversations WHERE created_at < datetime('now', ? || ' days')",
            (f"-{days}",),
        )
        await db.commit()
        return cursor.rowcount
    finally:
        await db.close()
