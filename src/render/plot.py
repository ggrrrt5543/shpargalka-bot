"""
Серверный плоттер графиков функций y = f(x).

Аналог `proxy/api-proxy.ts`: вспомогательный сервис, преобразующий
данные (LLM-ответ → SVG/PNG графика). Когда задание содержит «постройте
график функции y = f(x)», LLM нередко забывает нарисовать график. Поэтому
мы строим его сами через matplotlib и отдаём как PNG в чат + SVG в Mini App.
"""
import io
import math as _m
import re

from ..config import MATPLOTLIB_AVAILABLE, logger

if MATPLOTLIB_AVAILABLE:
    import matplotlib.pyplot as plt

# Лениво заполняемая таблица имён, разрешённых в выражении функции.
_FUNC_SAFE_NAMES: dict = {}


def _init_func_safe_names() -> None:
    """Лениво заполняет таблицу разрешённых имён для безопасного eval."""
    global _FUNC_SAFE_NAMES
    if _FUNC_SAFE_NAMES:
        return
    try:
        import numpy as np
    except ImportError:
        return
    _FUNC_SAFE_NAMES.update({
        "pi": np.pi, "e": np.e,
        "sin": np.sin, "cos": np.cos, "tan": np.tan,
        "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan,
        "arcsin": np.arcsin, "arccos": np.arccos, "arctan": np.arctan,
        "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
        "ctg": lambda v: 1.0 / np.tan(v),
        "cot": lambda v: 1.0 / np.tan(v),
        "log": np.log, "ln": np.log, "log2": np.log2, "log10": np.log10,
        "lg": np.log10,
        "exp": np.exp, "sqrt": np.sqrt, "abs": np.abs,
        "min": np.minimum, "max": np.maximum,
    })


def _normalize_func_expr(expr: str) -> str:
    """Превращает «человеческое» выражение функции в Python-выражение для numpy.
    Например: ``2 - x² + 2x³``  →  ``2 - x**2 + 2*x**3``.
    """
    if not expr:
        return ""
    s = expr.strip()
    s = (
        s.replace("·", "*")
         .replace("×", "*")
         .replace("−", "-")
         .replace("–", "-")
    )
    s = s.replace("π", "pi").replace("√", "sqrt")
    s = s.replace("²", "**2").replace("³", "**3").replace("⁴", "**4")
    s = s.replace("⁵", "**5").replace("⁶", "**6").replace("⁷", "**7")
    s = s.replace("⁸", "**8").replace("⁹", "**9").replace("⁰", "**0")
    s = s.replace("^", "**")
    s = re.sub(
        r"log_\{?([0-9.]+)\}?\s*\(([^)]+)\)",
        lambda m: f"(log({m.group(2)})/log({m.group(1)}))",
        s,
    )
    s = re.sub(
        r"log[_]?(\d+(?:\.\d+)?)\s*\(([^)]+)\)",
        lambda m: f"(log({m.group(2)})/log({m.group(1)}))",
        s,
    )
    _SUB_TO_DIGIT = {
        "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
        "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    }

    def _log_sub(m: re.Match) -> str:
        base = "".join(_SUB_TO_DIGIT[c] for c in m.group(1))
        return f"(log({m.group(2)})/log({base}))"

    s = re.sub(r"log([₀-₉]+)\s*\(([^)]+)\)", _log_sub, s)
    s = re.sub(
        r"log([₀-₉]+)\s*([a-zA-Z][a-zA-Z0-9]*)",
        lambda m: f"(log({m.group(2)})/log({''.join(_SUB_TO_DIGIT[c] for c in m.group(1))}))",
        s,
    )
    s = re.sub(r"(\d)\s*([A-Za-z\(])", r"\1*\2", s)
    s = re.sub(r"(\))\s*([A-Za-z0-9\(])", r"\1*\2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _compile_safe_expr(expr: str):
    """Компилирует выражение в безопасный bytecode (только числа, операторы,
    разрешённые имена функций и переменная ``x``).
    """
    import ast
    allowed = (
        ast.Module, ast.Expression, ast.Expr, ast.Constant,
        ast.Name, ast.Load,
        ast.BinOp, ast.UnaryOp,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
        ast.USub, ast.UAdd,
        ast.Call,
        ast.IfExp, ast.Compare,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    )
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError(f"unsafe node: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id != "x" and node.id not in _FUNC_SAFE_NAMES:
                raise ValueError(f"unknown name: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("only direct function calls are allowed")
    return compile(tree, "<func>", "eval")


def _compute_function_samples(
    expr_raw: str,
    x_range: tuple[float, float] = (-10.0, 10.0),
    y_clip: float = 50.0,
    n_points: int = 800,
):
    """Сэмплирует y = f(x). Возвращает (x, y, x_min, x_max, y_min, y_max)."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    _init_func_safe_names()
    norm = _normalize_func_expr(expr_raw)
    if not norm:
        return None
    try:
        code = _compile_safe_expr(norm)
    except Exception as e:
        logger.warning(f"plot: cannot compile {expr_raw!r} → {norm!r}: {e}")
        return None
    try:
        x_min, x_max = float(x_range[0]), float(x_range[1])
        x = np.linspace(x_min, x_max, n_points)
        env = {"__builtins__": {}}
        env.update(_FUNC_SAFE_NAMES)
        env["x"] = x
        with np.errstate(all="ignore"):
            y = eval(code, env)
        y = np.asarray(y, dtype=float)
        if y.ndim == 0:
            y = np.full_like(x, float(y))
        y = np.where(np.isfinite(y), y, np.nan)
        if y_clip > 0:
            y = np.where(np.abs(y) > y_clip, np.nan, y)
        if len(y) > 1:
            diff = np.abs(np.diff(y))
            jump_idx = np.where(diff > max(10.0, y_clip / 2))[0]
            for j in jump_idx:
                y[j + 1] = np.nan
        finite = y[np.isfinite(y)]
        if finite.size == 0:
            return None
        y_lo, y_hi = float(np.nanmin(finite)), float(np.nanmax(finite))
        pad = max(0.5, (y_hi - y_lo) * 0.1)
        y_min = max(-y_clip, y_lo - pad)
        y_max = min(y_clip, y_hi + pad)
        if y_min == y_max:
            y_min -= 1.0
            y_max += 1.0
        return x, y, x_min, x_max, y_min, y_max
    except Exception as e:
        logger.error(f"_compute_function_samples error for {expr_raw!r}: {e}")
        return None


def plot_function_svg(
    expr_raw: str,
    label: str = "",
    x_range: tuple[float, float] = (-10.0, 10.0),
    y_clip: float = 50.0,
) -> str | None:
    """Строит график y=f(x) как SVG-строку, используя только разрешённые
    Mini App'ом теги. Подходит для встраивания в блок ```figure:…```.
    """
    samples = _compute_function_samples(expr_raw, x_range, y_clip)
    if samples is None:
        return None
    try:
        x, y, x_min, x_max, y_min, y_max = samples

        W, H = 360, 240
        L, R, T, B = 36, 12, 28, 28
        plot_w = W - L - R
        plot_h = H - T - B

        def sx(xv: float) -> float:
            return L + (xv - x_min) / (x_max - x_min) * plot_w

        def sy(yv: float) -> float:
            return T + (y_max - yv) / (y_max - y_min) * plot_h

        def _nice_step(span: float) -> float:
            target = span / 8.0
            if target <= 0:
                return 1.0
            mag = 10 ** _m.floor(_m.log10(target))
            for k in (1, 2, 2.5, 5, 10):
                step = k * mag
                if step >= target:
                    return step
            return mag * 10

        step_x = _nice_step(x_max - x_min)
        step_y = _nice_step(y_max - y_min)

        parts: list[str] = []
        parts.append(
            f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
            f'font-family="sans-serif" font-size="10">'
        )
        parts.append(
            f'<rect x="0" y="0" width="{W}" height="{H}" fill="#1a1a2e"/>'
        )
        gx = _m.ceil(x_min / step_x) * step_x
        while gx <= x_max + 1e-9:
            X = sx(gx)
            parts.append(
                f'<line class="grid" x1="{X:.1f}" y1="{T}" '
                f'x2="{X:.1f}" y2="{T+plot_h}" '
                f'stroke="#444" stroke-width="0.5" opacity="0.6"/>'
            )
            gx += step_x
        gy = _m.ceil(y_min / step_y) * step_y
        while gy <= y_max + 1e-9:
            Y = sy(gy)
            parts.append(
                f'<line class="grid" x1="{L}" y1="{Y:.1f}" '
                f'x2="{L+plot_w}" y2="{Y:.1f}" '
                f'stroke="#444" stroke-width="0.5" opacity="0.6"/>'
            )
            gy += step_y

        if x_min <= 0 <= x_max:
            X0 = sx(0)
            parts.append(
                f'<line class="axis" x1="{X0:.1f}" y1="{T}" '
                f'x2="{X0:.1f}" y2="{T+plot_h}" stroke="#bbb" stroke-width="1"/>'
            )
        if y_min <= 0 <= y_max:
            Y0 = sy(0)
            parts.append(
                f'<line class="axis" x1="{L}" y1="{Y0:.1f}" '
                f'x2="{L+plot_w}" y2="{Y0:.1f}" stroke="#bbb" stroke-width="1"/>'
            )

        gx = _m.ceil(x_min / step_x) * step_x
        y_label = sy(0) if y_min <= 0 <= y_max else T + plot_h
        while gx <= x_max + 1e-9:
            if abs(gx) > 1e-9:
                X = sx(gx)
                v = (
                    f"{gx:.0f}"
                    if abs(gx - round(gx)) < 1e-6
                    else f"{gx:.2g}"
                )
                parts.append(
                    f'<text x="{X:.1f}" y="{min(T+plot_h+12, y_label+12):.1f}" '
                    f'fill="#bbb" text-anchor="middle">{v}</text>'
                )
            gx += step_x
        gy = _m.ceil(y_min / step_y) * step_y
        x_label = sx(0) if x_min <= 0 <= x_max else L
        while gy <= y_max + 1e-9:
            if abs(gy) > 1e-9:
                Y = sy(gy)
                v = (
                    f"{gy:.0f}"
                    if abs(gy - round(gy)) < 1e-6
                    else f"{gy:.2g}"
                )
                parts.append(
                    f'<text x="{max(L-4, x_label-4):.1f}" y="{Y+3:.1f}" '
                    f'fill="#bbb" text-anchor="end">{v}</text>'
                )
            gy += step_y

        parts.append(
            f'<text x="{L+plot_w-2}" y="{T+plot_h-4}" '
            f'fill="#aaa" text-anchor="end" font-style="italic">x</text>'
        )
        parts.append(
            f'<text x="{L+4}" y="{T+10}" '
            f'fill="#aaa" text-anchor="start" font-style="italic">y</text>'
        )

        d_parts: list[str] = []
        cur: list[str] = []
        for xv, yv in zip(x, y):
            if not (yv == yv):  # NaN
                if cur:
                    d_parts.append(" ".join(cur))
                    cur = []
                continue
            X = sx(float(xv))
            Y = sy(float(yv))
            cmd = "M" if not cur else "L"
            cur.append(f"{cmd}{X:.2f},{Y:.2f}")
        if cur:
            d_parts.append(" ".join(cur))
        if d_parts:
            d = " ".join(d_parts)
            parts.append(
                f'<path d="{d}" fill="none" '
                f'stroke="#4fc3f7" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )

        if label:
            safe_label = (
                label.replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;")
            )
            parts.append(
                f'<text x="{W/2:.0f}" y="16" fill="#ffd54f" '
                f'text-anchor="middle" font-size="13" '
                f'font-weight="bold">{safe_label}</text>'
            )

        parts.append("</svg>")
        return "".join(parts)
    except Exception as e:
        logger.error(f"plot_function_svg error for {expr_raw!r}: {e}")
        return None


def plot_function_png(
    expr_raw: str,
    label: str = "",
    x_range: tuple[float, float] = (-10.0, 10.0),
    y_clip: float = 50.0,
) -> bytes | None:
    """Строит график y = f(x) и возвращает PNG в bytes."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    _init_func_safe_names()
    norm = _normalize_func_expr(expr_raw)
    if not norm:
        return None
    try:
        code = _compile_safe_expr(norm)
    except Exception as e:
        logger.warning(f"plot: cannot compile {expr_raw!r} → {norm!r}: {e}")
        return None
    try:
        x_min, x_max = float(x_range[0]), float(x_range[1])
        x = np.linspace(x_min, x_max, 2000)
        env = {"__builtins__": {}}
        env.update(_FUNC_SAFE_NAMES)
        env["x"] = x
        with np.errstate(all="ignore"):
            y = eval(code, env)
        y = np.asarray(y, dtype=float)
        if y.ndim == 0:
            y = np.full_like(x, float(y))
        y = np.where(np.isfinite(y), y, np.nan)
        if y_clip > 0:
            y = np.where(np.abs(y) > y_clip, np.nan, y)
        if len(y) > 1:
            diff = np.abs(np.diff(y))
            jump_mask = np.where(diff > max(10.0, y_clip / 2))[0]
            for j in jump_mask:
                y[j + 1] = np.nan

        fig, ax = plt.subplots(figsize=(7, 5))
        ax.set_facecolor("#1a1a2e")
        fig.patch.set_facecolor("#1a1a2e")
        ax.plot(x, y, color="#4fc3f7", linewidth=2.4)
        ax.axhline(0, color="#888", linewidth=0.7)
        ax.axvline(0, color="#888", linewidth=0.7)
        ax.grid(True, color="#444", alpha=0.5, linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_color("#666")
        ax.tick_params(colors="#bbb", labelsize=9)
        finite_y = y[np.isfinite(y)]
        if finite_y.size:
            y_lo, y_hi = float(np.nanmin(finite_y)), float(np.nanmax(finite_y))
            pad = max(1.0, (y_hi - y_lo) * 0.1)
            ax.set_ylim(max(-y_clip, y_lo - pad), min(y_clip, y_hi + pad))
        ax.set_xlim(x_min, x_max)
        if label:
            ax.set_title(label, color="#ffd54f", fontsize=14, pad=10)
        ax.set_xlabel("x", color="#bbb")
        ax.set_ylabel("y", color="#bbb")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(
            buf, format="png", dpi=140, facecolor="#1a1a2e",
            edgecolor="none", bbox_inches="tight",
        )
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"plot_function_png error for {expr_raw!r}: {e}")
        try:
            plt.close()
        except Exception:
            pass
        return None


# Регулярка ловит «постройте … график функции … y = ...» в условии.
_PLOT_TASK_RE = re.compile(
    r"(?ius)постро(?:й|ить|йте)[^.]*?график[^.]*?функци\w+[^y\n]*?"
    r"(?:y|f\s*\(\s*x\s*\))\s*=\s*"
    r"(?P<expr>[A-Za-z0-9_\s\+\-\*/\^\(\)\.,²³⁴⁵⁶⁷⁸⁹⁰₀-₉πe√$]+?)"
    r"(?=[.;\n]|\s+(?:и|при|где|укажите|область|множество|постройте|на)\b|$)"
)


def extract_plot_tasks(text: str) -> list[dict]:
    """Возвращает список заданий «построй график функции y = …»."""
    if not text:
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for m in _PLOT_TASK_RE.finditer(text):
        raw = m.group("expr").strip().rstrip(",;:.- ")
        raw = re.sub(r"^\$+|\$+$", "", raw).strip()
        if not raw or len(raw) > 200:
            continue
        norm = _normalize_func_expr(raw)
        key = re.sub(r"\s+", "", norm)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append({
            "label": f"y = {raw}",
            "expr":  raw,
            "x_range": (-10.0, 10.0),
        })
    return found
