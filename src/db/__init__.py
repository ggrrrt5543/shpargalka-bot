"""
Персистентное хранилище: SQLite база данных.

Модуль предоставляет async-доступ к таблицам users, conversations,
cache, analytics, banned_users.
"""
from .database import get_db, init_db

__all__ = ["init_db", "get_db"]
