"""
Хранение pending_answers в БД (переживает рестарт).
"""
from .database import db_read, db_write


async def save_pending(user_id: int, answer: str) -> None:
    """Сохраняет ответ до выбора формата."""
    await db_write(
        "INSERT OR REPLACE INTO pending (user_id, answer, created_at) "
        "VALUES (?, ?, CURRENT_TIMESTAMP)",
        (user_id, answer),
    )


async def get_pending(user_id: int) -> str | None:
    """Получает сохранённый ответ."""
    row = await db_read(
        "SELECT answer FROM pending WHERE user_id = ? AND created_at > datetime('now', '-1 hour')",
        (user_id,),
    )
    return row[0] if row else None


async def delete_pending(user_id: int) -> None:
    """Удаляет после использования."""
    await db_write("DELETE FROM pending WHERE user_id = ?", (user_id,))
