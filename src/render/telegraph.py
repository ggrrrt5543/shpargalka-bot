"""
Публикация решений на Telegraph (адаптивная веб-страница).

Аналог `electron-auth.ts`: помощник, использующий внешний сервис как
fallback для главной фичи (Mini App). Когда Mini App backend недоступен,
ответ публикуется на telegra.ph и пользователю отдаётся ссылка.
"""
import json
import os
import re
import urllib.parse
import urllib.request

from ..config import logger

# Telegraph токен (создаётся один раз при запуске).
TELEGRAPH_TOKEN: str | None = None


def init_telegraph() -> None:
    global TELEGRAPH_TOKEN
    try:
        url = "https://api.telegra.ph/createAccount"
        data = urllib.parse.urlencode({
            "short_name":  "Шпаргалка",
            "author_name": "Шпаргалка-бот",
        }).encode()
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("ok"):
            TELEGRAPH_TOKEN = result["result"]["access_token"]
            logger.info(f"Telegraph токен получен: {TELEGRAPH_TOKEN[:12]}...")
        else:
            logger.error(f"Telegraph ошибка: {result}")
    except Exception as e:
        logger.error(f"Не удалось создать Telegraph аккаунт: {e}")


def upload_image_to_telegraph(
    image_bytes: bytes, title: str = "Формула"
) -> str | None:
    """Загружает PNG в Telegraph и возвращает абсолютный URL."""
    try:
        boundary = "----TGPHFormBoundary" + os.urandom(8).hex()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="formula.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            "https://telegra.ph/upload",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        resp = urllib.request.urlopen(req, timeout=20)
        result = json.loads(resp.read())
        if (
            isinstance(result, list)
            and result
            and isinstance(result[0], dict)
            and "src" in result[0]
        ):
            src = result[0]["src"]
            if src.startswith("http"):
                return src
            return "https://telegra.ph" + src
        logger.error(f"Telegraph upload unexpected response: {result}")
        return None
    except Exception as e:
        logger.error(f"Telegraph upload error: {e}")
        return None


def _parse_inline(text: str) -> list:
    """Разбирает **жирный**, *курсив*, `код` внутри строки."""
    parts = []
    pattern = r"(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)"
    last = 0
    for m in re.finditer(pattern, text):
        if m.start() > last:
            parts.append(text[last:m.start()])
        full = m.group(0)
        if full.startswith("**"):
            parts.append({"tag": "b", "children": [m.group(2)]})
        elif full.startswith("*"):
            parts.append({"tag": "i", "children": [m.group(3)]})
        elif full.startswith("`"):
            parts.append({"tag": "code", "children": [m.group(4)]})
        last = m.end()
    if last < len(text):
        parts.append(text[last:])
    return parts if parts else [text]


def text_to_telegraph_nodes(text: str) -> list:
    """Конвертирует ответ бота в Telegraph nodes."""
    nodes = []
    lines = text.strip().split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            nodes.append({"tag": "br"})
            continue

        if line.startswith("```formula") or line.startswith("```math"):
            formula_lines = []
            marker_len = 10 if line.startswith("```formula") else 7
            first = line[marker_len:].strip()
            if first:
                formula_lines.append(first)
            while i < len(lines) and not lines[i].strip().startswith("```"):
                formula_lines.append(lines[i])
                i += 1
            i += 1
            formula_text = " ".join(
                ln.strip() for ln in formula_lines if ln.strip()
            ).strip()
            if formula_text:
                nodes.append({
                    "tag": "aside",
                    "children": [
                        {"tag": "pre", "children": [formula_text]},
                    ],
                })
            continue

        if line.startswith(("📚", "🔍", "✅", "📖", "⚡", "💡", "📋", "🔣")):
            nodes.append({
                "tag": "h3",
                "children": _parse_inline(line),
            })
            continue

        if line.startswith(("- ", "• ", "* ")):
            list_items = [line[2:]]
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt.startswith(("- ", "• ", "* ")):
                    list_items.append(nxt[2:])
                    i += 1
                else:
                    break
            nodes.append({
                "tag": "ul",
                "children": [
                    {"tag": "li", "children": _parse_inline(it)}
                    for it in list_items
                ],
            })
            continue

        if re.match(r"^\d+[\.\)]\s", line):
            nodes.append({"tag": "p", "children": _parse_inline(line)})
            continue

        if line.startswith("```"):
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            nodes.append({
                "tag": "pre",
                "children": ["\n".join(code_lines)],
            })
            continue

        if line in ("---", "===", "***"):
            nodes.append({"tag": "hr"})
            continue

        nodes.append({"tag": "p", "children": _parse_inline(line)})

    return nodes


def publish_to_telegraph(title: str, answer: str) -> str | None:
    """Публикует ответ в Telegraph и возвращает URL."""
    if not TELEGRAPH_TOKEN:
        return None
    try:
        nodes = text_to_telegraph_nodes(answer)

        content = [
            {
                "tag": "p",
                "children": [
                    {"tag": "i", "children": ["Решение от Шпаргалка-бота 🤖"]},
                ],
            },
            {"tag": "hr"},
        ] + nodes + [
            {"tag": "hr"},
            {
                "tag": "p",
                "children": [
                    {"tag": "i", "children": ["✏️ Проверяй ответы самостоятельно!"]},
                ],
            },
        ]

        url = "https://api.telegra.ph/createPage"
        data = urllib.parse.urlencode({
            "access_token":  TELEGRAPH_TOKEN,
            "title":         title[:256],
            "content":       json.dumps(content, ensure_ascii=False),
            "return_content": "false",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())

        if result.get("ok"):
            return result["result"]["url"]
        logger.error(f"Telegraph publish error: {result}")
        return None
    except Exception as e:
        logger.error(f"Telegraph exception: {e}")
        return None
