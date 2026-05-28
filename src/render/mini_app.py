"""
Публикация решения в Mini App.

Если Mini App работает в том же процессе — сохраняет напрямую в память.
Если на внешнем сервере — отправляет HTTP-запрос.
"""
import hashlib
import json
import re
import time
import urllib.request

from ..config import (
    MINI_APP_API_KEY,
    MINI_APP_BASE_URL,
    logger,
)


def _get_public_base_url() -> str:
    """Возвращает публичный HTTPS URL Mini App.

    Railway сам прокидывает RAILWAY_PUBLIC_DOMAIN после генерации домена.
    Это защищает от частой ошибки, когда в переменных остался
    MINI_APP_BASE_URL=http://localhost:8000 и Telegram не принимает WebApp.
    """
    railway_domain = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip().strip("/")
    if railway_domain:
        if railway_domain.startswith(("http://", "https://")):
            return railway_domain.replace("http://", "https://", 1).rstrip("/")
        return f"https://{railway_domain}"

    base_url = (MINI_APP_BASE_URL or "").strip().rstrip("/")
    if base_url.startswith("http://") and "localhost" not in base_url:
        return base_url.replace("http://", "https://", 1)
    return base_url


def make_solution_title(answer: str) -> str:
    """Строит человеко-читаемый заголовок из ответа модели."""
    for raw in (answer or "").split("\n"):
        s = raw.strip()
        if not s:
            continue
        s = re.sub(
            r"^(?:[📚📋🔍📖⚡💡✅🔣]+\s*)?(?:Тип|Вопрос|Решение|Ответ)\s*[:—-]\s*",
            "",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"\*(.+?)\*", r"\1", s)
        s = re.sub(r"`(.+?)`", r"\1", s)
        s = s.strip(" -—:#")
        if s:
            return s[:120]
    return "Решение"


def publish_to_mini_app(
    title: str, content: str, user_id: int | None = None
) -> str | None:
    """Публикует решение в Mini App и возвращает URL.

    Сначала пробует сохранить напрямую (если Mini App в том же процессе).
    Если не получается — отправляет HTTP-запрос.
    """
    base_url = _get_public_base_url()
    if not base_url:
        return None

    # Попытка 1: прямое сохранение (если Mini App в том же процессе)
    try:
        from mini_app.app import solutions
        slug = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:8]
        solutions[slug] = {
            "title": title,
            "content": content,
            "user_id": user_id,
            "created_at": time.time(),
        }
        url = f"{base_url}/s/{slug}"
        return url
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Mini App direct save failed: {e}")

    # Попытка 2: HTTP-запрос (если Mini App на другом сервере)
    if not MINI_APP_API_KEY:
        return None
    payload = json.dumps({
        "title":   title,
        "content": content,
        "user_id": user_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/solutions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key":    MINI_APP_API_KEY,
            "User-Agent":   "shpargalka-bot/2.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            url = data.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
            return None
    except Exception as e:
        logger.error(f"Mini App publish error: {e}")
        return None
