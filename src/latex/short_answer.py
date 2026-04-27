"""
Извлечение коротких ответов из полного решения и LLM-fallback.

Аналог `oauth/qwen-browser-auth.ts`: вспомогательный модуль внутри
подсистемы латекса/текста, занимающийся «вторичным» преобразованием
данных — превращением подробного решения в чистый список финальных
ответов.
"""
import re

from ..config import TEXT_MODEL, logger, qwen_client
from .prompts import LLM_SHORT_PROMPT


# Ищем строки с финальным ответом.
_ANSWER_LINE_RE = re.compile(
    r"(?im)^\s*(?:[✅📌]\s*)?\**\s*"
    r"(?P<kw>Уточнённый\s+ответ|Правильный\s+ответ|Ответ)"
    r"\s*\**(?:\s*\([^)]*\))?\s*\**\s*[:—-]\s*\**\s*"
    r"(?P<val>.+?)\s*\**\s*$"
)

# Заголовок-секция «Ответ».
_ANSWER_HEADER_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:\d+[.)]\s*)?\**\s*"
    r"(?:[✅📌]\s*)?\**\s*"
    r"(?:Уточнённый\s+ответ|Правильный\s+ответ|Ответ)"
    r"\s*\**\s*$"
)

# Одиночные `\boxed{...}`.
_BOXED_LINE_RE = re.compile(
    r"(?im)^\s*\$?\s*\\boxed\s*(?:\{(?P<v1>[^{}]+)\}|"
    r"(?P<v2>-?\d+(?:[.,]\d+)?|[A-Za-zА-Яа-я]))\s*\$?\s*$"
)

# Финальный блок-сводка.
_SUMMARY_HEADER_RE = re.compile(
    r"(?im)^\s*\**\s*(?:[✅📌]\s*)?\**\s*"
    r"(?:ИТОГОВ(?:ЫЕ|ЫЙ)\s+ОТВЕТ(?:Ы)?|ФИНАЛЬН(?:ЫЕ|ЫЙ)\s+ОТВЕТ(?:Ы)?)"
    r"\s*\**\s*[:—-]?\s*\**\s*(?P<inline>.*?)\s*\**\s*$"
)


def pretty_short(s: str) -> str:
    """Превращает строку с LaTeX/markdown в красивый Unicode для одного
    финального ответа.
    """
    if not s:
        return s
    s = re.sub(r"\$\$+(.+?)\$\$+", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$(.+?)\$", r"\1", s)
    s = re.sub(r"\\\((.+?)\\\)", r"\1", s)
    s = re.sub(r"\\\[(.+?)\\\]", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$\s*\$+", "", s)
    s = re.sub(r"\\boxed\s*\{\s*\}", "", s)
    s = s.replace("$$", "")
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)

    s = re.sub(r"\\boxed\s*\{(.+?)\}", r"\1", s)
    s = re.sub(r"\\boxed\s*([A-Za-zА-Яа-я0-9.\-]+)", r"\1", s)
    s = re.sub(r"\\text\s*\{(.+?)\}", r"\1", s)
    s = re.sub(r"\\mathrm\s*\{(.+?)\}", r"\1", s)
    s = re.sub(r"\\mathbf\s*\{(.+?)\}", r"\1", s)
    s = re.sub(r"\\operatorname\s*\{(.+?)\}", r"\1", s)
    s = re.sub(r"\\(?:left|right|displaystyle|quad|qquad|;|,|!)", " ", s)

    _SUP_DIGITS = {
        "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
        "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻", "+": "⁺",
    }
    _to_sup = lambda d: "".join(_SUP_DIGITS.get(c, c) for c in d)
    s = re.sub(r"\^\{([\-+]?\d+)\}", lambda m: _to_sup(m.group(1)), s)
    s = re.sub(r"\^([\-+]?\d)", lambda m: _to_sup(m.group(1)), s)

    _SUB_DIGITS = {
        "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅",
        "6": "₆", "7": "₇", "8": "₈", "9": "₉", "-": "₋", "+": "₊",
    }
    s = re.sub(
        r"_\{(\d+)\}",
        lambda m: "".join(_SUB_DIGITS.get(c, c) for c in m.group(1)),
        s,
    )
    s = re.sub(
        r"_(\d)",
        lambda m: _SUB_DIGITS.get(m.group(1), "_" + m.group(1)),
        s,
    )

    s = re.sub(r"\\vec\s*\{([^{}]+)\}", lambda m: m.group(1) + "\u20D7", s)
    s = re.sub(r"\\hat\s*\{([^{}]+)\}", lambda m: m.group(1) + "\u0302", s)
    s = re.sub(r"\\bar\s*\{([^{}]+)\}", lambda m: m.group(1) + "\u0304", s)
    s = re.sub(r"\\tilde\s*\{([^{}]+)\}", lambda m: m.group(1) + "\u0303", s)

    def _frac(m: re.Match) -> str:
        a, b = m.group(1).strip(), m.group(2).strip()
        wrap = lambda x: f"({x})" if re.search(r"[+\-]", x) and len(x) > 1 else x
        return f"{wrap(a)}/{wrap(b)}"

    for _ in range(5):
        new_s = re.sub(r"\\d?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", _frac, s)
        if new_s == s:
            break
        s = new_s

    def _sqrt(m: re.Match) -> str:
        x = m.group(1).strip()
        return f"√{x}" if re.fullmatch(r"[\wА-Яа-я²³⁰-⁹.,]+", x) else f"√({x})"

    s = re.sub(r"\\sqrt\s*\{([^{}]+)\}", _sqrt, s)
    s = re.sub(
        r"\\sqrt\s*\[([^\]]+)\]\s*\{([^{}]+)\}",
        lambda m: f"{m.group(1)}√{m.group(2)}",
        s,
    )

    s = re.sub(r"\^\{([^{}]+)\}", lambda m: f"^({m.group(1)})", s)
    s = re.sub(r"_\{([^{}]+)\}", lambda m: f"_{m.group(1)}", s)

    _GREEK = {
        "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
        "epsilon": "ε", "varepsilon": "ε",
        "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
        "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
        "xi": "ξ", "pi": "π", "varpi": "ϖ", "rho": "ρ",
        "sigma": "σ", "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ",
        "psi": "ψ", "omega": "ω",
        "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
        "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ",
        "Omega": "Ω",
    }
    for name, ch in _GREEK.items():
        s = re.sub(rf"\\{name}\b", ch, s)

    _SYMS = {
        r"\\pm": "±", r"\\mp": "∓", r"\\times": "×", r"\\div": "÷",
        r"\\cdot": "·", r"\\le(?:q)?\b": "≤", r"\\ge(?:q)?\b": "≥",
        r"\\neq": "≠", r"\\approx": "≈", r"\\equiv": "≡",
        r"\\to": "→", r"\\rightarrow": "→", r"\\leftarrow": "←",
        r"\\Rightarrow": "⇒", r"\\Leftrightarrow": "⇔",
        r"\\infty": "∞", r"\\sum": "∑", r"\\int": "∫", r"\\partial": "∂",
        r"\\in\b": "∈", r"\\notin\b": "∉", r"\\subset": "⊂",
        r"\\cup": "∪", r"\\cap": "∩", r"\\emptyset": "∅",
        r"\\angle": "∠", r"\\degree|\\deg\b": "°", r"\\circ\b": "°",
    }
    for pat, ch in _SYMS.items():
        s = re.sub(pat, ch, s)

    s = re.sub(r"\\[,;:!>]", "", s)
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = s.rstrip(".,;").strip()
    if re.fullmatch(r"[\$\s\{\}\(\)\[\]]*", s):
        return ""
    return s


def count_problems(answer: str) -> int:
    """Грубо оценивает, сколько отдельных задач решено в полном ответе."""
    if not answer:
        return 0
    n = 0
    n += len(_ANSWER_LINE_RE.findall(answer))
    for ln in answer.splitlines():
        if _ANSWER_HEADER_RE.match(ln):
            n += 1
        elif _BOXED_LINE_RE.match(ln):
            n += 1
    n = max(
        n,
        len(re.findall(
            r"(?im)^\s*(?:\*\*)?(?:Задача\s+)?\d{1,3}[.)]", answer
        )) // 2,
    )
    return n


def count_short_lines(short_answer: str) -> int:
    """Сколько отдельных ответов в уже сформированном коротком сообщении."""
    if not short_answer:
        return 0
    text = short_answer
    text = re.sub(r"^✅\s*Ответы:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^✅\s*Ответ:\s*", "", text, flags=re.MULTILINE)
    return sum(1 for ln in text.splitlines() if ln.strip())


def _extract_summary_block(answer: str) -> str:
    """Если модель сделала финальный блок «ИТОГОВЫЕ ОТВЕТЫ:» — возвращает
    готовую короткую сводку. Иначе пустую строку."""
    lines = answer.splitlines()
    header_idx = -1
    inline_val = ""
    for i, ln in enumerate(lines):
        m = _SUMMARY_HEADER_RE.match(ln)
        if m:
            header_idx = i
            inline_val = (m.group("inline") or "").strip()
    if header_idx < 0:
        return ""

    raw_items: list[str] = []
    if inline_val:
        raw_items.append(inline_val)

    j = header_idx + 1
    while j < len(lines):
        ln = lines[j].strip()
        if not ln:
            j += 1
            continue
        if ln in ("---", "===", "***"):
            break
        if ln.startswith(("📚", "🔍", "✅", "📖", "⚡", "💡", "📋", "🔣")):
            break
        if re.match(r"^#{1,6}\s", ln):
            break
        raw_items.append(ln)
        j += 1

    cleaned: list[str] = []
    for item in raw_items:
        item = re.sub(r"^[-•*]\s+", "", item)
        m = re.match(r"^\s*(?P<num>\d+)\s*[.)\]]\s*(?P<rest>.+)$", item)
        num = m.group("num") if m else ""
        rest = (m.group("rest") if m else item).strip()
        rest = pretty_short(rest)
        if not rest:
            continue
        if num:
            cleaned.append(f"{num}. {rest}")
        else:
            cleaned.append(rest)

    if not cleaned:
        return ""
    if len(cleaned) == 1 and not re.match(r"^\d+\.", cleaned[0]):
        return f"✅ Ответ: {cleaned[0]}"
    return "✅ Ответы:\n" + "\n".join(cleaned)


def llm_extract_short_answers(full_answer: str) -> str:
    """Просит модель собрать чистый список финальных ответов."""
    if not full_answer or not full_answer.strip():
        return ""
    try:
        r = qwen_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": LLM_SHORT_PROMPT},
                {"role": "user", "content": full_answer},
            ],
            max_tokens=512,
            temperature=0.0,
        )
        out = (r.choices[0].message.content or "").strip()
        out = re.sub(
            r"(?im)^\s*\**\s*(?:[✅📌]\s*)?\**\s*"
            r"(?:ИТОГОВ(?:ЫЕ|ЫЙ)\s+ОТВЕТ(?:Ы)?|ФИНАЛЬН(?:ЫЕ|ЫЙ)\s+ОТВЕТ(?:Ы)?|"
            r"Ответы|Ответ)\s*[:—-]?\s*\**\s*$",
            "",
            out,
        ).strip()
        nice: list[str] = []
        for ln in out.splitlines():
            ln = ln.strip().lstrip("-•* ").strip()
            if not ln:
                continue
            m = re.match(r"^\s*(?P<num>\d+)\s*[.)\]]\s*(?P<rest>.+)$", ln)
            num = m.group("num") if m else ""
            rest = (m.group("rest") if m else ln).strip()
            rest = pretty_short(rest)
            if not rest:
                continue
            nice.append(f"{num}. {rest}" if num else rest)
        return "\n".join(nice)
    except Exception as e:
        logger.warning(f"LLM-short extractor error: {e}")
        return ""


def extract_answers_only(answer: str) -> str:
    """Извлекает из полного ответа модели ТОЛЬКО финальные ответы.

    Источники (в порядке приоритета):
      0. Финальный блок `ИТОГОВЫЕ ОТВЕТЫ:` / `ИТОГОВЫЙ ОТВЕТ:`.
      1. `Ответ: X`, `✅ Ответ: X`, `📌 Уточнённый ответ: X`.
      2. Заголовок `## Ответ` + следующая непустая строка.
      3. Одиночный `\\boxed{X}` на отдельной строке.
    """
    lines = answer.splitlines()

    summary = _extract_summary_block(answer)
    if summary:
        return summary

    used_lines: set[int] = set()
    raw_answers: list[tuple[int, str, bool]] = []

    for m in _ANSWER_LINE_RE.finditer(answer):
        ans = m.group("val").strip()
        kw = m.group("kw").lower()
        ans = re.split(r"\n", ans, 1)[0].strip().rstrip("*").strip()
        if not ans:
            continue
        line_idx = answer.count("\n", 0, m.start())
        used_lines.add(line_idx)
        raw_answers.append((line_idx, ans, "уточн" in kw))

    for i, line in enumerate(lines):
        if i in used_lines or not _ANSWER_HEADER_RE.match(line):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or j in used_lines:
            continue
        ans = lines[j].strip()
        if ans:
            used_lines.add(i)
            used_lines.add(j)
            raw_answers.append((i, ans, False))

    for i, line in enumerate(lines):
        if i in used_lines:
            continue
        m = _BOXED_LINE_RE.match(line)
        if not m:
            continue
        val = (m.group("v1") or m.group("v2") or "").strip()
        if val:
            used_lines.add(i)
            raw_answers.append((i, val, False))

    if not raw_answers:
        return ""

    raw_answers.sort(key=lambda t: t[0])

    final: list[str] = []
    for _idx, val, is_corr in raw_answers:
        if is_corr and final:
            final[-1] = val
        else:
            final.append(val)

    cleaned = [pretty_short(a) for a in final]
    cleaned = [a for a in cleaned if a]

    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"✅ Ответ: {cleaned[0]}"
    out = ["✅ Ответы:"]
    for idx, a in enumerate(cleaned, 1):
        out.append(f"{idx}. {a}")
    return "\n".join(out)
