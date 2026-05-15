"""
Telegram message handlers.
"""
import asyncio
import html
import io
import re
import time

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

from .admin import (
    handle_admin_text_input,
    is_admin_awaiting_input,
    try_secret_phrase,
)
from .admin.ban import is_banned
from .config import (
    CACHE_TTL_HOURS,
    HISTORY_TIMEOUT_MINUTES,
    KNOWLEDGE_BASE_PATH,
    MAX_HISTORY_MESSAGES,
    logger,
    pending_choice_messages,
)
from .db import analytics as db_analytics
from .db import cache as db_cache
from .db import users as db_users
from .db import pending as db_pending
from .latex.clean import clean_latex_outside_formulas
from .latex.short_answer import (
    count_problems,
    count_short_lines,
    extract_answers_only,
    llm_extract_short_answers,
    pretty_short,
)
from .latex.subject_prompts import (
    SUBJECT_LABELS,
    SUBJECT_PROMPTS,
    detect_subject,
)
from .memory import ConversationMemory
from .rag import KnowledgeRetriever
from .render.mini_app import make_solution_title, publish_to_mini_app
from .render.plot import extract_plot_tasks, plot_function_png
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

# ─── Инициализация подсистем ─────────────────────────────────────────────────
memory = ConversationMemory(
    max_messages=MAX_HISTORY_MESSAGES,
    timeout_minutes=HISTORY_TIMEOUT_MINUTES,
)
retriever = KnowledgeRetriever()

# ─── Постоянная клавиатура (вместо /команд) ──────────────────────────────────
BTN_SETTINGS = "⚙ Настройки"
BTN_SUBJECT = "📚 Предмет"
BTN_STATS = "📊 Статистика"
BTN_CLEAR = "🗑 Очистить"
BTN_FORMAT = "📖 Режим ответа"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_FORMAT), KeyboardButton(BTN_SUBJECT)],
        [KeyboardButton(BTN_SETTINGS), KeyboardButton(BTN_STATS)],
        [KeyboardButton(BTN_CLEAR)],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


# ─── /start ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await db_users.get_or_create_user(user_id)
    await update.message.reply_text(
        "👋 Привет! Я твоя шпаргалка.\n\n"
        "📸 Отправь фото задания или напиши задачу текстом — "
        "и я дам красивое решение!\n\n"
        "💬 Я помню контекст — можешь уточнять вопросы!\n\n"
        "Кнопки внизу — настройки, предмет, статистика.",
        reply_markup=MAIN_KEYBOARD,
    )


# ─── Настройки ───────────────────────────────────────────────────────────────
def _settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Подробный", callback_data="set_format_detailed"),
            InlineKeyboardButton("⚡ Краткий", callback_data="set_format_short"),
        ],
        [
            InlineKeyboardButton("🔄 Сбросить формат", callback_data="set_format_reset"),
        ],
        [
            InlineKeyboardButton("📚 Выбрать предмет", callback_data="show_subjects"),
        ],
    ])


async def _show_settings(message, user_id: int) -> None:
    format_choice = await db_users.get_format_choice(user_id)
    subject = await db_users.get_subject(user_id)

    format_label = {
        "detailed": "📖 Подробный",
        "short": "⚡ Краткий",
    }.get(format_choice, "❓ спрашиваю каждый раз")

    subject_label = SUBJECT_LABELS.get(subject, "🤖 Авто")

    await message.reply_text(
        f"⚙ <b>Настройки</b>\n\n"
        f"Формат: <i>{html.escape(format_label)}</i>\n"
        f"Предмет: <i>{html.escape(subject_label)}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=_settings_keyboard(),
    )


async def set_format_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Сохраняет выбор формата."""
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass

    data = query.data or ""

    if data == "set_format_detailed":
        await db_users.set_format_choice(user_id, "detailed")
        try:
            await query.edit_message_text("✅ Режим: 📖 Подробный")
        except Exception:
            pass
    elif data == "set_format_short":
        await db_users.set_format_choice(user_id, "short")
        try:
            await query.edit_message_text("✅ Режим: ⚡ Краткий")
        except Exception:
            pass
    elif data == "show_subjects":
        await _show_subject_menu_edit(query)
        return
    else:
        await db_users.set_format_choice(user_id, None)
        try:
            await query.edit_message_text("✅ Режим: спрашиваю каждый раз")
        except Exception:
            pass


# ─── Предмет ─────────────────────────────────────────────────────────────────
def _subject_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for key, label in SUBJECT_LABELS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"set_subject_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_settings")])
    return InlineKeyboardMarkup(buttons)


async def _show_subject_menu_edit(query) -> None:
    """Показывает меню предметов (редактирует сообщение)."""
    try:
        await query.message.edit_text(
            "📚 Выбери предмет:",
            reply_markup=_subject_keyboard(),
        )
    except Exception:
        pass


async def _show_subject_menu(message) -> None:
    """Показывает меню предметов (новое сообщение)."""
    await message.reply_text(
        "📚 Выбери предмет:",
        reply_markup=_subject_keyboard(),
    )


async def set_subject_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Сохраняет выбор предмета."""
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass

    data = (query.data or "").replace("set_subject_", "")
    await db_users.set_subject(user_id, data)
    label = SUBJECT_LABELS.get(data, data)
    try:
        await query.edit_message_text(f"✅ Предмет: {label}")
    except Exception:
        pass


# ─── Callback «Назад к настройкам» ──────────────────────────────────────────
async def back_settings_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass

    format_choice = await db_users.get_format_choice(user_id)
    subject = await db_users.get_subject(user_id)

    format_label = {
        "detailed": "📖 Подробный",
        "short": "⚡ Краткий",
    }.get(format_choice, "❓ спрашиваю каждый раз")
    subject_label = SUBJECT_LABELS.get(subject, "🤖 Авто")

    try:
        await query.edit_message_text(
            f"⚙ <b>Настройки</b>\n\n"
            f"Формат: <i>{html.escape(format_label)}</i>\n"
            f"Предмет: <i>{html.escape(subject_label)}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=_settings_keyboard(),
        )
    except Exception:
        pass


# ─── Режим ответа ────────────────────────────────────────────────────────────
async def _show_format_menu(message, user_id: int) -> None:
    format_choice = await db_users.get_format_choice(user_id)
    current = {
        "detailed": "📖 Подробный",
        "short": "⚡ Краткий",
    }.get(format_choice, "❓ спрашиваю каждый раз")

    await message.reply_text(
        f"📖 <b>Режим ответа</b>\n\nСейчас: <i>{html.escape(current)}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📖 Подробный", callback_data="set_format_detailed"),
                InlineKeyboardButton("⚡ Краткий", callback_data="set_format_short"),
            ],
            [
                InlineKeyboardButton("🔄 Спрашивать каждый раз", callback_data="set_format_reset"),
            ],
        ]),
    )


# ─── Статистика ──────────────────────────────────────────────────────────────
async def _show_mystats(message, user_id: int) -> None:
    stats = await db_analytics.get_user_stats(user_id)
    subj = SUBJECT_LABELS.get(stats["favorite_subject"] or "auto", "—")
    avg_sec = stats["avg_response_ms"] / 1000 if stats["avg_response_ms"] else 0
    await message.reply_text(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"📝 Задач решено: {stats['total_queries']}\n"
        f"📚 Любимый предмет: {subj}\n"
        f"⏱ Среднее время: {avg_sec:.1f}с",
        parse_mode=ParseMode.HTML,
    )


# ─── Общая обработка готового ответа ─────────────────────────────────────────
async def process_answer(update, user_id, thinking_msg, answer, cache_hit=False):
    """Сохраняет ответ и рендерит в выбранном формате."""
    answer = sanitize_model_output(answer)
    await db_pending.save_pending(user_id, answer)

    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass

    format_choice = await db_users.get_format_choice(user_id)

    if format_choice == "detailed":
        await _render_detailed(update.message, user_id, answer)
        return
    if format_choice == "short":
        await _render_short(update.message, user_id, answer)
        return

    msg = await update.message.reply_text(
        "✅ Решение готово! Какой формат?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 Подробный", callback_data="show_detailed"),
            InlineKeyboardButton("⚡ Краткий", callback_data="show_short"),
        ]]),
    )
    pending_choice_messages[user_id] = msg.message_id


async def cleanup_qwen_chats():
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, delete_qwen_chats)
    except Exception:
        pass


# ─── Текст ───────────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    question = (update.message.text or "").strip()
    logger.info(f"handle_text: user={user_id}, text={question[:50]!r}")

    # 0. Бан
    if await is_banned(user_id):
        return

    # 1. Кнопки клавиатуры
    if question == BTN_SETTINGS:
        await _show_settings(update.message, user_id)
        return
    if question == BTN_SUBJECT:
        await _show_subject_menu(update.message)
        return
    if question == BTN_STATS:
        await _show_mystats(update.message, user_id)
        return
    if question == BTN_CLEAR:
        await memory.clear(user_id)
        await update.message.reply_text("🗑 История очищена.")
        return
    if question == BTN_FORMAT:
        await _show_format_menu(update.message, user_id)
        return

    # 2. Админ: секретная фраза
    if await try_secret_phrase(update, context):
        return

    # 3. Админ: ожидание ввода
    if is_admin_awaiting_input(user_id):
        if await handle_admin_text_input(update, context):
            return

    # 4. Обновляем пользователя
    await db_users.touch(user_id)

    # 5. Кэш (учитывает предмет)
    subject = await db_users.get_subject(user_id)
    cached = await db_cache.get_cached(question, ttl_hours=CACHE_TTL_HOURS, subject=subject)
    if cached:
        await process_answer(update, user_id, None, cached, cache_hit=True)
        await db_analytics.log_event(user_id, question_type="text", cache_hit=True)
        return

    # 6. Контекст
    history = await memory.get_history(user_id)
    detected_subject = subject
    if subject == "auto":
        detected_subject = detect_subject(question)
    subject_prompt = SUBJECT_PROMPTS.get(detected_subject, "")
    rag_chunks = retriever.search(question, subject=detected_subject)

    # 7. Решаем
    thinking_msg = await update.message.reply_text("⏳ Анализирую задачу...")

    t0 = time.time()
    try:
        loop = asyncio.get_running_loop()

        if rag_chunks:
            try:
                await thinking_msg.edit_text("🔍 Нашёл материал в базе знаний...")
            except Exception:
                pass
            await asyncio.sleep(0.3)

        try:
            await thinking_msg.edit_text("🧠 Решаю задачу...")
        except Exception:
            pass

        # Таймер прогресса — обновляет сообщение каждые 5 сек
        async def _progress_timer():
            elapsed = 5
            while True:
                await asyncio.sleep(5)
                try:
                    await thinking_msg.edit_text(f"🧠 Решаю задачу... ({elapsed}с)")
                except Exception:
                    pass
                elapsed += 5

        timer_task = asyncio.create_task(_progress_timer())

        try:
            answer = await loop.run_in_executor(
                None, ask_qwen_text, question, history, rag_chunks, subject_prompt, detected_subject
            )
        finally:
            timer_task.cancel()

        elapsed_ms = int((time.time() - t0) * 1000)

        try:
            await thinking_msg.edit_text("✅ Проверяю ответ...")
        except Exception:
            pass

        if not answer or len(answer) < 10:
            await thinking_msg.edit_text("❌ Не удалось решить. Попробуй ещё раз.")
            return

        # Сохраняем
        await memory.add_message(user_id, "user", question)
        await memory.add_message(user_id, "assistant", answer[:2000])
        await db_cache.put_cached(question, answer, detected_subject)
        await db_analytics.log_event(
            user_id, question_type="text", subject=detected_subject,
            response_time_ms=elapsed_ms, rag_used=bool(rag_chunks),
            rag_chunks_count=len(rag_chunks),
        )

        await process_answer(update, user_id, thinking_msg, answer)
        await cleanup_qwen_chats()

    except Exception as e:
        logger.error(f"Ошибка (текст): {e}")
        try:
            await thinking_msg.edit_text("❌ Ошибка. Попробуй ещё раз.")
        except Exception:
            pass


# ─── Фото ────────────────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if await is_banned(user_id):
        return
    await db_users.touch(user_id)
    caption = (update.message.caption or "").strip()

    thinking_msg = await update.message.reply_text("📷 Распознаю задание с фото...")

    t0 = time.time()
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = bytes(await photo_file.download_as_bytearray())
        await _solve_image(update, user_id, photo_bytes, caption, thinking_msg, t0, "photo")
    except Exception as e:
        logger.error(f"Ошибка (фото): {e}")
        try:
            await thinking_msg.edit_text("❌ Ошибка. Попробуй ещё раз.")
        except Exception:
            pass


# ─── Документ ────────────────────────────────────────────────────────────────
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if not (doc.mime_type and doc.mime_type.startswith("image/")):
        await update.message.reply_text("📎 Я работаю только с фото и текстом!")
        return

    user_id = update.effective_user.id
    if await is_banned(user_id):
        return
    await db_users.touch(user_id)
    caption = (update.message.caption or "").strip()

    thinking_msg = await update.message.reply_text("📷 Распознаю задание...")

    t0 = time.time()
    try:
        file = await doc.get_file()
        img_bytes = bytes(await file.download_as_bytearray())
        await _solve_image(update, user_id, img_bytes, caption, thinking_msg, t0, "document")
    except Exception as e:
        logger.error(f"Ошибка (документ): {e}")
        try:
            await thinking_msg.edit_text("❌ Ошибка.")
        except Exception:
            pass


async def _solve_image(update, user_id, image_bytes, caption, thinking_msg, t0, q_type):
    """Общая логика решения задачи с фото/документа."""
    try:
        await thinking_msg.edit_text("🧠 Решаю задачу...")
    except Exception:
        pass

    subject = await db_users.get_subject(user_id)
    detected_subject = subject if subject != "auto" else (detect_subject(caption) if caption else "auto")
    subject_prompt = SUBJECT_PROMPTS.get(detected_subject, "")
    rag_chunks = retriever.search(caption, subject=detected_subject) if caption else []

    loop = asyncio.get_running_loop()

    # Таймер прогресса
    async def _progress_timer():
        elapsed = 5
        while True:
            await asyncio.sleep(5)
            try:
                await thinking_msg.edit_text(f"🧠 Решаю задачу... ({elapsed}с)")
            except Exception:
                pass
            elapsed += 5

    timer_task = asyncio.create_task(_progress_timer())

    try:
        answer = await loop.run_in_executor(
            None, ask_qwen_image, image_bytes, caption, subject_prompt, rag_chunks
        )
    finally:
        timer_task.cancel()

    elapsed_ms = int((time.time() - t0) * 1000)

    if not answer or len(answer) < 10:
        await thinking_msg.edit_text("❌ Не удалось распознать. Попробуй ещё раз.")
        return

    await memory.add_message(user_id, "user", f"[{q_type}] {caption}")
    await memory.add_message(user_id, "assistant", answer[:2000])
    await db_analytics.log_event(
        user_id, question_type=q_type, subject=detected_subject,
        response_time_ms=elapsed_ms, rag_used=bool(rag_chunks),
    )
    await process_answer(update, user_id, thinking_msg, answer)
    await cleanup_qwen_chats()


# ─── Подробный рендер ────────────────────────────────────────────────────────
async def _render_detailed(target_msg, user_id: int, answer: str) -> None:
    answer = sanitize_model_output(answer)
    answer = clean_latex_outside_formulas(answer)
    thinking = await target_msg.reply_text("🌐 Готовлю решение...")
    loop = asyncio.get_running_loop()

    # Графики
    try:
        for spec in extract_plot_tasks(answer)[:3]:
            try:
                png = await asyncio.wait_for(
                    loop.run_in_executor(None, plot_function_png, spec["expr"], spec["label"], spec["x_range"], 50.0),
                    timeout=10.0,
                )
                if png:
                    await target_msg.reply_photo(photo=io.BytesIO(png), caption=f"📈 {spec['label']}")
            except Exception:
                pass
    except Exception:
        pass

    title = make_solution_title(answer)

    # Mini App
    mini_app_url = None
    try:
        mini_app_url = await asyncio.wait_for(
            loop.run_in_executor(None, publish_to_mini_app, title, answer, user_id),
            timeout=15.0,
        )
    except Exception:
        pass

    try:
        await thinking.delete()
    except Exception:
        pass

    if mini_app_url:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Открыть в приложении", web_app=WebAppInfo(url=mini_app_url))],
            [InlineKeyboardButton("🌐 Открыть в браузере", url=mini_app_url)],
        ])
        try:
            await target_msg.reply_text("✅ Решение готово!", reply_markup=kb)
        except Exception:
            pass
        return

    # Telegraph
    telegraph_url = None
    try:
        if not TELEGRAPH_TOKEN:
            await loop.run_in_executor(None, init_telegraph)
        telegraph_url = await asyncio.wait_for(
            loop.run_in_executor(None, publish_to_telegraph, title, answer),
            timeout=10.0,
        )
    except Exception:
        pass

    if telegraph_url:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 Открыть решение", url=telegraph_url),
        ]])
        await target_msg.reply_text("✅ Решение готово!", reply_markup=kb)
        return

    # Текст fallback
    for chunk in [answer[i:i+4000] for i in range(0, len(answer), 4000)]:
        try:
            await target_msg.reply_text(chunk)
        except Exception:
            pass


# ─── Краткий рендер ──────────────────────────────────────────────────────────
async def _render_short(target_msg, user_id: int, answer: str) -> None:
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
        llm_short = await loop.run_in_executor(None, llm_extract_short_answers, answer)
        if llm_short:
            short_answer = ("✅ Ответы:\n" + llm_short) if "\n" in llm_short else f"✅ Ответ: {llm_short}"

    if not short_answer:
        last_line = next((ln.strip() for ln in reversed(answer.splitlines()) if ln.strip()), "")
        last_line = pretty_short(last_line)
        short_answer = f"✅ Ответ: {last_line}" if last_line else "⚠️ Не удалось выделить ответ."

    short_answer = re.sub(r"\n{3,}", "\n\n", short_answer).strip()
    lines = [ln for ln in short_answer.splitlines() if ln.strip()]
    quoted = "\n".join(html.escape(ln) for ln in lines)
    pretty = (
        f"<b>✅ Ответ готов</b>\n"
        f"<blockquote>{quoted}</blockquote>\n"
        f"<i>✏️ Проверяй ответы самостоятельно</i>"
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📖 Посмотреть подробно", callback_data="show_detailed"),
    ]])

    try:
        await target_msg.reply_text(pretty, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        for chunk in [short_answer[i:i+4000] for i in range(0, len(short_answer), 4000)]:
            await target_msg.reply_text(chunk)


# ─── Callbacks ───────────────────────────────────────────────────────────────
async def show_detailed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass
    answer = await db_pending.get_pending(user_id)
    if not answer:
        try:
            await query.message.reply_text("⚠️ Ответ не найден. Отправь задание заново.")
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


async def show_short_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass
    answer = await db_pending.get_pending(user_id)
    if not answer:
        try:
            await query.message.reply_text("⚠️ Ответ не найден. Отправь задание заново.")
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
