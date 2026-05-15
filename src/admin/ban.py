"""
Бан/разбан пользователей.
"""
from src.db.database import get_db


async def is_banned(user_id: int) -> bool:
    """Проверяет, забанен ли пользователь."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row is not None
    finally:
        await db.close()


async def get_ban_status(user_id: int) -> bool:
    """Алиас для is_banned."""
    return await is_banned(user_id)


async def toggle_ban(target_id: int, banned_by: int) -> str:
    """Переключает бан. Возвращает текст результата."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT user_id FROM banned_users WHERE user_id = ?", (target_id,)
        )
        row = await cursor.fetchone()
        if row:
            # Разбан
            await db.execute(
                "DELETE FROM banned_users WHERE user_id = ?", (target_id,)
            )
            await db.commit()
            return f"✅ Пользователь {target_id} разбанен."
        else:
            # Бан
            await db.execute(
                "INSERT INTO banned_users (user_id, banned_by) VALUES (?, ?)",
                (target_id, banned_by),
            )
            await db.commit()
            return f"🚫 Пользователь {target_id} забанен."
    finally:
        await db.close()
