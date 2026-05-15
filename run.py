"""
Запуск бота и Mini App вместе.

Использование:
    python run.py          — запускает и бота и Mini App (порт 8000)
    python run.py bot      — только бот
    python run.py web      — только Mini App
"""
import os
import sys
import threading

from dotenv import load_dotenv

load_dotenv()


def run_bot():
    """Запускает Telegram бота."""
    from src.telegram_bot import main
    main()


def run_web():
    """Запускает Mini App (FastAPI)."""
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    uvicorn.run("mini_app.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "bot":
        run_bot()
    elif mode == "web":
        run_web()
    else:
        # Запускаем оба: Mini App в отдельном потоке, бот в основном
        print("🚀 Запуск Mini App на http://localhost:8000")
        print("🤖 Запуск Telegram бота")
        print("─" * 40)

        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()

        run_bot()
