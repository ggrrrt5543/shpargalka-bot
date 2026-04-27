"""
Публикация решения в Mini App (FastAPI бэкенд на Fly.io).

Аналог `proxy/api-proxy.ts` (третья ветка): пробрасывает решение во
внешний сервис и возвращает публичный URL вида
`https://shpargalka-app-….fly.dev/s/<slug>`.
"""
import json
import re
import urllib.request

from ..config import (
    MINI_APP_API_KEY,
    MINI_APP_BASE_URL,
    logger,
)


def make_solution_title(answer: str) -> str:
    """Строит человеко-читаемый заголовок Mini App из ответа модели.

    Берёт первую содержательную строку, очищая ведущие эмодзи и метки
    «Тип:», «Решение:» и т.п.
    """
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
    """Публикует решение в FastAPI-бэкенд Mini App и возвращает URL."""
    if not MINI_APP_BASE_URL or not MINI_APP_API_KEY:
        return None
    payload = json.dumps({
        "title":   title,
        "content": content,
        "user_id": user_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{MINI_APP_BASE_URL}/api/solutions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key":    MINI_APP_API_KEY,
            "User-Agent":   "shpargalka-bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            url = data.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
            logger.error(f"Mini App publish: unexpected response {data}")
            return None
    except Exception as e:
        logger.error(f"Mini App publish error: {e}")
        return None
