"""
Инициализация SQLite базы данных и подключение.
"""
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

CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_created
    ON analytics(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_user
    ON analytics(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cache_created
    ON cache(created_at);
"""


async def init_db() -> None:
    """Создаёт папку data/ и таблицы если не существуют."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()
        # Автоочистка старых conversations (>7 дней)
        await db.execute(
            "DELETE FROM conversations WHERE created_at < datetime('now', '-7 days')"
        )
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    """Возвращает новое подключение к БД. Вызывающий должен закрыть."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db
