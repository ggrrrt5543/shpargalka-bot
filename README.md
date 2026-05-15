# 🤖 Шпаргалка-бот

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://python.org)
[![Telegram Bot](https://img.shields.io/badge/Telegram%20Bot-API-20B2AA)](https://core.telegram.org/bots/api)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Telegram-бот, который решает школьные/вузовские задачи (математика,
физика, тесты и т.д.) через Qwen + reasoning-верификатор и красиво
отображает решение в Telegram Mini App.

## 📸 Скриншоты

*Добавьте скриншоты работы бота здесь*

## ✨ Возможности

- 📸 **Фото-задания** — vision-модель распознаёт условие с картинки
- 📝 **Текстовые задачи** — основной solver + reasoning-проверка ответа
- 📈 **Графики функций** — серверный плоттер (matplotlib) рисует SVG/PNG
- 🌐 **Mini App** — подробное решение открывается прямо в Telegram
- 📄 **Telegraph fallback** — если Mini App недоступен
- 🖼️ **PNG fallback** — рендер всего решения в одну картинку
- ⚡ **Краткий режим** — только финальные ответы

## 📋 Требования

- Python 3.8+
- Telegram Bot Token
- Qwen API Token

## 🚀 Быстрый старт

### 1. Клонирование и установка

```bash
git clone https://github.com/ВАШ_НИК/shpargalka-bot.git
cd shpargalka-bot

# Создание виртуального окружения
python -m venv .venv

# Активация (Windows)
.venv\Scripts\activate
# Активация (Linux/Mac)
source .venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Копирование файла конфигурации
cp .env.example .env
```

### 2. Настройка переменных окружения

Отредактируйте файл `.env`:
```env
TELEGRAM_TOKEN=ваш_токен_от_BotFather
QWEN_TOKEN=ваш_jwt_токен
```

### 2. Получите токены

#### Telegram Bot Token
1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям, получите токен
4. Вставьте в `.env`: `TELEGRAM_TOKEN=ваш_токен`

#### Qwen Token
1. Откройте https://chat.qwen.ai
2. Войдите через Google
3. Нажмите **F12** → **Application** → **Local Storage** → `https://chat.qwen.ai`
4. Найдите ключ `token`, скопируйте значение `accessToken`
5. Вставьте в `.env`: `QWEN_TOKEN=eyJhbGci...`

### 3. Запуск

```bash
python bot.py
```

## 📂 Структура

```
shpargalka-bot/
├── bot.py                      # entry-point (тонкая обёртка над main)
├── requirements.txt
├── .env.example
├── .gitignore
└── src/
    ├── telegram_bot.py         # инициализация Application + handlers
    ├── handlers.py             # /start, текст, фото, документ, callbacks
    ├── solver.py               # ask_qwen_text / ask_qwen_image / verifier
    ├── config.py               # env-переменные, модели, qwen_client, logger
    ├── latex/                  # подсистема LaTeX (аналог oauth/)
    │   ├── prompts.py          # SYSTEM_PROMPT, VERIFIER_PROMPT, LLM_SHORT_PROMPT
    │   ├── clean.py            # чистка LaTeX (наружу и внутри блоков)
    │   ├── fix.py              # math_fix: чинит кривой LaTeX от модели
    │   └── short_answer.py     # извлечение коротких ответов + LLM-fallback
    └── render/                 # подсистема рендера (аналог proxy/)
        ├── images.py           # formula/answer/solution → PNG
        ├── plot.py             # графики y=f(x) → SVG / PNG
        ├── telegraph.py        # публикация на telegra.ph
        ├── imgbb.py            # загрузка картинок на imgbb
        └── mini_app.py         # POST в FastAPI Mini App backend
```

Эта раскладка повторяет структуру TypeScript-проекта
`qwen-channel-translator`:

| qwen-channel-translator (TS) | shpargalka-bot (Python)        |
| ---------------------------- | ------------------------------ |
| `src/telegram-bot.ts`        | `src/telegram_bot.py`          |
| `src/channel-translator.ts`  | `src/solver.py`                |
| `src/server.ts`              | `src/config.py`                |
| `src/electron-auth.ts`       | `src/render/telegraph.py`      |
| `src/oauth/`                 | `src/latex/`                   |
| `src/proxy/`                 | `src/render/`                  |

## ⚙ Конфигурация

Файл `.env`:
```env
TELEGRAM_TOKEN=<токен_от_BotFather>
QWEN_API_URL=https://qwen.aikit.club
QWEN_TOKEN=<ваш_jwt_токен>
QWEN_API_KEY=<алиас_QWEN_TOKEN>
MINI_APP_BASE_URL=https://shpargalka-app-mjhceaka.fly.dev
MINI_APP_API_KEY=<ваш_api_ключ>
```

## 🐛 FAQ

**Q: matplotlib не установлен**
A: PNG-fallback и графики не работают, но Mini App / Telegraph остаются.

**Q: Mini App backend недоступен**
A: Бот автоматически опубликует решение на Telegraph, либо отрендерит PNG.

**Q: Verifier ругается слишком часто**
A: Включите debug-логи (`logging.DEBUG` в `src/config.py`) и посмотрите
выдачу reasoning-модели — может стоит подкрутить `temperature` или
`reasoning_effort`.

## 🤝 Вклад в проект

1. Fork проекта
2. Создайте ветку (`git checkout -b feature/AmazingFeature`)
3. Сделайте коммит (`git commit -m 'Add some AmazingFeature'`)
4. Отправьте в репозиторий (`git push origin feature/AmazingFeature`)
5. Откройте Pull Request

## 📝 TODO

- [ ] Добавить поддержку 更多 языков
- [ ] Улучшить обработку математических формул
- [ ] Добавить базу знаний по предметам
- [ ] Создать веб-интерфейс

## 📞 Контакты

Ваш Telegram: [@ваш_ник]

## 📜 Лицензия

Этот проект распространяется под лицензией MIT. Подробности в файле [LICENSE](LICENSE).

## ⭐ Спасибо за использование!

Если проект вам понравился, поставьте ⭐ на GitHub!
