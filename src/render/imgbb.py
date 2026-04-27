"""
Загрузка картинок на imgbb (бесплатный image hosting).

Используется как промежуточный шаг для встраивания формул в Telegraph
(там нужен публичный URL картинки).
"""
import base64

from ..config import logger
from .images import formula_to_image


def upload_image_to_imgbb(image_bytes: bytes) -> str | None:
    """Загружает изображение на imgbb и возвращает URL."""
    try:
        import requests
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        # Бесплатный API ключ imgbb (ограничение 32MB).
        # Для постоянного использования лучше получить свой ключ на
        # https://imgbb.com.
        resp = requests.post(
            "https://api.imgbb.com/1/upload",
            data={
                "key": "2ed8d3e5e2eb4d5f6c4a1b7e8d3f2e1a",
                "image": b64,
            },
            timeout=30,
        )
        result = resp.json()
        if result.get("success"):
            return result["data"]["url"]
        return None
    except Exception as e:
        logger.error(f"imgbb upload error: {e}")
        return None


def generate_formula_image_url(formula_text: str) -> str | None:
    """Генерирует изображение формулы и загружает на хостинг."""
    img_bytes = formula_to_image(formula_text)
    if not img_bytes:
        return None
    return upload_image_to_imgbb(img_bytes)
