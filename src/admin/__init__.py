"""
Секретная админ-панель бота.
"""
from .handlers import (
    handle_admin_callback,
    handle_admin_text_input,
    is_admin_awaiting_input,
    try_secret_phrase,
)

__all__ = [
    "try_secret_phrase",
    "is_admin_awaiting_input",
    "handle_admin_text_input",
    "handle_admin_callback",
]
