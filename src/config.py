"""
Centralized configuration: env vars, models, logger, Qwen client.

Аналог `server.ts` из qwen-channel-translator: один общий модуль, через
который остальные части приложения тянут токены и инициализированный
клиент.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from openai import OpenAI

# Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# Qwen / LLM
QWEN_API_URL = os.environ.get(
    "QWEN_API_URL",
    "https://qwen.aikit.club",
)

QWEN_TOKEN = os.environ.get("QWEN_TOKEN", "")

# Совместимость со старым именем переменной.
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", QWEN_TOKEN)

# Mini App backend (FastAPI на Fly.io).
MINI_APP_BASE_URL = os.environ.get("MINI_APP_BASE_URL", "").rstrip("/")
MINI_APP_API_KEY = os.environ.get("MINI_APP_API_KEY", "")

# Модели (можно переопределить через .env)
TEXT_MODEL = os.environ.get("TEXT_MODEL", "qwen3.6-plus")
VERIFIER_MODEL = os.environ.get("VERIFIER_MODEL", "qwen3.6-max-preview")
VISION_MODEL = os.environ.get("VISION_MODEL", "qwen3.6-plus")

# RAG
KNOWLEDGE_BASE_PATH = os.environ.get("KNOWLEDGE_BASE_PATH", "./knowledge_base")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

# Память диалога
MAX_HISTORY_MESSAGES = int(os.environ.get("MAX_HISTORY_MESSAGES", "10"))
HISTORY_TIMEOUT_MINUTES = int(os.environ.get("HISTORY_TIMEOUT_MINUTES", "30"))

# Кэш
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))

# Админ
ADMIN_IDS: set[int] = set()
_admin_ids_raw = os.environ.get("ADMIN_IDS", "")
if _admin_ids_raw:
    for _id in _admin_ids_raw.split(","):
        _id = _id.strip()
        if _id.isdigit():
            ADMIN_IDS.add(int(_id))

ADMIN_SECRET_PHRASE = os.environ.get("ADMIN_SECRET_PHRASE", "открой ворота")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Клиент Qwen (OpenAI-совместимый)
qwen_client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_API_URL)

# Логгер
os.makedirs("data/logs", exist_ok=True)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("shpargalka")

# Ротация логов в файл
_file_handler = RotatingFileHandler(
    "data/logs/bot.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
logger.addHandler(_file_handler)

# Глобальное состояние (legacy)
pending_choice_messages: dict[int, int] = {}  # message_id сообщения с выбором формата

# matplotlib (опционально)
try:
    import matplotlib  # noqa: F401
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: F401
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
