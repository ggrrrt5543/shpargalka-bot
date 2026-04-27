"""
Рендер картинок: формулы, краткий ответ, полное решение.

Аналог `proxy/api-proxy.ts` (вторая часть): конвертирует текст ответа
в PNG-изображения через matplotlib. Используется как fallback-вариант,
если Mini App / Telegraph недоступны.
"""
import io
import re
import textwrap

from ..config import MATPLOTLIB_AVAILABLE, logger
from ..latex.clean import clean_latex

if MATPLOTLIB_AVAILABLE:
    import matplotlib.pyplot as plt


def formula_to_image(
    text: str, dark_bg: bool = True, fontsize: int = 24
) -> bytes | None:
    """Генерирует изображение текста/формулы с помощью matplotlib."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        fig, ax = plt.subplots(figsize=(max(8, len(text) * 0.09), 2))
        ax.set_facecolor("#1a1a2e" if dark_bg else "#ffffff")
        fig.patch.set_facecolor("#1a1a2e" if dark_bg else "#ffffff")

        ax.text(
            0.5, 0.5, text, fontsize=fontsize, ha="center", va="center",
            color="white" if dark_bg else "black", fontfamily="monospace",
            transform=ax.transAxes,
        )
        ax.axis("off")
        plt.tight_layout(pad=1.0)

        buf = io.BytesIO()
        plt.savefig(
            buf, format="png", dpi=150, bbox_inches="tight",
            facecolor="#1a1a2e" if dark_bg else "#ffffff", edgecolor="none",
        )
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Ошибка генерации формулы: {e}")
        try:
            plt.close()
        except Exception:
            pass
        return None


def answer_to_image(answer_text: str, answer_only: bool = True) -> bytes | None:
    """Генерирует красивое изображение ответа для краткого режима."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        if "✅ Ответ:" in answer_text:
            parts = answer_text.split("✅ Ответ:")
            if len(parts) > 1:
                answer = parts[1].strip().split("\n")[0].strip()
            else:
                answer = answer_text.strip()
        else:
            answer = answer_text.strip().split("\n")[0]

        answer = clean_latex(answer)

        fig, ax = plt.subplots(figsize=(6, 3))
        ax.set_facecolor("#2d2d44")
        fig.patch.set_facecolor("#2d2d44")

        ax.text(
            0.5, 0.85, "✅ Ответ", fontsize=16, ha="center", va="center",
            color="#4fc3f7", fontweight="bold", fontfamily="sans-serif",
            transform=ax.transAxes,
        )
        ax.text(
            0.5, 0.35, answer, fontsize=32, ha="center", va="center",
            color="white", fontweight="bold", fontfamily="monospace",
            transform=ax.transAxes,
        )
        ax.axis("off")
        plt.tight_layout(pad=1.5)

        buf = io.BytesIO()
        plt.savefig(
            buf, format="png", dpi=150, bbox_inches="tight",
            facecolor="#2d2d44", edgecolor="none",
        )
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Ошибка генерации ответа: {e}")
        try:
            plt.close()
        except Exception:
            pass
        return None


def _strip_inline_md(text: str) -> str:
    """Убирает **жирный**, *курсив*, `код` для рендера в картинку."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


# Эмодзи → подпись/цвет для бейджа в подробной картинке.
_HEADER_BADGES: dict[str, tuple[str, str]] = {
    "📚": ("ТИП",       "#4fc3f7"),
    "📋": ("ВОПРОС",    "#4fc3f7"),
    "🔍": ("РЕШЕНИЕ",   "#ffd54f"),
    "📖": ("ПОДРОБНО",  "#ffd54f"),
    "⚡": ("КРАТКО",    "#ff8a65"),
    "💡": ("ПОЯСНЕНИЕ", "#ba68c8"),
    "✅": ("ОТВЕТ",     "#81c784"),
    "🔣": ("ФОРМУЛА",   "#ffd54f"),
}


def _split_header_badge(line: str) -> tuple[str | None, str, str]:
    """Разбирает строку-заголовок типа "📚 Тип: Математика".

    Возвращает (label, color, остаток_текста).
    """
    for emoji, (label, color) in _HEADER_BADGES.items():
        if line.startswith(emoji):
            rest = line[len(emoji):].lstrip(" :—-")
            rest = re.sub(
                r"^(?:Тип|Решение|Ответ|Вопрос|Объяснение|Пояснение|Подробно|Кратко|Формула)\s*[:—-]\s*",
                "",
                rest,
                flags=re.IGNORECASE,
            )
            return label, color, rest.strip()
    return None, "#4fc3f7", line


def solution_to_image(text: str) -> bytes | None:
    """Рендерит полное пошаговое решение в одну PNG-картинку."""
    if not MATPLOTLIB_AVAILABLE:
        return None

    try:
        clean = clean_latex(clean_latex(text or ""))

        items: list[tuple[str, str]] = []
        raw = clean.split("\n")
        i = 0
        while i < len(raw):
            stripped = raw[i].strip()

            if stripped.startswith("```formula") or stripped.startswith("```math"):
                buf = []
                first = (
                    stripped[10:].strip()
                    if stripped.startswith("```formula")
                    else stripped[7:].strip()
                )
                if first:
                    buf.append(first)
                i += 1
                while i < len(raw) and not raw[i].strip().startswith("```"):
                    if raw[i].strip():
                        buf.append(raw[i].strip())
                    i += 1
                i += 1
                f = " ".join(buf).strip()
                if f:
                    items.append(("formula", f))
                continue

            if stripped.startswith("```"):
                buf = []
                i += 1
                while i < len(raw) and not raw[i].strip().startswith("```"):
                    buf.append(raw[i])
                    i += 1
                i += 1
                items.append(("code", "\n".join(buf)))
                continue

            if not stripped:
                items.append(("blank", ""))
                i += 1
                continue

            if stripped.startswith(("📚", "🔍", "✅", "📖", "⚡", "💡", "📋", "🔣")):
                items.append(("header", _strip_inline_md(stripped)))
                i += 1
                continue

            if stripped.startswith(("- ", "• ", "* ")):
                items.append(("bullet", _strip_inline_md(stripped[2:])))
                i += 1
                continue

            if re.match(r"^\d+[\.\)]\s", stripped):
                items.append(("num", _strip_inline_md(stripped)))
                i += 1
                continue

            if stripped in ("---", "===", "***"):
                items.append(("hr", ""))
                i += 1
                continue

            items.append(("text", _strip_inline_md(stripped)))
            i += 1

        wrapped: list[tuple[str, str]] = []
        for kind, content in items:
            if kind in ("formula", "blank", "hr"):
                wrapped.append((kind, content))
            elif kind == "code":
                for ln in content.split("\n"):
                    wrapped.append(("code", ln))
            elif kind == "header":
                for j, w in enumerate(textwrap.wrap(content, width=55) or [""]):
                    wrapped.append(("header" if j == 0 else "header_cont", w))
            elif kind == "bullet":
                lines = textwrap.wrap(content, width=68) or [""]
                for j, w in enumerate(lines):
                    wrapped.append(("bullet" if j == 0 else "text_indent", w))
            elif kind == "num":
                lines = textwrap.wrap(content, width=68) or [""]
                for j, w in enumerate(lines):
                    wrapped.append(("num" if j == 0 else "text_indent", w))
            else:
                for w in textwrap.wrap(content, width=72) or [""]:
                    wrapped.append(("text", w))

        line_h = {
            "header": 0.65, "header_cont": 0.45,
            "formula": 0.95, "code": 0.32,
            "bullet": 0.42, "num": 0.42,
            "text": 0.42, "text_indent": 0.40,
            "blank": 0.22, "hr": 0.30,
        }
        total_h = sum(line_h.get(k, 0.4) for k, _ in wrapped) + 0.7
        total_h = max(total_h, 3.5)
        total_h = min(total_h, 30.0)

        fig_w = 10.0
        fig, ax = plt.subplots(figsize=(fig_w, total_h))
        ax.set_facecolor("#1a1a2e")
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, total_h)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)

        ax.text(
            0.5, total_h - 0.25, "Шпаргалка-бот · Решение",
            fontsize=15, color="#90caf9", fontweight="bold",
            fontfamily="DejaVu Sans", ha="center", va="top",
        )

        y = total_h - 0.7
        for kind, content in wrapped:
            h = line_h.get(kind, 0.4)
            if kind == "header":
                label, color, rest = _split_header_badge(content)
                x_cursor = 0.04
                if label:
                    ax.text(
                        x_cursor, y, f"  {label}  ",
                        fontsize=13, color="#1a1a2e",
                        fontweight="bold", fontfamily="DejaVu Sans", va="top",
                        bbox=dict(
                            facecolor=color, edgecolor="none",
                            boxstyle="round,pad=0.3",
                        ),
                    )
                    x_cursor = 0.04 + 0.012 * (len(label) + 4)
                if rest:
                    ax.text(
                        x_cursor, y, rest, fontsize=19, color=color,
                        fontweight="bold", fontfamily="DejaVu Sans", va="top",
                    )
            elif kind == "header_cont":
                ax.text(
                    0.04, y, content, fontsize=17, color="#4fc3f7",
                    fontweight="bold", fontfamily="DejaVu Sans", va="top",
                )
            elif kind == "formula":
                ax.text(
                    0.5, y - h * 0.5, content, fontsize=22, color="#ffd54f",
                    fontfamily="DejaVu Sans Mono", ha="center", va="center",
                    bbox=dict(
                        facecolor="#2d2d44", edgecolor="#4fc3f7",
                        boxstyle="round,pad=0.5", linewidth=2,
                    ),
                )
            elif kind == "code":
                ax.text(
                    0.06, y, content, fontsize=12, color="#a5d6a7",
                    fontfamily="DejaVu Sans Mono", va="top",
                )
            elif kind == "bullet":
                ax.text(
                    0.05, y, "▸ " + content, fontsize=14, color="#e0e0e0",
                    fontfamily="DejaVu Sans", va="top",
                )
            elif kind == "num":
                ax.text(
                    0.05, y, content, fontsize=14, color="#e0e0e0",
                    fontfamily="DejaVu Sans", va="top",
                )
            elif kind == "text_indent":
                ax.text(
                    0.07, y, content, fontsize=14, color="#cfd8dc",
                    fontfamily="DejaVu Sans", va="top",
                )
            elif kind == "hr":
                ax.plot(
                    [0.05, 0.95], [y - h * 0.5, y - h * 0.5],
                    color="#4fc3f7", linewidth=1, alpha=0.4,
                )
            elif kind == "blank":
                pass
            else:
                ax.text(
                    0.05, y, content, fontsize=14, color="#ffffff",
                    fontfamily="DejaVu Sans", va="top",
                )
            y -= h

        ax.text(
            0.5, 0.2, "✏️ Проверяй ответы самостоятельно",
            fontsize=10, color="#90a4ae", fontstyle="italic",
            fontfamily="DejaVu Sans", ha="center", va="bottom",
        )

        plt.tight_layout(pad=0.6)
        buf = io.BytesIO()
        plt.savefig(
            buf, format="png", dpi=140, bbox_inches="tight",
            facecolor="#1a1a2e", edgecolor="none",
        )
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Ошибка solution_to_image: {e}")
        try:
            plt.close()
        except Exception:
            pass
        return None
