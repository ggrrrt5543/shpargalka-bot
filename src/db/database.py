"""
Инициализация SQLite базы данных — shared connection с WAL mode.
"""
import asyncio
import os

import aiosqlite

DB_PATH = os.path.join("data", "bot.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    format_choice TEXT DEFAULT NULL,
    subject TEXT DEFAULT 'auto',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cache (
    question_hash TEXT PRIMARY KEY,
    question_text TEXT NOT NULL,
    answer TEXT NOT NULL,
    subject TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question_type TEXT NOT NULL,
    subject TEXT,
    response_time_ms INTEGER,
    cache_hit INTEGER DEFAULT 0,
    rag_used INTEGER DEFAULT 0,
    rag_chunks_count INTEGER DEFAULT 0,
    verifier_corrected INTEGER DEFAULT 0,
    action_type TEXT DEFAULT 'query',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    banned_by INTEGER
);

CREATE TABLE IF NOT EXISTS pending (
    user_id INTEGER PRIMARY KEY,
    answer TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_created
    ON analytics(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_user
    ON analytics(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cache_created
    ON cache(created_at);
"""

# Shared connection + write lock
_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def init_db() -> None:
    """Создаёт папку data/ и таблицы. Включает WAL mode."""
    global _db
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    # WAL mode — позволяет параллельные чтения
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA_SQL)
    await _db.commit()
    # Автоочистка
    await _db.execute(
        "DELETE FROM conversations WHERE created_at < datetime('now', '-7 days')"
    )
    await _db.execute(
        "DELETE FROM pending WHERE created_at < datetime('now', '-1 hour')"
    )
    await _db.commit()


async def get_db() -> aiosqlite.Connection:
    """Возвращает shared connection. НЕ закрывать!"""
    global _db
    if _db is None:
        await init_db()
    return _db


async def db_write(sql: str, params: tuple = ()) -> None:
    """Выполняет запись с блокировкой."""
    async with _db_lock:
        db = await get_db()
        await db.execute(sql, params)
        await db.commit()


async def db_write_fetchone(sql: str, params: tuple = ()):
    """Выполняет запись и возвращает результат."""
    async with _db_lock:
        db = await get_db()
        cursor = await db.execute(sql, params)
        await db.commit()
        return await cursor.fetchone()


async def db_read(sql: str, params: tuple = ()):
    """Выполняет чтение (без блокировки — WAL позволяет)."""
    db = await get_db()
    cursor = await db.execute(sql, params)
    return await cursor.fetchone()


async def db_read_all(sql: str, params: tuple = ()) -> list:
    """Выполняет чтение нескольких строк."""
    db = await get_db()
    cursor = await db.execute(sql, params)
    return await cursor.fetchall()
