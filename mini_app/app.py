"""
Mini App FastAPI сервер.

Endpoints:
- POST /api/solutions — создать решение (от бота)
- GET /s/{slug} — отобразить решение (для пользователя)
"""
import hashlib
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="Шпаргалка Mini App")

# Пути
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Шаблоны и статика
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# API ключ для защиты POST endpoint
API_KEY = os.environ.get("MINI_APP_API_KEY", "")

# Хранилище решений (in-memory, при деплое можно заменить на Redis/SQLite)
solutions: dict[str, dict] = {}


def _generate_slug(content: str) -> str:
    """Генерирует короткий уникальный slug."""
    h = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:8]
    return h


class SolutionCreate(BaseModel):
    title: str
    content: str
    user_id: int | None = None


@app.post("/api/solutions")
async def create_solution(body: SolutionCreate, request: Request):
    """Создаёт решение и возвращает URL."""
    # Проверка API ключа
    api_key = request.headers.get("X-API-Key", "")
    if API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    slug = _generate_slug(body.content)
    solutions[slug] = {
        "title": body.title,
        "content": body.content,
        "user_id": body.user_id,
        "created_at": time.time(),
    }

    # Определяем base URL
    base_url = os.environ.get("MINI_APP_BASE_URL", "").rstrip("/")
    if not base_url:
        # Пробуем определить из запроса
        base_url = f"{request.url.scheme}://{request.url.netloc}"

    url = f"{base_url}/s/{slug}"
    return {"url": url, "slug": slug}


@app.get("/s/{slug}", response_class=HTMLResponse)
async def view_solution(slug: str, request: Request):
    """Отображает решение."""
    solution = solutions.get(slug)
    if not solution:
        raise HTTPException(status_code=404, detail="Решение не найдено")

    return templates.TemplateResponse(
        request=request,
        name="solution.html",
        context={
            "title": solution["title"],
            "content": solution["content"],
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "solutions_count": len(solutions)}
