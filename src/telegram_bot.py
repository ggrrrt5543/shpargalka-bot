"""
Главная точка входа Telegram-бота.

Аналог `telegram-bot.ts` из qwen-channel-translator: создаёт инстанс
бота, регистрирует обработчики команд / сообщений / коллбеков и
запускает long polling.
"""
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import TELEGRAM_TOKEN, logger
from .handlers import (
    handle_document,
    handle_photo,
    handle_text,
    set_format_callback,
    show_detailed_callback,
    show_short_callback,
    start,
)
from .render.telegraph import init_telegraph


def main() -> None:
    init_telegraph()  # создаём Telegraph аккаунт один раз при запуске

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(
        CallbackQueryHandler(show_detailed_callback, pattern="^show_detailed$")
    )
    app.add_handler(
        CallbackQueryHandler(show_short_callback, pattern="^show_short$")
    )
    app.add_handler(
        CallbackQueryHandler(set_format_callback, pattern="^set_format_")
    )

    logger.info("🤖 Бот запущен! Нажми Ctrl+C для остановки")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
