"""
Обработчики админ-панели: секретная фраза, пароль, меню, callbacks.
"""
import html
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.config import (
    ADMIN_IDS,
    ADMIN_PASSWORD,
    ADMIN_SECRET_PHRASE,
    CACHE_TTL_HOURS,
    KNOWLEDGE_BASE_PATH,
    logger,
)
from src.db import analytics as db_analytics
from src.db import cache as db_cache
from src.db import users as db_users

from .ban import get_ban_status, toggle_ban
from .broadcast import broadcast_message

# Состояния админ-сессии
STATE_NONE = "none"
STATE_AWAITING_PASSWORD = "awaiting_password"
STATE_ACTIVE = "active"
STATE_AWAITING_BROADCAST = "awaiting_broadcast"
STATE_AWAITING_BAN_ID = "awaiting_ban_id"

# {user_id: {"state": str, "last_active": datetime, "attempts": int, "locked_until": datetime|None}}
_admin_sessions: dict[int, dict] = {}

SESSION_TIMEOUT_MINUTES = 10
MAX_ATTEMPTS = 3
LOCKOUT_MINUTES_SHORT = 5
LOCKOUT_MINUTES_LONG = 60


def _get_session(user_id: int) -> dict:
    if user_id not in _admin_sessions:
        _admin_sessions[user_id] = {
            "state": STATE_NONE,
            "last_active": None,
            "attempts": 0,
            "locked_until": None,
        }
    return _admin_sessions[user_id]


def _is_locked(user_id: int) -> bool:
    session = _get_session(user_id)
    if session["locked_until"] and datetime.now() < session["locked_until"]:
        return True
    return False


def _is_session_expired(user_id: int) -> bool:
    session = _get_session(user_id)
    if not session["last_active"]:
        return True
    return datetime.now() - session["last_active"] > timedelta(minutes=SESSION_TIMEOUT_MINUTES)


def is_admin_awaiting_input(user_id: int) -> bool:
    """Проверяет, ожидает ли админ-сессия ввода (пароль, текст рассылки, ban id)."""
    if user_id not in _admin_sessions:
        return False
    session = _admin_sessions[user_id]
    return session["state"] in (
        STATE_AWAITING_PASSWORD,
        STATE_AWAITING_BROADCAST,
        STATE_AWAITING_BAN_ID,
    )


async def try_secret_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, является ли сообщение секретной фразой."""
    text = (update.message.text or "").strip().lower()
    if text != ADMIN_SECRET_PHRASE.lower():
        return False

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return False

    if _is_locked(user_id):
        return True

    # Удаляем сообщение с фразой
    try:
        await update.message.delete()
    except Exception:
        pass

    session = _get_session(user_id)
    session["state"] = STATE_AWAITING_PASSWORD
    session["last_active"] = datetime.now()

    await update.effective_chat.send_message("🔐 Введите пароль:")
    return True


async def handle_admin_text_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Обрабатывает текстовый ввод в контексте админ-сессии.

    Возвращает True если обработано.
    """
    user_id = update.effective_user.id
    if user_id not in _admin_sessions:
        return False

    session = _admin_sessions[user_id]
    state = session["state"]

    if state == STATE_AWAITING_PASSWORD:
        return await _handle_password(update, context)
    elif state == STATE_AWAITING_BROADCAST:
        return await _handle_broadcast_input(update, context)
    elif state == STATE_AWAITING_BAN_ID:
        return await _handle_ban_input(update, context)

    return False


async def _handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет пароль."""
    user_id = update.effective_user.id
    password = update.message.text or ""
    session = _get_session(user_id)

    # Удаляем сообщение с паролем
    try:
        await update.message.delete()
    except Exception:
        pass

    # Удаляем сообщение «Введите пароль»
    # (это последнее сообщение бота перед паролем)
    try:
        # Ищем и удаляем предыдущее сообщение бота
        pass  # Telegram не даёт удалить чужие сообщения в ЛС без ID
    except Exception:
        pass

    if password == ADMIN_PASSWORD:
        session["state"] = STATE_ACTIVE
        session["attempts"] = 0
        session["last_active"] = datetime.now()
        logger.info(f"Admin login: user_id={user_id}")
        await _show_admin_menu(update, context)
    else:
        session["attempts"] += 1
        attempts = session["attempts"]

        if attempts >= MAX_ATTEMPTS:
            session["locked_until"] = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES_LONG)
            session["state"] = STATE_NONE
            await update.effective_chat.send_message("❌ Слишком много попыток. Заблокировано на 1 час.")
            logger.warning(f"Admin lockout: user_id={user_id}, attempts={attempts}")
        else:
            remaining = MAX_ATTEMPTS - attempts
            session["locked_until"] = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES_SHORT)
            session["state"] = STATE_NONE
            await update.effective_chat.send_message(f"❌ Неверный пароль. Осталось попыток: {remaining}")

    return True


async def _show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает админ-меню (новое сообщение)."""
    kb = _admin_menu_keyboard()
    await update.effective_chat.send_message(
        "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def _show_admin_menu_edit(query, context) -> None:
    """Возвращает в админ-меню (редактирует текущее сообщение)."""
    kb = _admin_menu_keyboard()
    try:
        await query.message.edit_text(
            "🔐 <b>Админ-панель</b>\n\nВыберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    except Exception:
        pass


def _admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton("🔄 Реиндекс", callback_data="admin_reindex"),
        ],
        [
            InlineKeyboardButton("🗑 Очистить кэш", callback_data="admin_clearcache"),
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
            InlineKeyboardButton("🚫 Бан", callback_data="admin_ban"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="admin_config"),
            InlineKeyboardButton("❌ Закрыть", callback_data="admin_close"),
        ],
    ])


async def handle_admin_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Обрабатывает нажатия кнопок админ-панели."""
    query = update.callback_query
    user_id = query.from_user.id

    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа")
        return

    session = _get_session(user_id)
    if session["state"] != STATE_ACTIVE or _is_session_expired(user_id):
        await query.answer("⏰ Сессия истекла. Введите фразу заново.")
        try:
            await query.message.delete()
        except Exception:
            pass
        session["state"] = STATE_NONE
        return

    session["last_active"] = datetime.now()

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data or ""

    if data == "admin_stats":
        await _show_stats(query, context)
    elif data == "admin_reindex":
        await _do_reindex(query, context)
    elif data == "admin_clearcache":
        await _do_clearcache(query, context)
    elif data == "admin_users":
        await _show_users(query, context)
    elif data == "admin_broadcast":
        session["state"] = STATE_AWAITING_BROADCAST
        cancel_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Отмена", callback_data="admin_back"),
        ]])
        await query.message.edit_text("📢 Введите текст для рассылки:", reply_markup=cancel_kb)
    elif data == "admin_ban":
        session["state"] = STATE_AWAITING_BAN_ID
        cancel_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Отмена", callback_data="admin_back"),
        ]])
        await query.message.edit_text("🚫 Введите user_id для бана/разбана:", reply_markup=cancel_kb)
    elif data == "admin_config":
        await _show_config(query, context)
    elif data == "admin_back":
        session["state"] = STATE_ACTIVE
        await _show_admin_menu_edit(query, context)
    elif data == "admin_close":
        session["state"] = STATE_NONE
        try:
            await query.message.delete()
        except Exception:
            pass


async def _show_stats(query, context) -> None:
    """Показывает статистику."""
    stats_24h = await db_analytics.get_stats("24h")
    stats_7d = await db_analytics.get_stats("7d")
    stats_all = await db_analytics.get_stats("all")

    def _fmt(s: dict) -> str:
        subjects = ", ".join(f"{subj}({cnt})" for subj, cnt in s["top_subjects"]) or "—"
        return (
            f"  Запросов: {s['total_queries']}\n"
            f"  Пользователей: {s['unique_users']}\n"
            f"  Ср. время: {s['avg_response_ms']}мс\n"
            f"  Cache hit: {s['cache_hit_rate']}%\n"
            f"  RAG запросов: {s['rag_queries']}\n"
            f"  Исправлений: {s['verifier_corrections']}\n"
            f"  Топ предметы: {subjects}"
        )

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"<b>За 24 часа:</b>\n{_fmt(stats_24h)}\n\n"
        f"<b>За 7 дней:</b>\n{_fmt(stats_7d)}\n\n"
        f"<b>Всё время:</b>\n{_fmt(stats_all)}"
    )
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="admin_back"),
    ]])
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)
    except Exception:
        await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)


async def _do_reindex(query, context) -> None:
    """Переиндексирует базу знаний."""
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="admin_back"),
    ]])
    try:
        await query.message.edit_text("🔄 Переиндексация...", reply_markup=None)
    except Exception:
        pass
    try:
        from src.rag.indexer import KnowledgeIndexer

        indexer = KnowledgeIndexer(KNOWLEDGE_BASE_PATH)
        stats = indexer.index_all()
        await db_cache.clear_all()
        try:
            await query.message.edit_text(
                f"✅ Переиндексация завершена!\n"
                f"📁 Файлов: {stats['files']}\n"
                f"📄 Чанков: {stats['chunks']}\n"
                f"🗑 Кэш очищен.",
                reply_markup=back_kb,
            )
        except Exception:
            await query.message.reply_text(
                f"✅ Переиндексация завершена!\n"
                f"📁 Файлов: {stats['files']}\n"
                f"📄 Чанков: {stats['chunks']}\n"
                f"🗑 Кэш очищен.",
                reply_markup=back_kb,
            )
    except Exception as e:
        try:
            await query.message.edit_text(f"❌ Ошибка: {e}", reply_markup=back_kb)
        except Exception:
            await query.message.reply_text(f"❌ Ошибка: {e}", reply_markup=back_kb)


async def _do_clearcache(query, context) -> None:
    """Очищает кэш."""
    count = await db_cache.clear_all()
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="admin_back"),
    ]])
    try:
        await query.message.edit_text(f"🗑 Кэш очищен. Удалено записей: {count}", reply_markup=back_kb)
    except Exception:
        await query.message.reply_text(f"🗑 Кэш очищен. Удалено записей: {count}", reply_markup=back_kb)


async def _show_users(query, context) -> None:
    """Показывает последних активных пользователей."""
    users = await db_users.get_recent_users(20)
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="admin_back"),
    ]])
    if not users:
        try:
            await query.message.edit_text("👥 Пользователей пока нет.", reply_markup=back_kb)
        except Exception:
            pass
        return

    lines = ["👥 <b>Последние активные:</b>\n"]
    for u in users:
        ban_status = await get_ban_status(u["user_id"])
        ban_mark = " 🚫" if ban_status else ""
        lines.append(
            f"• <code>{u['user_id']}</code>{ban_mark} "
            f"| {u['subject'] or 'auto'} | {u['last_active_at'] or '?'}"
        )

    try:
        await query.message.edit_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb)
    except Exception:
        await query.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb)


async def _show_config(query, context) -> None:
    """Показывает текущие настройки (без секретов)."""
    from src.config import (
        CACHE_TTL_HOURS,
        HISTORY_TIMEOUT_MINUTES,
        MAX_HISTORY_MESSAGES,
        TEXT_MODEL,
        VERIFIER_MODEL,
        VISION_MODEL,
    )

    cache_size = await db_cache.get_cache_size()

    text = (
        "⚙️ <b>Текущие настройки</b>\n\n"
        f"📝 TEXT_MODEL: <code>{TEXT_MODEL}</code>\n"
        f"🔍 VERIFIER_MODEL: <code>{VERIFIER_MODEL}</code>\n"
        f"📷 VISION_MODEL: <code>{VISION_MODEL}</code>\n"
        f"💬 История: {MAX_HISTORY_MESSAGES} сообщений, таймаут {HISTORY_TIMEOUT_MINUTES} мин\n"
        f"⚡ Кэш TTL: {CACHE_TTL_HOURS}ч, записей: {cache_size}\n"
        f"📁 База знаний: <code>{html.escape(KNOWLEDGE_BASE_PATH)}</code>\n"
        f"👤 Админов: {len(ADMIN_IDS)}"
    )
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="admin_back"),
    ]])
    try:
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)
    except Exception:
        await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)


async def _handle_broadcast_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Обрабатывает текст рассылки."""
    user_id = update.effective_user.id
    text = update.message.text or ""
    session = _get_session(user_id)
    session["state"] = STATE_ACTIVE
    session["last_active"] = datetime.now()

    if not text.strip():
        await update.message.reply_text("❌ Пустое сообщение. Рассылка отменена.")
        return True

    await update.message.reply_text("📢 Рассылка начата...")
    sent, errors = await broadcast_message(context.bot, text)
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад в меню", callback_data="admin_back"),
    ]])
    await update.message.reply_text(
        f"📢 Рассылка завершена!\n✅ Отправлено: {sent}\n❌ Ошибок: {errors}",
        reply_markup=back_kb,
    )

    # Логируем
    await db_analytics.log_event(user_id, action_type="admin_broadcast")
    return True


async def _handle_ban_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Обрабатывает ввод user_id для бана."""
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    session = _get_session(user_id)
    session["state"] = STATE_ACTIVE
    session["last_active"] = datetime.now()

    if not text.isdigit():
        await update.message.reply_text("❌ Некорректный user_id. Введите число.")
        return True

    target_id = int(text)
    result = await toggle_ban(target_id, banned_by=user_id)
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад в меню", callback_data="admin_back"),
    ]])
    await update.message.reply_text(result, reply_markup=back_kb)

    await db_analytics.log_event(user_id, action_type="admin_ban")
    return True
