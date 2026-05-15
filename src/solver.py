"""
LLM-решатель: основной solver + reasoning-верификатор.

  • `ask_qwen_text`  — обычная задача (текст) с поддержкой истории, RAG, предметов.
  • `ask_qwen_image` — задача с фото (vision-модель).
  • `_verify_answer` — reasoning-проверка чернового ответа.
"""
import base64
import re
import urllib.error
import urllib.request

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
    SUBJECT_VERIFIER_PROMPTS,
    SYSTEM_PROMPT,
    VERIFIER_PROMPT,
)


# ─── Очистка технического мусора провайдера ──────────────────────────────────
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
    text = _DETAILS_RE.sub("", text)
    text = _DETAILS_OPEN_RE.sub("", text)
    text = _DETAILS_TAG_RE.sub("", text)
    text = _REQUEST_ID_RE.sub("", text)
    text = _REQUEST_ID_INLINE_RE.sub("", text)
    text = _BACKTICK_LINE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


sanitize_model_output = _sanitize_model_output


# ─── Удаление чатов Qwen ────────────────────────────────────────────────────
def delete_qwen_chats() -> bool:
    """Удаляет историю чатов Qwen через endpoint прокси."""
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


# ─── Верификатор ─────────────────────────────────────────────────────────────
def _verify_answer(question: str, draft: str, verifier_prompt: str | None = None) -> str | None:
    """Проверяет черновое решение reasoning-моделью.

    Возвращает None если OK, либо строку с правильным ответом.
    """
    prompt = verifier_prompt or VERIFIER_PROMPT
    try:
        r = qwen_client.chat.completions.create(
            model=VERIFIER_MODEL,
            messages=[
                {"role": "system", "content": prompt},
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
        "литератур", "произведен", "автор", "писател", "поэт",
        "роман", "повест", "рассказ", "поэм", "стих", "басн",
        "герой", "персонаж", "сюжет", "жанр", "лирическ",
        "эпитет", "метафор", "олицетвор", "цитат", "тема",
        "идея произведения", "онегин", "печорин", "обломов",
        "чичиков", "раскольников", "дубровский", "гринев",
        "мцыри", "чатский", "фамусов", "базаров",
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


# ─── Основной решатель ───────────────────────────────────────────────────────
def ask_qwen_text(
    question: str,
    history: list[dict] | None = None,
    rag_chunks: list[dict] | None = None,
    subject_prompt: str = "",
    detected_subject: str = "auto",
) -> str:
    """Решает задачу с учётом истории, RAG-контекста и предметного промпта.

    Args:
        question: текст вопроса
        history: история диалога [{role, content}]
        rag_chunks: релевантные фрагменты из базы знаний [{text, source}]
        subject_prompt: дополнительный промпт для предмета
        detected_subject: определённый предмет (для выбора верификатора)
    """
    # Собираем системный промпт
    system = SYSTEM_PROMPT
    if subject_prompt:
        system += subject_prompt

    # Добавляем RAG-контекст
    if rag_chunks:
        context_parts = []
        for c in rag_chunks:
            source = c.get("source", "")
            text = c.get("text", "")
            if source:
                context_parts.append(f"[Источник: {source}]\n{text}")
            else:
                context_parts.append(text)
        context_text = "\n\n---\n\n".join(context_parts)
        system += (
            "\n\n═══ РЕЛЕВАНТНЫЙ МАТЕРИАЛ ИЗ БАЗЫ ЗНАНИЙ ═══\n"
            "(Используй эту информацию для точности ответа. "
            "Если материал не относится к вопросу — игнорируй.)\n\n"
            + context_text
        )

    # Собираем messages
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    r = qwen_client.chat.completions.create(
        model=TEXT_MODEL,
        messages=messages,
        max_tokens=3500,
        temperature=0.1,
    )
    draft = _sanitize_model_output(r.choices[0].message.content)
    if not draft:
        return "Не удалось получить ответ. Попробуй ещё раз."

    # Верификация — ОДИН верификатор на запрос
    verifier_corrected = False
    verifier_prompt = SUBJECT_VERIFIER_PROMPTS.get(detected_subject)

    # Если предмет не определён — пробуем автоопределить для верификации
    if not verifier_prompt and detected_subject == "auto":
        if _looks_like_literature(question, draft):
            verifier_prompt = SUBJECT_VERIFIER_PROMPTS.get("literature")
        else:
            # Для неопределённого предмета — общий math-верификатор (ловит арифметику)
            verifier_prompt = VERIFIER_PROMPT

    if verifier_prompt:
        correction = _verify_answer(question, draft, verifier_prompt)
        if correction:
            logger.info(f"Verifier [{detected_subject}] исправление: {correction}")
            draft = (
                draft.rstrip()
                + f"\n\n📌 **Уточнённый ответ (после проверки):** {correction}"
            )
            verifier_corrected = True

    # Источники RAG НЕ показываем пользователю

    return draft


def ask_qwen_image(
    image_bytes: bytes,
    caption: str = "",
    subject_prompt: str = "",
    rag_chunks: list[dict] | None = None,
) -> str:
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

    system = SYSTEM_PROMPT
    if subject_prompt:
        system += subject_prompt

    if rag_chunks:
        context_parts = []
        for c in rag_chunks:
            source = c.get("source", "")
            text = c.get("text", "")
            if source:
                context_parts.append(f"[Источник: {source}]\n{text}")
            else:
                context_parts.append(text)
        context_text = "\n\n---\n\n".join(context_parts)
        system += (
            "\n\n═══ РЕЛЕВАНТНЫЙ МАТЕРИАЛ ИЗ БАЗЫ ЗНАНИЙ ═══\n"
            + context_text
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
                    "text": system + "\n\n" + instruction,
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
