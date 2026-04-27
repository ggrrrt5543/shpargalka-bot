"""
Centralized configuration: env vars, models, logger, Qwen client.

Аналог `server.ts` из qwen-channel-translator: один общий модуль, через
который остальные части приложения тянут токены и инициализированный
клиент.
"""
import logging
import os

from openai import OpenAI

# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# ─── Qwen / LLM ──────────────────────────────────────────────────────────────
QWEN_API_URL = os.environ.get(
    "QWEN_API_URL",
    "https://qwen.aikit.club",
)

QWEN_TOKEN = os.environ.get("QWEN_TOKEN", "")

# Совместимость со старым именем переменной.
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", QWEN_TOKEN)

# Mini App backend (FastAPI на Fly.io). По кнопке «Подробно» бот публикует
# решение через POST /api/solutions и открывает уникальную ссылку как
# Telegram Mini App — это полноэкранная мобильная страница внутри Telegram.
MINI_APP_BASE_URL = os.environ.get("MINI_APP_BASE_URL", "").rstrip("/")
MINI_APP_API_KEY = os.environ.get("MINI_APP_API_KEY", "")

# ─── Модели (можно переопределить через .env) ────────────────────────────────
# Список доступных моделей: GET https://qwen.aikit.club/models с твоим JWT.
# qwen3.6-plus — флагман (text + vision, 1M context).
TEXT_MODEL = os.environ.get("TEXT_MODEL", "qwen3.6-plus")
VERIFIER_MODEL = os.environ.get("VERIFIER_MODEL", "qwen3.6-max-preview")
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen3.6-plus")

# ─── Клиент Qwen (OpenAI-совместимый) ────────────────────────────────────────
qwen_client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_API_URL)

# ─── Логгер ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("shpargalka")

# ─── Глобальное состояние пользователей ──────────────────────────────────────
# Хранит готовый ответ и выбор формата до тех пор, пока пользователь
# не нажмёт «Подробный»/«Краткий».
pending_answers: dict[int, str] = {}
user_format_choice: dict[int, str] = {}        # 'short' или 'detailed'
pending_tasks: dict[int, dict] = {}            # хранит задание до выбора формата
pending_choice_messages: dict[int, int] = {}   # message_id сообщения с выбором

# ─── matplotlib (опционально) ────────────────────────────────────────────────
try:
    import matplotlib  # noqa: F401
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: F401
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
