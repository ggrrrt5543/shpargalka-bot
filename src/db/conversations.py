"""
CRUD для таблицы conversations (история диалога).
"""
from .database import db_read_all, db_write


async def add_message(user_id: int, role: str, content: str) -> None:
    await db_write(
        "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content[:2000]),
    )


async def get_history(user_id: int, limit: int = 10, timeout_minutes: int = 30) -> list[dict]:
    rows = await db_read_all(
        """SELECT role, content FROM conversations
           WHERE user_id = ? AND created_at > datetime('now', ? || ' minutes')
           ORDER BY created_at DESC LIMIT ?""",
        (user_id, f"-{timeout_minutes}", limit * 2),
    )
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


async def clear(user_id: int) -> None:
    await db_write("DELETE FROM conversations WHERE user_id = ?", (user_id,))
