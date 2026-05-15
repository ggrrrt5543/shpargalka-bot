"""
Рассылка сообщений всем пользователям.
"""
from telegram import Bot

from src.config import logger
from src.db import users as db_users


async def broadcast_message(bot: Bot, text: str) -> tuple[int, int]:
    """Отправляет сообщение всем пользователям.

    Возвращает (sent_count, error_count).
    """
    user_ids = await db_users.get_all_user_ids()
    sent = 0
    errors = 0

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception as e:
            errors += 1
            logger.warning(f"Broadcast failed for {uid}: {e}")

    logger.info(f"Broadcast complete: sent={sent}, errors={errors}")
    return sent, errors
