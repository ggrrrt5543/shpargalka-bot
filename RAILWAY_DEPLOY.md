# Деплой на Railway

## 1. Загрузить проект на GitHub

Если ещё не сделано — создай репозиторий на GitHub и запушь код:

```bash
git add .
git commit -m "Add Railway deploy config"
git push
```

## 2. Создать проект на Railway

1. Зайди на [railway.app](https://railway.app) и войди через GitHub
2. Нажми **New Project → Deploy from GitHub repo**
3. Выбери репозиторий `shpargalka-bot`
4. Railway автоматически обнаружит `railway.toml` и `requirements.txt`

## 3. Добавить переменные окружения

В Railway откройте вкладку **Variables** своего сервиса и добавь:

| Переменная | Значение |
|---|---|
| `TELEGRAM_TOKEN` | токен от BotFather |
| `QWEN_TOKEN` | твой JWT токен qwen.aikit.club |
| `QWEN_API_KEY` | то же что QWEN_TOKEN (если нужно) |
| `QWEN_API_URL` | `https://qwen.aikit.club` |
| `MINI_APP_BASE_URL` | `https://shpargalka-app-mjhceaka.fly.dev` (или пусто) |
| `MINI_APP_API_KEY` | ключ Mini App (или пусто) |
| `TEXT_MODEL` | `qwen3.6-plus` |
| `VERIFIER_MODEL` | `qwen3.6-max-preview` |
| `VISION_MODEL` | `qwen3.6-plus` |

## 4. Деплой

После добавления переменных Railway автоматически задеплоит проект.
Статус можно смотреть во вкладке **Deployments**.

Бот запускается как `worker` (без HTTP-порта) — это нормально для Telegram-ботов на polling.

## Важно

- Бот работает через **long polling** — не нужен никакой открытый порт
- Railway перезапустит бот автоматически при падении (`restartPolicyType = "always"`)
- Не добавляй `.env` файл в git — он в `.gitignore`
