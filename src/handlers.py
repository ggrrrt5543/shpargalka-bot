"""
Telegram message handlers.

Обработчики команд / сообщений / коллбеков с интеграцией:
- RAG (поиск по базе знаний)
- Память диалога (контекст беседы)
- Кэширование ответов
- Предметные режимы
- Аналитика
- Админ-панель
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
    pending_answers,
    pending_choice_messages,
)
from .db import analytics as db_analytics
from .db import cache as db_cache
from .db import conversations as db_conv
from .db import users as db_users
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

# ─── Инициализация подсистем ─────────────────────────────────────────────────
memory = ConversationMemory(
    max_messages=MAX_HISTORY_MESSAGES,
    timeout_minutes=HISTORY_TIMEOUT_MINUTES,
)
retriever = KnowledgeRetriever()

# ─── Постоянная клавиатура ───────────────────────────────────────────────────
SETTINGS_BTN = "⚙ Настройки"
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(SETTINGS_BTN)]],
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
        "⚙ В настройках можно выбрать формат и предмет.\n"
        "💬 Я помню контекст — можешь уточнять вопросы!\n\n"
        "Команды:\n"
        "/clear — очистить историю диалога\n"
        "/subject — выбрать предмет\n"
        "/mystats — твоя статистика",
        reply_markup=MAIN_KEYBOARD,
    )


# ─── /clear ──────────────────────────────────────────────────────────────────
async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await memory.clear(user_id)
    await update.message.reply_text("🗑 История очищена. Начинаем с чистого листа.")


# ─── /subject ────────────────────────────────────────────────────────────────
async def handle_subject_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _show_subject_menu(update.message)


async def _show_subject_menu(target_msg) -> None:
    """Показывает меню выбора предмета."""
    buttons = []
    row = []
    for key, label in SUBJECT_LABELS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"set_subject_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await target_msg.reply_text(
        "📚 Выбери предмет — бот будет использовать специализированный промпт:",
        reply_markup=InlineKeyboardMarkup(buttons),
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
        await query.edit_message_text(f"✅ Предмет: <b>{html.escape(label)}</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ─── /mystats ────────────────────────────────────────────────────────────────
async def handle_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    stats = await db_analytics.get_user_stats(user_id)
    subj = SUBJECT_LABELS.get(stats["favorite_subject"] or "auto", "—")
    avg_sec = stats["avg_response_ms"] / 1000 if stats["avg_response_ms"] else 0
    await update.message.reply_text(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"📝 Задач решено: {stats['total_queries']}\n"
        f"📚 Любимый предмет: {subj}\n"
        f"⏱ Среднее время: {avg_sec:.1f}с",
        parse_mode=ParseMode.HTML,
    )


# ─── Меню «⚙ Настройки» ──────────────────────────────────────────────────────
async def handle_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    format_choice = await db_users.get_format_choice(user_id)
    subject = await db_users.get_subject(user_id)

    format_label = {
        "detailed": "📖 Подробный",
        "short": "⚡ Краткий",
    }.get(format_choice, "❓ спрашиваю каждый раз")

    subject_label = SUBJECT_LABELS.get(subject, "🤖 Авто")

    await update.message.reply_text(
        f"⚙ <b>Настройки</b>\n\n"
        f"Формат: <i>{html.escape(format_label)}</i>\n"
        f"Предмет: <i>{html.escape(subject_label)}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
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
        ]),
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
        text = "✅ Формат: <b>📖 Подробный</b>"
    elif data == "set_format_short":
        await db_users.set_format_choice(user_id, "short")
        text = "✅ Формат: <b>⚡ Краткий</b>"
    elif data == "show_subjects":
        await _show_subject_menu(query.message)
        return
    else:
        await db_users.set_format_choice(user_id, None)
        text = "🔄 Сброшено — буду спрашивать каждый раз."

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ─── Общая обработка готового ответа ─────────────────────────────────────────
async def process_answer(
    update,
    user_id: int,
    thinking_msg,
    answer: str,
    cache_hit: bool = False,
) -> None:
    """Сохраняет ответ и рендерит в выбранном формате."""
    answer = sanitize_model_output(answer)
    pending_answers[user_id] = answer

    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass

    # Метка кэша
    if cache_hit:
        answer_display = answer
    else:
        answer_display = answer

    format_choice = await db_users.get_format_choice(user_id)

    if format_choice == "detailed":
        await _render_detailed(update.message, user_id, answer_display)
        return
    if format_choice == "short":
        await _render_short(update.message, user_id, answer_display)
        return

    msg = await update.message.reply_text(
        "✅ Решение готово! Какой формат?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 Подробный", callback_data="show_detailed"),
            InlineKeyboardButton("⚡ Краткий", callback_data="show_short"),
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
    logger.info(f"handle_text: user={user_id}, text={question[:50]!r}")

    # 0. Проверка бана
    if await is_banned(user_id):
        return

    # 1. Кнопка настроек
    if question.strip() == SETTINGS_BTN:
        await handle_settings(update, context)
        return

    # 2. Админ: секретная фраза
    if await try_secret_phrase(update, context):
        return

    # 3. Админ: ожидание ввода (пароль, рассылка, бан)
    if is_admin_awaiting_input(user_id):
        if await handle_admin_text_input(update, context):
            return

    # 4. Обновляем пользователя
    await db_users.touch(user_id)

    # 5. Проверяем кэш
    cached = await db_cache.get_cached(question, ttl_hours=CACHE_TTL_HOURS)
    if cached:
        await process_answer(update, user_id, None, cached, cache_hit=True)
        await db_analytics.log_event(
            user_id, question_type="text", cache_hit=True
        )
        return

    # 6. Получаем контекст
    subject = await db_users.get_subject(user_id)
    history = await memory.get_history(user_id)

    # Автоопределение предмета если 'auto'
    detected_subject = subject
    if subject == "auto":
        detected_subject = detect_subject(question)

    subject_prompt = SUBJECT_PROMPTS.get(detected_subject, "")

    # RAG поиск
    rag_chunks = retriever.search(question, subject=detected_subject)

    # 7. Решаем с прогресс-баром (в фоновой задаче чтобы не блокировать бота)
    progress_steps = [
        "⏳ Анализирую задачу...\n▓░░░░░░░░░",
        "🔍 Ищу в базе знаний...\n▓▓▓░░░░░░░",
        "🧠 Решаю...\n▓▓▓▓▓░░░░░",
        "✍️ Оформляю ответ...\n▓▓▓▓▓▓▓░░░",
        "✅ Проверяю...\n▓▓▓▓▓▓▓▓▓░",
    ]
    thinking_msg = await update.message.reply_text(progress_steps[0])

    async def _update_progress(step: int):
        if step < len(progress_steps):
            try:
                await thinking_msg.edit_text(progress_steps[step])
            except Exception:
                pass

    await _update_progress(1 if rag_chunks else 2)

    t0 = time.time()
    try:
        loop = asyncio.get_running_loop()

        # Обновляем прогресс перед запуском LLM
        await _update_progress(2)

        answer = await loop.run_in_executor(
            None, ask_qwen_text, question, history, rag_chunks, subject_prompt, detected_subject
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        await _update_progress(4)

        if not answer or len(answer) < 10:
            await thinking_msg.edit_text(
                "❌ Не удалось решить задачу. Попробуй ещё раз."
            )
            return

        # 8. Сохраняем в память и кэш
        await memory.add_message(user_id, "user", question)
        await memory.add_message(user_id, "assistant", answer[:2000])
        await db_cache.put_cached(question, answer, detected_subject)

        # 9. Аналитика
        await db_analytics.log_event(
            user_id,
            question_type="text",
            subject=detected_subject,
            response_time_ms=elapsed_ms,
            cache_hit=False,
            rag_used=bool(rag_chunks),
            rag_chunks_count=len(rag_chunks),
        )

        # 10. Отдаём ответ
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

    if await is_banned(user_id):
        return

    await db_users.touch(user_id)
    caption = (update.message.caption or "").strip()

    thinking_msg = await update.message.reply_text(
        "📷 Читаю задание с фото...\n▓▓░░░░░░░░" if not caption
        else "📷 Читаю фото + сообщение...\n▓▓░░░░░░░░"
    )

    t0 = time.time()
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = bytes(await photo_file.download_as_bytearray())

        try:
            await thinking_msg.edit_text("🧠 Решаю задачу...\n▓▓▓▓▓░░░░░")
        except Exception:
            pass

        # Контекст
        subject = await db_users.get_subject(user_id)
        detected_subject = subject
        if subject == "auto" and caption:
            detected_subject = detect_subject(caption)
        subject_prompt = SUBJECT_PROMPTS.get(detected_subject, "")

        # RAG по caption
        rag_chunks = []
        if caption:
            rag_chunks = retriever.search(caption, subject=detected_subject)

        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(
            None, ask_qwen_image, photo_bytes, caption, subject_prompt, rag_chunks
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        if not answer or len(answer) < 10:
            await thinking_msg.edit_text(
                "❌ Не удалось распознать задание. Попробуй ещё раз."
            )
            return

        # Память
        await memory.add_message(user_id, "user", f"[фото] {caption}")
        await memory.add_message(user_id, "assistant", answer[:2000])

        # Аналитика
        await db_analytics.log_event(
            user_id,
            question_type="photo",
            subject=detected_subject,
            response_time_ms=elapsed_ms,
            rag_used=bool(rag_chunks),
            rag_chunks_count=len(rag_chunks),
        )

        await process_answer(update, user_id, thinking_msg, answer)
        await cleanup_qwen_chats()

    except Exception as e:
        logger.error(f"Ошибка (фото): {e}")
        try:
            await thinking_msg.edit_text("❌ Ошибка при обработке фото. Попробуй ещё раз.")
        except Exception:
            pass


# ─── Документ ────────────────────────────────────────────────────────────────
async def handle_document(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image/"):
        user_id = update.effective_user.id

        if await is_banned(user_id):
            return

        await db_users.touch(user_id)
        caption = (update.message.caption or "").strip()

        thinking_msg = await update.message.reply_text(
            "📷 Читаю задание с фото..." if not caption
            else "📷 Читаю задание с фото и учитываю сообщение..."
        )

        t0 = time.time()
        try:
            file = await doc.get_file()
            img_bytes = bytes(await file.download_as_bytearray())

            subject = await db_users.get_subject(user_id)
            detected_subject = subject
            if subject == "auto" and caption:
                detected_subject = detect_subject(caption)
            subject_prompt = SUBJECT_PROMPTS.get(detected_subject, "")

            rag_chunks = []
            if caption:
                rag_chunks = retriever.search(caption, subject=detected_subject)

            loop = asyncio.get_running_loop()
            answer = await loop.run_in_executor(
                None, ask_qwen_image, img_bytes, caption, subject_prompt, rag_chunks
            )
            elapsed_ms = int((time.time() - t0) * 1000)

            if not answer or len(answer) < 10:
                await thinking_msg.edit_text("❌ Не удалось распознать задание.")
                return

            await memory.add_message(user_id, "user", f"[документ] {caption}")
            await memory.add_message(user_id, "assistant", answer[:2000])

            await db_analytics.log_event(
                user_id,
                question_type="document",
                subject=detected_subject,
                response_time_ms=elapsed_ms,
                rag_used=bool(rag_chunks),
                rag_chunks_count=len(rag_chunks),
            )

            await process_answer(update, user_id, thinking_msg, answer)
            await cleanup_qwen_chats()

        except Exception as e:
            logger.error(f"Ошибка (документ): {e}")
            try:
                await thinking_msg.edit_text("❌ Ошибка при обработке документа.")
            except Exception:
                pass
    else:
        await update.message.reply_text("📎 Я работаю только с фото и текстом!")


# ─── Подробный рендер ────────────────────────────────────────────────────────
async def _render_detailed(target_msg, user_id: int, answer: str) -> None:
    """Публикует подробное решение: Mini App → Telegraph → текст (fallback)."""
    answer = sanitize_model_output(answer)
    answer = clean_latex_outside_formulas(answer)
    thinking = await target_msg.reply_text("🌐 Готовлю решение...")
    loop = asyncio.get_running_loop()

    # Графики — только PNG в чат
    try:
        plot_specs = extract_plot_tasks(answer)
        for spec in plot_specs[:3]:  # максимум 3 графика
            try:
                png = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, plot_function_png, spec["expr"], spec["label"], spec["x_range"], 50.0
                    ),
                    timeout=10.0,
                )
                if png:
                    await target_msg.reply_photo(photo=io.BytesIO(png), caption=f"📈 {spec['label']}")
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"График пропущен: {e}")
    except Exception:
        pass

    title = make_solution_title(answer)

    # Mini App (с таймаутом)
    mini_app_url = None
    try:
        mini_app_url = await asyncio.wait_for(
            loop.run_in_executor(None, publish_to_mini_app, title, answer, user_id),
            timeout=15.0,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Mini App недоступен: {e}")

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

    # Telegraph fallback (с таймаутом)
    telegraph_url = None
    try:
        if not TELEGRAPH_TOKEN:
            await loop.run_in_executor(None, init_telegraph)
        telegraph_url = await asyncio.wait_for(
            loop.run_in_executor(None, publish_to_telegraph, title, answer),
            timeout=10.0,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Telegraph недоступен: {e}")

    if telegraph_url:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 Открыть решение", url=telegraph_url),
        ]])
        await target_msg.reply_text("✅ Решение готово!", reply_markup=kb)
        return

    # Текстовый fallback — всегда работает
    for chunk in [answer[i:i+4000] for i in range(0, len(answer), 4000)]:
        try:
            await target_msg.reply_text(chunk)
        except Exception:
            pass

    await target_msg.reply_text("📚 Отправь новое задание!")


# ─── Краткий рендер ──────────────────────────────────────────────────────────
def _short_to_html_blockquote(short_answer: str) -> str:
    s = (short_answer or "").strip()
    if not s:
        s = "Не удалось выделить ответ."
    lines = [ln for ln in s.splitlines() if ln.strip()]
    quoted = "\n".join(html.escape(ln) for ln in lines)
    return (
        f"<b>✅ Ответ готов</b>\n"
        f"<blockquote>{quoted}</blockquote>\n"
        f"<i>✏️ Проверяй ответы самостоятельно</i>"
    )


async def _render_short(target_msg, user_id: int, answer: str) -> None:
    """Только финальные ответы + кнопка «Подробнее»."""
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
        last_line = next(
            (ln.strip() for ln in reversed(answer.splitlines()) if ln.strip()), ""
        )
        last_line = pretty_short(last_line)
        short_answer = f"✅ Ответ: {last_line}" if last_line else "⚠️ Не удалось выделить ответ."

    short_answer = re.sub(r"\n{3,}", "\n\n", short_answer).strip()
    pretty = _short_to_html_blockquote(short_answer)

    # Кнопка «Подробнее» — переключает на подробный формат
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📖 Посмотреть подробно", callback_data="show_detailed"),
    ]])

    try:
        await target_msg.reply_text(pretty, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        for chunk in [short_answer[i:i+4000] for i in range(0, len(short_answer), 4000)]:
            await target_msg.reply_text(chunk)


# ─── Callbacks ───────────────────────────────────────────────────────────────
async def show_detailed_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass
    answer = pending_answers.get(user_id)
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


async def show_short_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass
    answer = pending_answers.get(user_id)
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
