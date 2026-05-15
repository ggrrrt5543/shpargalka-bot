"""
Главная точка входа Telegram-бота.

Создаёт инстанс бота, регистрирует обработчики команд / сообщений /
коллбеков и запускает long polling.
"""
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .admin.handlers import handle_admin_callback
from .config import ADMIN_IDS, KNOWLEDGE_BASE_PATH, TELEGRAM_TOKEN, logger
from .db import init_db
from .handlers import (
    handle_clear,
    handle_document,
    handle_mystats,
    handle_photo,
    handle_subject_command,
    handle_text,
    set_format_callback,
    set_subject_callback,
    show_detailed_callback,
    show_short_callback,
    start,
)
from .render.telegraph import init_telegraph


async def _startup_tasks() -> None:
    """Задачи при старте: инициализация БД."""
    # Инициализация SQLite
    await init_db()
    logger.info("✅ База данных инициализирована")


def _index_knowledge_base() -> None:
    """Индексация RAG в фоне (синхронная, запускается в executor)."""
    try:
        from .rag.indexer import KnowledgeIndexer

        indexer = KnowledgeIndexer(KNOWLEDGE_BASE_PATH)
        collection = indexer._get_collection()

        # Если база уже проиндексирована — пропускаем
        if collection is not None:
            count = collection.count()
            if count > 0:
                logger.info(
                    f"✅ RAG: база уже проиндексирована ({count} чанков). "
                    f"Для переиндексации используй /reindex или админ-панель."
                )
                return

        stats = indexer.index_all()
        if stats["files"] > 0:
            logger.info(
                f"✅ RAG: проиндексировано {stats['files']} файлов, "
                f"{stats['chunks']} чанков"
            )
        else:
            logger.info("ℹ️ RAG: база знаний пуста (добавьте файлы в knowledge_base/)")
    except Exception as e:
        logger.warning(f"⚠️ RAG индексация пропущена: {e}")


def main() -> None:
    # Синхронная инициализация Telegraph
    init_telegraph()

    # Async startup (DB)
    asyncio.get_event_loop().run_until_complete(_startup_tasks())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("subject", handle_subject_command))
    app.add_handler(CommandHandler("mystats", handle_mystats))

    # Сообщения
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Callbacks — формат
    app.add_handler(
        CallbackQueryHandler(show_detailed_callback, pattern="^show_detailed$")
    )
    app.add_handler(
        CallbackQueryHandler(show_short_callback, pattern="^show_short$")
    )
    app.add_handler(
        CallbackQueryHandler(set_format_callback, pattern="^set_format_")
    )
    app.add_handler(
        CallbackQueryHandler(set_format_callback, pattern="^show_subjects$")
    )

    # Callbacks — предмет
    app.add_handler(
        CallbackQueryHandler(set_subject_callback, pattern="^set_subject_")
    )

    # Callbacks — админ
    app.add_handler(
        CallbackQueryHandler(handle_admin_callback, pattern="^admin_")
    )

    # RAG индексация отключена при старте (запускай через админ-панель → Реиндекс)
    # Это экономит ресурсы при запуске бота
    logger.info("ℹ️ RAG: для индексации используй админ-панель → 🔄 Реиндекс")

    logger.info("🤖 Бот запущен! Нажми Ctrl+C для остановки")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
