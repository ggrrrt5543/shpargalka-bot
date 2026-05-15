"""
CRUD операции для таблицы users.
"""
from .database import get_db


async def get_or_create_user(user_id: int) -> dict:
    """Возвращает пользователя, создаёт если не существует."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT user_id, format_choice, subject, created_at, last_active_at "
            "FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "user_id": row[0],
                "format_choice": row[1],
                "subject": row[2],
                "created_at": row[3],
                "last_active_at": row[4],
            }
        await db.execute(
            "INSERT INTO users (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()
        return {
            "user_id": user_id,
            "format_choice": None,
            "subject": "auto",
            "created_at": None,
            "last_active_at": None,
        }
    finally:
        await db.close()


async def get_format_choice(user_id: int) -> str | None:
    """Возвращает выбранный формат или None."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT format_choice FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
    finally:
        await db.close()


async def set_format_choice(user_id: int, choice: str | None) -> None:
    """Сохраняет выбор формата."""
    await get_or_create_user(user_id)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET format_choice = ? WHERE user_id = ?",
            (choice, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_subject(user_id: int) -> str:
    """Возвращает выбранный предмет (по умолчанию 'auto')."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT subject FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else "auto"
    finally:
        await db.close()


async def set_subject(user_id: int, subject: str) -> None:
    """Сохраняет выбранный предмет."""
    await get_or_create_user(user_id)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET subject = ? WHERE user_id = ?",
            (subject, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def touch(user_id: int) -> None:
    """Обновляет last_active_at."""
    await get_or_create_user(user_id)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_user_ids() -> list[int]:
    """Возвращает список всех user_id (для рассылки)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
    finally:
        await db.close()


async def get_recent_users(limit: int = 20) -> list[dict]:
    """Возвращает последних активных пользователей."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT user_id, format_choice, subject, last_active_at "
            "FROM users ORDER BY last_active_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": r[0],
                "format_choice": r[1],
                "subject": r[2],
                "last_active_at": r[3],
            }
            for r in rows
        ]
    finally:
        await db.close()
