"""
Telegram message handlers.

Аналог обработчиков команд в `telegram-bot.ts` (`bot.command(...)`,
`bot.on('message:text', ...)`, и т.д.). Каждая функция — самостоятельный
обработчик одного типа апдейта или callback'а.
"""
import asyncio
import html
import io
import re

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import (
    logger,
    pending_answers,
    pending_choice_messages,
    user_format_choice,
)
from .latex.clean import clean_latex_outside_formulas
from .latex.short_answer import (
    count_problems,
    count_short_lines,
    extract_answers_only,
    llm_extract_short_answers,
    pretty_short,
)
from .render.images import solution_to_image
from .render.mini_app import make_solution_title, publish_to_mini_app
from .render.plot import extract_plot_tasks, plot_function_png, plot_function_svg
from .render.telegraph import (
    TELEGRAPH_TOKEN,
    init_telegraph,
    publish_to_telegraph,
)
from .solver import (
    ask_qwen_image,
    ask_qwen_text,
    delete_qwen_chats,
    sanitize_model_output,
)


# ─── Постоянная клавиатура под полем ввода ───────────────────────────────────
SETTINGS_BTN = "⚙ Настройки"
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(SETTINGS_BTN)]],
    resize_keyboard=True,
    is_persistent=True,
)


# ─── /start ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я твоя шпаргалка.\n\n"
        "📸 Отправь фото задания или напиши задачу текстом — "
        "и я дам красивое решение!\n\n"
        "⚙ В настройках можно выбрать формат по умолчанию: "
        "подробный (с открытием в Mini App) или краткий "
        "(только финальный ответ в чате).",
        reply_markup=MAIN_KEYBOARD,
    )


# ─── Меню «⚙ Настройки» ──────────────────────────────────────────────────────
def _format_label(user_id: int) -> str:
    choice = user_format_choice.get(user_id)
    if choice == "detailed":
        return "📖 Подробный (по умолчанию)"
    if choice == "short":
        return "⚡ Краткий (по умолчанию)"
    return "❓ не выбран — спрашиваю каждый раз"


async def handle_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"⚙ <b>Настройки</b>\n\n"
        f"Текущий формат ответа: <i>{html.escape(_format_label(user_id))}</i>\n\n"
        f"Выбери формат — он будет применяться ко всем новым задачам:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📖 Подробный",
                    callback_data="set_format_detailed",
                ),
                InlineKeyboardButton(
                    "⚡ Краткий",
                    callback_data="set_format_short",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔄 Сбросить (спрашивать каждый раз)",
                    callback_data="set_format_reset",
                ),
            ],
        ]),
    )


async def set_format_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Сохраняет выбор формата и подтверждает."""
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"set_format query.answer() failed: {e}")

    data = query.data or ""
    if data == "set_format_detailed":
        user_format_choice[user_id] = "detailed"
        text = (
            "✅ Формат по умолчанию: <b>📖 Подробный</b>\n"
            "Решения будут открываться в Mini App."
        )
    elif data == "set_format_short":
        user_format_choice[user_id] = "short"
        text = (
            "✅ Формат по умолчанию: <b>⚡ Краткий</b>\n"
            "В чате — только финальные ответы, оформленные цитатой."
        )
    else:
        user_format_choice.pop(user_id, None)
        text = (
            "🔄 Сброшено. Бот будет спрашивать формат после каждой задачи."
        )

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        try:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ─── Общая обработка готового ответа ─────────────────────────────────────────
async def process_answer(
    update,
    user_id: int,
    thinking_msg,
    answer: str,
) -> None:
    """Сохраняет ответ и либо сразу рендерит в выбранном формате,
    либо показывает выбор «Подробный / Краткий».
    """
    answer = sanitize_model_output(answer)
    pending_answers[user_id] = answer
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    choice = user_format_choice.get(user_id)
    if choice == "detailed":
        await _render_detailed(update.message, user_id, answer)
        return
    if choice == "short":
        await _render_short(update.message, user_id, answer)
        return

    msg = await update.message.reply_text(
        "✅ Решение готово! Какой формат выбрать?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📖 Подробный ответ",
                callback_data="show_detailed",
            ),
            InlineKeyboardButton(
                "⚡ Краткий ответ",
                callback_data="show_short",
            ),
        ]]),
    )
    pending_choice_messages[user_id] = msg.message_id


async def cleanup_qwen_chats() -> None:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, delete_qwen_chats)
    except Exception as e:
        logger.warning(f"Qwen cleanup error: {e}")


# ─── Текст ───────────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    question = update.message.text or ""

    # Кнопка «⚙ Настройки» из ReplyKeyboard приходит как обычный текст.
    if question.strip() == SETTINGS_BTN:
        await handle_settings(update, context)
        return

    thinking_msg = await update.message.reply_text("🤔 Решаю задачу...")
    try:
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, ask_qwen_text, question)
        if not answer or len(answer) < 10:
            await thinking_msg.edit_text(
                "❌ Не удалось решить задачу. Попробуй ещё раз или "
                "отправь задание в другом формате."
            )
            return
        await process_answer(update, user_id, thinking_msg, answer)
        await cleanup_qwen_chats()
    except Exception as e:
        logger.error(f"Ошибка (текст): {e}")
        try:
            await thinking_msg.edit_text(
                "❌ Ошибка: не удалось обработать запрос. Попробуй ещё раз."
            )
        except Exception:
            pass


# ─── Фото ────────────────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    caption = (update.message.caption or "").strip()
    if caption:
        thinking_msg = await update.message.reply_text(
            "📷 Читаю задание с фото и учитываю твоё сообщение..."
        )
    else:
        thinking_msg = await update.message.reply_text(
            "📷 Читаю задание с фото..."
        )
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = bytes(await photo_file.download_as_bytearray())
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, ask_qwen_image, photo_bytes, caption
        )
        if not answer or len(answer) < 10:
            await thinking_msg.edit_text(
                "❌ Не удалось распознать задание на фото. Попробуй ещё раз."
            )
            return
        await process_answer(update, user_id, thinking_msg, answer)
        await cleanup_qwen_chats()
    except Exception as e:
        logger.error(f"Ошибка (фото): {e}")
        try:
            await thinking_msg.edit_text(
                "❌ Ошибка: не удалось обработать фото. Попробуй ещё раз."
            )
        except Exception:
            pass


# ─── Фото как документ ───────────────────────────────────────────────────────
async def handle_document(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image/"):
        user_id = update.effective_user.id
        caption = (update.message.caption or "").strip()
        if caption:
            thinking_msg = await update.message.reply_text(
                "📷 Читаю задание с фото и учитываю твоё сообщение..."
            )
        else:
            thinking_msg = await update.message.reply_text(
                "📷 Читаю задание с фото..."
            )
        try:
            file = await doc.get_file()
            img_bytes = bytes(await file.download_as_bytearray())
            loop = asyncio.get_event_loop()
            answer = await loop.run_in_executor(
                None, ask_qwen_image, img_bytes, caption
            )
            if not answer or len(answer) < 10:
                await thinking_msg.edit_text(
                    "❌ Не удалось распознать задание. Попробуй ещё раз."
                )
                return
            await process_answer(update, user_id, thinking_msg, answer)
            await cleanup_qwen_chats()
        except Exception as e:
            logger.error(f"Ошибка (документ): {e}")
            try:
                await thinking_msg.edit_text(
                    "❌ Ошибка при обработке документа. Попробуй ещё раз."
                )
            except Exception:
                pass
    else:
        await update.message.reply_text("📎 Я работаю только с фото и текстом!")


# ─── Подробный рендер ────────────────────────────────────────────────────────
async def _render_detailed(target_msg, user_id: int, answer: str) -> None:
    """Публикует подробное решение: Mini App → Telegraph → PNG → текст."""
    answer = sanitize_model_output(answer)
    answer = clean_latex_outside_formulas(answer)
    thinking = await target_msg.reply_text(
        "🌐 Готовлю мини-приложение с решением..."
    )
    loop = asyncio.get_running_loop()

    plot_specs = extract_plot_tasks(answer)
    plot_outputs: list[tuple[str, str | None, bytes | None]] = []
    for spec in plot_specs[:6]:
        svg = await loop.run_in_executor(
            None, plot_function_svg,
            spec["expr"], spec["label"], spec["x_range"], 50.0,
        )
        png = await loop.run_in_executor(
            None, plot_function_png,
            spec["expr"], spec["label"], spec["x_range"], 50.0,
        )
        plot_outputs.append((spec["label"], svg, png))

    for label, svg, _png in plot_outputs:
        if not svg:
            continue
        figure_block = f"\n\n```figure:{label}\n{svg}\n```\n"
        m = re.search(
            r"(?ius)постро(?:й|ить|йте)[^.\n]*?график[^.\n]*?функци\w+[^.\n]*?",
            answer,
        )
        if m:
            insert_at = answer.find("\n", m.end())
            if insert_at < 0:
                insert_at = len(answer)
            answer = answer[:insert_at] + figure_block + answer[insert_at:]
        else:
            answer += figure_block

    for label, _svg, png in plot_outputs:
        if not png:
            continue
        try:
            await target_msg.reply_photo(
                photo=io.BytesIO(png),
                caption=f"📈 График: {label}",
            )
        except Exception as e:
            logger.error(f"Не удалось отправить график {label}: {e}")

    title = make_solution_title(answer)

    mini_app_url = await loop.run_in_executor(
        None, publish_to_mini_app, title, answer, user_id
    )

    try:
        await thinking.delete()
    except Exception:
        pass

    if mini_app_url:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📖 Открыть в приложении",
                web_app=WebAppInfo(url=mini_app_url),
            )],
            [InlineKeyboardButton(
                "🌐 Открыть в браузере",
                url=mini_app_url,
            )],
        ])
        try:
            await target_msg.reply_text(
                f"✅ Решение готово! Тапни «Открыть в приложении» — "
                f"откроется внутри Telegram, красиво и адаптивно.\n\n"
                f"🔗 {mini_app_url}",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"reply with web_app failed: {e}")
        await target_msg.reply_text(
            "📚 Отправь новое задание — фото или текст!"
        )
        return

    if not TELEGRAPH_TOKEN:
        await loop.run_in_executor(None, init_telegraph)
    telegraph_url = await loop.run_in_executor(
        None, publish_to_telegraph, title, answer
    )
    if telegraph_url:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📖 Открыть подробное решение",
                url=telegraph_url,
            ),
        ]])
        await target_msg.reply_text(
            f"✅ Решение готово (Mini App временно недоступен, открыта "
            f"Telegraph-версия).\n\n🔗 {telegraph_url}",
            reply_markup=kb,
            disable_web_page_preview=False,
        )
        await target_msg.reply_text(
            "📚 Отправь новое задание — фото или текст!"
        )
        return

    image_bytes = await loop.run_in_executor(None, solution_to_image, answer)
    if image_bytes:
        try:
            if len(image_bytes) > 9 * 1024 * 1024:
                await target_msg.reply_document(
                    document=io.BytesIO(image_bytes),
                    filename="solution.png",
                    caption="📖 Подробное решение",
                )
            else:
                await target_msg.reply_photo(
                    photo=io.BytesIO(image_bytes),
                    caption="📖 Подробное решение",
                )
        except Exception as e:
            logger.error(f"Не удалось отправить картинку решения: {e}")
            for chunk in [
                answer[i:i+4000] for i in range(0, len(answer), 4000)
            ]:
                await target_msg.reply_text(chunk)
    else:
        for chunk in [
            answer[i:i+4000] for i in range(0, len(answer), 4000)
        ]:
            await target_msg.reply_text(chunk)

    await target_msg.reply_text("📚 Отправь новое задание — фото или текст!")


# ─── Краткий рендер ──────────────────────────────────────────────────────────
def _short_to_html_blockquote(short_answer: str) -> str:
    """Превращает «✅ Ответ: …» в HTML с blockquote-цитатой."""
    s = (short_answer or "").strip()
    if not s:
        s = "Не удалось выделить ответ."

    lines = [ln for ln in s.splitlines() if ln.strip()]
    quoted = "\n".join(html.escape(ln) for ln in lines)

    header = "<b>✅ Ответ готов</b>"
    return (
        f"{header}\n"
        f"<blockquote>{quoted}</blockquote>\n"
        f"<i>✏️ Проверяй ответы самостоятельно</i>"
    )


async def _render_short(target_msg, user_id: int, answer: str) -> None:
    """Только финальные ответы, оформленные как HTML-цитата."""
    answer = sanitize_model_output(answer)
    short_answer = sanitize_model_output(extract_answers_only(answer))

    expected = count_problems(answer)
    extracted = count_short_lines(short_answer)

    needs_llm = (
        not short_answer
        or "$$" in short_answer
        or re.search(r"^\s*\d+\.\s*\$+\s*$", short_answer, flags=re.MULTILINE)
        or (expected >= 2 and extracted < max(2, expected - 1))
    )
    if needs_llm:
        loop = asyncio.get_running_loop()
        llm_short = await loop.run_in_executor(
            None, llm_extract_short_answers, answer
        )
        if llm_short:
            if "\n" in llm_short:
                short_answer = "✅ Ответы:\n" + llm_short
            else:
                short_answer = f"✅ Ответ: {llm_short}"

    if not short_answer:
        last_line = next(
            (ln.strip() for ln in reversed(answer.splitlines()) if ln.strip()),
            "",
        )
        last_line = pretty_short(last_line)
        short_answer = (
            f"✅ Ответ: {last_line}"
            if last_line
            else "⚠️ Не удалось выделить ответ."
        )

    short_answer = re.sub(r"\n{3,}", "\n\n", short_answer).strip()
    pretty = _short_to_html_blockquote(short_answer)

    try:
        await target_msg.reply_text(pretty, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"reply_html failed, fallback to plain: {e}")
        for chunk in [
            short_answer[i:i+4000] for i in range(0, len(short_answer), 4000)
        ]:
            await target_msg.reply_text(chunk)


# ─── Кнопка «Подробно» (если выбор формата не сохранён) ──────────────────────
async def show_detailed_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"query.answer() failed (stale callback?): {e}")
    answer = pending_answers.get(user_id)
    if not answer:
        try:
            await query.message.reply_text(
                "⚠️ Ответ не найден. Отправь задание заново."
            )
        except Exception:
            pass
        return

    if user_id in pending_choice_messages:
        try:
            await query.message.delete()
        except Exception:
            pass
        del pending_choice_messages[user_id]

    await _render_detailed(query.message, user_id, answer)


# ─── Кнопка «Кратко» (если выбор формата не сохранён) ────────────────────────
async def show_short_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"query.answer() failed (stale callback?): {e}")
    answer = pending_answers.get(user_id)
    if not answer:
        try:
            await query.message.reply_text(
                "⚠️ Ответ не найден. Отправь задание заново."
            )
        except Exception:
            pass
        return

    if user_id in pending_choice_messages:
        try:
            await query.message.delete()
        except Exception:
            pass
        del pending_choice_messages[user_id]

    await _render_short(query.message, user_id, answer)
