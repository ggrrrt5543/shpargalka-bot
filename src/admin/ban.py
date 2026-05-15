"""
Бан/разбан пользователей.
"""
from src.db.database import db_read, db_write


async def is_banned(user_id: int) -> bool:
    row = await db_read("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
    return row is not None


async def get_ban_status(user_id: int) -> bool:
    return await is_banned(user_id)


async def toggle_ban(target_id: int, banned_by: int) -> str:
    row = await db_read("SELECT user_id FROM banned_users WHERE user_id = ?", (target_id,))
    if row:
        await db_write("DELETE FROM banned_users WHERE user_id = ?", (target_id,))
        return f"✅ Пользователь {target_id} разбанен."
    else:
        await db_write(
            "INSERT INTO banned_users (user_id, banned_by) VALUES (?, ?)",
            (target_id, banned_by),
        )
        return f"🚫 Пользователь {target_id} забанен."
