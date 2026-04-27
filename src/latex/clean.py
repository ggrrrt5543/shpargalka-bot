"""
Чистка LaTeX — снаружи и внутри математических блоков.

Аналог `oauth/auto-token.ts`: высокоуровневые операции, использующие
низкоуровневые регулярки/функции из `fix.py`.
"""
import re

from .fix import _ZERO_WIDTH, math_fix


def clean_latex(text: str) -> str:
    """Очищает остатки LaTeX и конвертирует в понятные символы."""
    if not text:
        return text
    text = re.sub(r'\$\$(.+?)\$\$', lambda m: m.group(1), text, flags=re.DOTALL)
    text = re.sub(r'\$(.+?)\$', r'\1', text)
    replacements = {
        r'\\dfrac\{(.+?)\}\{(.+?)\}': r'(\1)/(\2)',
        r'\\frac\{(.+?)\}\{(.+?)\}': r'(\1)/(\2)',
        r'\\displaystyle': '',
        r'\\Rightarrow': '⇒', r'\\rightarrow': '→', r'\\Leftarrow': '⇐',
        r'\\leftarrow': '←', r'\\leq': '≤', r'\\geq': '≥', r'\\neq': '≠',
        r'\\pm': '±', r'\\times': '×', r'\\div': '÷', r'\\cdot': '·',
        r'\\sqrt\{(.+?)\}': r'√(\1)', r'\\sqrt': '√',
        r'\\alpha': 'α', r'\\beta': 'β', r'\\gamma': 'γ', r'\\delta': 'δ',
        r'\\pi': 'π', r'\\infty': '∞', r'\\sum': '∑', r'\\int': '∫',
        r'\^2': '²', r'\^3': '³', r'\^\{2\}': '²', r'\^\{3\}': '³',
        r'\^(-?\d+)': r'^\1',
        r'\^\{-(\d+)\}': r'⁻\1',
        r'\^\{(\d+)\}': r'^\1',
        r'\^\{([+-]?\d+[+-]\d+)\}': r'^(\1)',
        r'10\^(-?\d+)': r'10^\1',
        r'\\left': '', r'\\right': '', r'\\quad': ' ', r'\\qquad': '  ',
        r'\\_\{(.+?)\}': r'_\1', r'\{': '', r'\}': '',
        r'\\text\{(.+?)\}': r'\1', r'\\mathbf\{(.+?)\}': r'\1',
        r'\\cdot': '·', r'\\ldots': '...', r'\\to': '→',
    }
    for pattern, repl in replacements.items():
        try:
            text = re.sub(pattern, repl, text)
        except Exception:
            pass
    return text


# ─── Очистка многострочных $$...$$ блоков и character-stacking ───────────────
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_DISPLAY_BRACKET_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)


def _flatten_display_math(s: str) -> str:
    def _flatten(m: re.Match) -> str:
        body = m.group(1)
        body = _ZERO_WIDTH.sub("", body)
        body = re.sub(r"\s*\n\s*", " ", body)
        body = re.sub(r"\s{2,}", " ", body).strip()
        return f"${body}$" if body else ""
    return _DISPLAY_MATH_RE.sub(_flatten, s)


def _flatten_bracket_math(s: str) -> str:
    def _flatten(m: re.Match) -> str:
        body = _ZERO_WIDTH.sub("", m.group(1))
        body = re.sub(r"\s*\n\s*", " ", body)
        body = re.sub(r"\s{2,}", " ", body).strip()
        return f"\\[{body}\\]" if body else ""
    return _DISPLAY_BRACKET_RE.sub(_flatten, s)


# Признаки того что строка математическая, а не проза.
_MATH_HINTS = (
    re.compile(r"\\[A-Za-z]+"),
    re.compile(r"\^|_"),
    re.compile(r"=|≈|⇒|→"),
    re.compile(r"\d\s*[\+\-\*/]\s*\d"),
    re.compile(r"√"),
    re.compile(r"\|[^|]*\|"),
    re.compile(r"[α-ωΑ-Ω]"),
)


def _looks_like_math(s: str) -> bool:
    if len(s.strip()) < 2:
        return False
    return sum(1 for r in _MATH_HINTS if r.search(s)) >= 2


def _wrap_loose_math_lines(text: str) -> str:
    """Если строка целиком математическая и не обёрнута — оборачиваем в $...$."""
    out_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if "$" in stripped or "\\(" in stripped or "\\[" in stripped:
            out_lines.append(line)
            continue
        if stripped.startswith(("#", "*", "-", ">", "•")):
            out_lines.append(line)
            continue
        cyrillic_words = re.findall(r"[А-Яа-я]{3,}", stripped)
        if len(cyrillic_words) > 2:
            m = re.match(
                r"^([A-Za-zА-Яа-я_\\][^\s=]*\s*=\s*[^,\.\n]+)$", stripped
            )
            if m and _looks_like_math(m.group(1)):
                indent = line[: len(line) - len(line.lstrip())]
                out_lines.append(f"{indent}${math_fix(m.group(1))}$")
                continue
            out_lines.append(line)
            continue
        if _looks_like_math(stripped):
            indent = line[: len(line) - len(line.lstrip())]
            out_lines.append(f"{indent}${math_fix(stripped)}$")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


_MINI_APP_PRESERVE_RE = re.compile(
    r"```(?:formula|math)(?::[^\n]*)?\n.*?```"
    r"|```(?:figure|svg|diagram)(?::[^\n]*)?\n.*?```"
    r"|\$\$[^\n]+?\$\$"
    r"|\\\[[^\n]+?\\\]"
    r"|\\\([^\n]+?\\\)"
    r"|\$(?!\$)[^$\n]+?\$",
    re.DOTALL,
)


def clean_latex_outside_formulas(text: str) -> str:
    """
    Применяет `clean_latex` ко всему тексту, КРОМЕ математических блоков.

    • Содержимое блоков ```formula …``` / ```math …``` остаётся как есть.
    • Inline-математика `$…$`, `\\(…\\)`, `\\[…\\]`, `$$…$$` сохраняется.
    • Кривой LaTeX внутри math-блоков чинится через `math_fix`.
    • «Голые» формулы автоматически оборачиваются в `$...$`.
    """
    if not text:
        return text

    text = _flatten_display_math(text)
    text = _flatten_bracket_math(text)
    # Голые `\boxed42` → `$\boxed{42}$`.
    text = re.sub(
        r"(?m)^(\s*)\\boxed\s*(-?\d+(?:[.,]\d+)?|[A-Za-zА-Яа-я])\s*$",
        lambda m: f"{m.group(1)}$\\boxed{{{m.group(2)}}}$",
        text,
    )
    text = _MINI_APP_PRESERVE_RE.sub(lambda m: math_fix(m.group(0)), text)
    text = _wrap_loose_math_lines(text)

    parts: list[str] = []
    last = 0
    for m in _MINI_APP_PRESERVE_RE.finditer(text):
        prose = text[last:m.start()]
        parts.append(clean_latex(prose))
        parts.append(m.group(0))
        last = m.end()
    parts.append(clean_latex(text[last:]))
    return "".join(parts)
