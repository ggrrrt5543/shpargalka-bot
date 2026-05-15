"""
Entry-point: запуск Telegram-бота.

Тонкая обёртка над `src.telegram_bot.main`, чтобы можно было запустить
проект простым `python bot.py`. Вся логика — в подмодулях `src/`.
"""
from dotenv import load_dotenv

load_dotenv()

from src.telegram_bot import main

if __name__ == "__main__":
    main()
