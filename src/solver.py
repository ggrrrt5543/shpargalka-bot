"""
LLM-решатель: основной solver + reasoning-верификатор.

Аналог `channel-translator.ts`: модуль, отвечающий за «прикладную»
работу с моделью — отправляет запрос и возвращает текстовый результат.

  • `ask_qwen_text`  — обычная задача (текст).
  • `ask_qwen_image` — задача с фото (vision-модель).
  • `_verify_answer` — reasoning-проверка чернового ответа.
"""
import base64
import urllib.error
import urllib.request
import re

from .config import (
    QWEN_API_KEY,
    QWEN_API_URL,
    TEXT_MODEL,
    VERIFIER_MODEL,
    VISION_MODEL,
    logger,
    qwen_client,
)
from .latex.prompts import (
    LITERATURE_VERIFIER_PROMPT,
    SYSTEM_PROMPT,
    VERIFIER_PROMPT,
)


# Провайдер qwen.aikit.club добавляет в конец ответа технический блок
# <details><summary></summary>`Response ID: …`Request ID: …`</details>
# Чистим его, чтобы не лез в Mini App / краткий ответ / Telegraph.
_DETAILS_RE = re.compile(r"<details\b.*?</details>", re.IGNORECASE | re.DOTALL)
_DETAILS_OPEN_RE = re.compile(r"<details\b.*", re.IGNORECASE | re.DOTALL)
_DETAILS_TAG_RE = re.compile(
    r"</?(?:details|summary)\b[^>]*>", re.IGNORECASE
)
_REQUEST_ID_RE = re.compile(
    r"(?im)^[\s`]*(?:Response|Request)\s*ID\s*[:=].*$"
)
_REQUEST_ID_INLINE_RE = re.compile(
    r"(?i)(?:Response|Request)\s*ID\s*[:=]\s*[A-Za-z0-9_-]+"
)
_BACKTICK_LINE_RE = re.compile(r"(?m)^\s*`+\s*$")


def _sanitize_model_output(text: str | None) -> str:
    """Убирает технический мусор провайдера из текста модели."""
    if not text:
        return ""
    # 1) Полные блоки <details>...</details>.
    text = _DETAILS_RE.sub("", text)
    # 2) Если </details> отсутствует (оборванный ответ) — режем всё от <details>.
    text = _DETAILS_OPEN_RE.sub("", text)
    # 3) Голые теги <details>/<summary>, если остались.
    text = _DETAILS_TAG_RE.sub("", text)
    # 4) Строки Response/Request ID — целиком.
    text = _REQUEST_ID_RE.sub("", text)
    # 5) То же самое, но если они попали внутрь строки.
    text = _REQUEST_ID_INLINE_RE.sub("", text)
    # 6) Висячие одиночные backtick-строки.
    text = _BACKTICK_LINE_RE.sub("", text)
    # 7) Сжимаем 3+ переносов в 2.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Публичный алиас — чтобы handlers.py мог импортировать.
sanitize_model_output = _sanitize_model_output


def delete_qwen_chats() -> bool:
    """Удаляет историю чатов Qwen через endpoint прокси qwen.aikit.club."""
    if getattr(delete_qwen_chats, "_unsupported", False):
        return False

    base_url = (QWEN_API_URL or "").rstrip("/")
    if not base_url or not QWEN_API_KEY:
        return False

    if base_url.endswith("/v1"):
        url = f"{base_url}/chats/delete"
    else:
        url = f"{base_url}/v1/chats/delete"

    for method in ("DELETE", "POST"):
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {QWEN_API_KEY}",
                "User-Agent": "shpargalka-bot/1.0",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                ok = 200 <= resp.status < 300
                if ok:
                    logger.info("Qwen chats deleted")
                return ok
        except urllib.error.HTTPError as e:
            if method == "DELETE" and e.code in (404, 405):
                continue
            if e.code in (404, 405, 501):
                delete_qwen_chats._unsupported = True
            logger.warning(f"Qwen chats delete failed ({method}): {e}")
            return False
        except Exception as e:
            logger.warning(f"Qwen chats delete failed ({method}): {e}")
            return False

    return False


def _verify_answer(question: str, draft: str) -> str | None:
    """Проверяет черновое решение умной reasoning-моделью.

    Возвращает None если всё OK, либо строку с правильным ответом.
    """
    try:
        r = qwen_client.chat.completions.create(
            model=VERIFIER_MODEL,
            messages=[
                {"role": "system", "content": VERIFIER_PROMPT},
                {
                    "role": "user",
                    "content":
                        f"ЗАДАЧА:\n{question}\n\n"
                        f"ПРЕДЛОЖЕННОЕ РЕШЕНИЕ:\n{draft}",
                },
            ],
            max_tokens=512,
            temperature=0.0,
            extra_body={"reasoning_effort": "medium"},
        )
        verdict = _sanitize_model_output(r.choices[0].message.content)
        logger.info(f"Verifier: {verdict[:200]}")
        if not verdict or verdict.upper().startswith("VERDICT: OK"):
            return None
        for line in verdict.splitlines():
            line = line.strip()
            if line.upper().startswith("ANSWER:"):
                return line[len("ANSWER:"):].strip() or None
        return None
    except Exception as e:
        logger.warning(f"Verifier error ({VERIFIER_MODEL}): {e}")
        return None


def _looks_like_literature(question: str, draft: str = "") -> bool:
    text = f"{question}\n{draft}".lower()
    words = (
        "литератур",
        "произведен",
        "автор",
        "писател",
        "поэт",
        "роман",
        "повест",
        "рассказ",
        "поэм",
        "стих",
        "басн",
        "герой",
        "персонаж",
        "сюжет",
        "жанр",
        "лирическ",
        "эпитет",
        "метафор",
        "олицетвор",
        "цитат",
        "тема",
        "идея произведения",
        "онегин",
        "печорин",
        "обломов",
        "чичиков",
        "раскольников",
        "дубровский",
        "гринев",
        "мцыри",
        "чатский",
        "фамусов",
        "базаров",
    )
    return any(word in text for word in words)


def _verify_literature_answer(question: str, draft: str) -> str | None:
    try:
        r = qwen_client.chat.completions.create(
            model=VERIFIER_MODEL,
            messages=[
                {"role": "system", "content": LITERATURE_VERIFIER_PROMPT},
                {
                    "role": "user",
                    "content":
                        f"ЗАДАНИЕ ПО ЛИТЕРАТУРЕ:\n{question}\n\n"
                        f"ПРЕДЛОЖЕННЫЙ ОТВЕТ:\n{draft}",
                },
            ],
            max_tokens=700,
            temperature=0.0,
            extra_body={"reasoning_effort": "medium"},
        )
        verdict = _sanitize_model_output(r.choices[0].message.content)
        logger.info(f"Literature verifier: {verdict[:200]}")
        if not verdict or verdict.upper().startswith("VERDICT: OK"):
            return None
        for line in verdict.splitlines():
            line = line.strip()
            if line.upper().startswith("ANSWER:"):
                return line[len("ANSWER:"):].strip() or None
        return None
    except Exception as e:
        logger.warning(f"Literature verifier error ({VERIFIER_MODEL}): {e}")
        return None


def ask_qwen_text(question: str) -> str:
    """Решает задачу основной моделью и проверяет ответ у reasoning-модели.

    Если верификатор нашёл ошибку, к решению дописывается
    «📌 Уточнённый ответ: …».
    """
    r = qwen_client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": question},
        ],
        max_tokens=3500,
        temperature=0.1,
    )
    draft = _sanitize_model_output(r.choices[0].message.content)
    if not draft:
        return "Не удалось получить ответ. Попробуй ещё раз."

    correction = _verify_answer(question, draft)
    if correction:
        logger.info(f"Verifier предложил исправление: {correction}")
        draft = (
            draft.rstrip()
            + f"\n\n📌 **Уточнённый ответ (после проверки):** {correction}"
        )
    if _looks_like_literature(question, draft):
        literature_correction = _verify_literature_answer(question, draft)
        if literature_correction:
            logger.info(
                f"Literature verifier предложил исправление: {literature_correction}"
            )
            draft = (
                draft.rstrip()
                + "\n\n📚 **Повторная проверка по литературе:** "
                + literature_correction
            )
    return draft


def ask_qwen_image(image_bytes: bytes, caption: str = "") -> str:
    """Решает задание с фото."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    instruction = (
        "Распознай задание на фото и реши его. Если на фото несколько "
        "пронумерованных задач — реши КАЖДУЮ и в конце дай блок "
        "«ИТОГОВЫЕ ОТВЕТЫ:» с номерами как в условии."
    )
    caption = (caption or "").strip()
    if caption:
        instruction += (
            "\n\nДОПОЛНИТЕЛЬНОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ (учитывай его при "
            "решении — это уточнения к фото или указание, что именно "
            "нужно сделать):\n"
            f"«{caption}»"
        )
    r = qwen_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                    },
                },
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT + "\n\n" + instruction,
                },
            ],
        }],
        max_tokens=6144,
    )
    content = _sanitize_model_output(r.choices[0].message.content)
    if not content:
        return "Не удалось распознать задание. Попробуй ещё раз."
    if _looks_like_literature(caption, content):
        literature_correction = _verify_literature_answer(caption, content)
        if literature_correction:
            logger.info(
                f"Literature verifier предложил исправление: {literature_correction}"
            )
            content = (
                content.rstrip()
                + "\n\n📚 **Повторная проверка по литературе:** "
                + literature_correction
            )
    return content
