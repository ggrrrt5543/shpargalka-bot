"""
CRUD операции для таблицы users.
"""
from .database import db_read, db_read_all, db_write


async def get_or_create_user(user_id: int) -> dict:
    """Возвращает пользователя, создаёт если не существует."""
    row = await db_read(
        "SELECT user_id, format_choice, subject, created_at, last_active_at "
        "FROM users WHERE user_id = ?",
        (user_id,),
    )
    if row:
        return {
            "user_id": row[0], "format_choice": row[1],
            "subject": row[2], "created_at": row[3], "last_active_at": row[4],
        }
    await db_write("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    return {"user_id": user_id, "format_choice": None, "subject": "auto"}


async def get_format_choice(user_id: int) -> str | None:
    row = await db_read("SELECT format_choice FROM users WHERE user_id = ?", (user_id,))
    return row[0] if row else None


async def set_format_choice(user_id: int, choice: str | None) -> None:
    await db_write(
        "INSERT INTO users (user_id, format_choice) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET format_choice = ?",
        (user_id, choice, choice),
    )


async def get_subject(user_id: int) -> str:
    row = await db_read("SELECT subject FROM users WHERE user_id = ?", (user_id,))
    return row[0] if row and row[0] else "auto"


async def set_subject(user_id: int, subject: str) -> None:
    await db_write(
        "INSERT INTO users (user_id, subject) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET subject = ?",
        (user_id, subject, subject),
    )


async def touch(user_id: int) -> None:
    await db_write(
        "INSERT INTO users (user_id) VALUES (?) "
        "ON CONFLICT(user_id) DO UPDATE SET last_active_at = CURRENT_TIMESTAMP",
        (user_id,),
    )


async def get_all_user_ids() -> list[int]:
    rows = await db_read_all("SELECT user_id FROM users")
    return [row[0] for row in rows]


async def get_recent_users(limit: int = 20) -> list[dict]:
    rows = await db_read_all(
        "SELECT user_id, format_choice, subject, last_active_at "
        "FROM users ORDER BY last_active_at DESC LIMIT ?",
        (limit,),
    )
    return [{"user_id": r[0], "format_choice": r[1], "subject": r[2], "last_active_at": r[3]} for r in rows]
