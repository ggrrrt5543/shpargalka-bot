"""
Чистка/починка LaTeX, который пришёл от модели.

Аналог `oauth/credentials-store.ts`: хранит набор предкомпилированных
регулярок и низкоуровневую функцию `_math_fix`, превращающую кривой
LaTeX в валидный.
"""
import re

# \veca, \vecb, \vecAB, \hatx, \tilden, \overlineAB и т.п. без скобок.
_VEC_NO_BRACE = re.compile(
    r"\\(vec|hat|tilde|bar|overline|widehat|widetilde)([A-Za-zА-Яа-я]+)\b"
)
# \textкириллица без скобок.
_TEXT_NO_BRACE = re.compile(r"\\text(?!\s*\{)([A-Za-zА-Яа-я0-9_]+)")
# \frac{...}{...} с одиночными аргументами без скобок.
_FRAC_NO_BRACE = re.compile(r"\\frac(?!\s*\{)\s*(\S)\s*(\S)")
# Дублированные обратные слеши.
_DOUBLE_BS = re.compile(
    r"\\\\(frac|sqrt|vec|sum|int|lim|cos|sin|tan|log|ln|alpha|beta|gamma|pi|theta|cdot|times)\b"
)
# (a)/(b) — псевдо-дробь.
_PSEUDO_FRAC = re.compile(r"\(([^()\n/]{1,40})\)\s*/\s*\(([^()\n/]{1,40})\)")
# Юникод-корень √(…) → \sqrt{…}.
_SQRT_PAREN = re.compile(r"√\s*\(([^()\n]{1,80})\)")
# Юникод-корень √число → \sqrt{число}.
_SQRT_NUM = re.compile(r"√\s*(\d+(?:[.,]\d+)?)")
# Юникод-степени.
_UNI_POW = {
    "²": "^{2}", "³": "^{3}", "⁴": "^{4}", "⁵": "^{5}",
    "⁶": "^{6}", "⁷": "^{7}", "⁸": "^{8}", "⁹": "^{9}",
    "¹": "^{1}", "⁰": "^{0}",
}
# Юникод-стрелки над буквой → \vec{...}.
_UNI_VEC = re.compile(r"([A-Za-zА-Яа-я]{1,3})\u20D7")
# \boxed0.5 без скобок → \boxed{0.5}.
_BOXED_NO_BRACE = re.compile(
    r"\\boxed(?!\s*\{)\s*(-?\d+(?:[.,]\d+)?|[A-Za-zА-Яа-я])"
)
# X_кириллица в индексе без скобок.
_CYR_SUB = re.compile(r"([A-Za-zА-Яа-я])_(?!\{|\\)([А-Яа-я][А-Яа-я0-9_]+)")
# Zero-ширинные пробелы.
_ZERO_WIDTH = re.compile(r"[\u200B\u200C\u200D\uFEFF]")


def math_fix(s: str) -> str:
    """Чинит куски LaTeX в уже-математическом контексте (внутри $...$ либо
    при обёртывании голой строки в $...$)."""
    s = _ZERO_WIDTH.sub("", s)
    s = (
        s.replace("∣", "|")
         .replace("−", "-")
         .replace("·", r"\cdot ")
         .replace("×", r"\times ")
    )
    s = _DOUBLE_BS.sub(r"\\\1", s)
    s = _UNI_VEC.sub(lambda m: f"\\vec{{{m.group(1)}}}", s)
    s = _VEC_NO_BRACE.sub(lambda m: f"\\{m.group(1)}{{{m.group(2)}}}", s)
    s = _TEXT_NO_BRACE.sub(
        lambda m: "\\text{" + m.group(1).replace("_", " ") + "}", s
    )
    s = _CYR_SUB.sub(
        lambda m: f"{m.group(1)}_{{\\text{{{m.group(2).replace('_', ' ')}}}}}",
        s,
    )
    s = _BOXED_NO_BRACE.sub(lambda m: f"\\boxed{{{m.group(1)}}}", s)
    s = _FRAC_NO_BRACE.sub(
        lambda m: f"\\frac{{{m.group(1)}}}{{{m.group(2)}}}", s
    )
    s = _PSEUDO_FRAC.sub(
        lambda m: f"\\frac{{{m.group(1).strip()}}}{{{m.group(2).strip()}}}",
        s,
    )
    s = _SQRT_PAREN.sub(lambda m: f"\\sqrt{{{m.group(1).strip()}}}", s)
    s = _SQRT_NUM.sub(lambda m: f"\\sqrt{{{m.group(1).strip()}}}", s)
    for u, l in _UNI_POW.items():
        s = s.replace(u, l)
    return s
