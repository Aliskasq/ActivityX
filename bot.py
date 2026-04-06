"""Telegram bot with commands for managing Twitter monitor."""
import json
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from config import (
    ADMIN_IDS, COOKIES_PATH, get_api_key, set_api_key, get_model, set_model,
    get_schedule_mode, get_schedule_times, get_interval_min,
    set_schedule_times, set_interval_mode,
)
from scraper import _normalize_cookies
import database as db

logger = logging.getLogger(__name__)

WAITING_TAG = 1
WAITING_EXCLUSION = 2
WAITING_COOKIES = 3


def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


# --- Commands ---

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🐦 **Twitter Monitor Bot**\n\n"
        "**Аккаунты:**\n"
        "/add `@username` — добавить\n"
        "/remove `@username` — удалить\n"
        "/list — список с тегами\n"
        "/pages — управление тегами (кнопки)\n\n"
        "**Настройки:**\n"
        "/cookies — загрузить куки Twitter\n"
        "/listid `ID` — установить ID списка Twitter\n"
        "/key `ключ` — сменить OpenRouter API ключ\n"
        "/models — список моделей / сменить\n"
        "/time `18:05 20:49` — расписание скана (МСК)\n"
        "/time30 — сканить каждые 30 мин\n"
        "/status — статус",
        parse_mode="Markdown",
    )


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("Использование: /add @username")
    username = ctx.args[0].lstrip("@").lower()
    if db.add_account(username):
        await update.message.reply_text(f"✅ @{username} добавлен")
    else:
        await update.message.reply_text(f"⚠️ @{username} уже есть")


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        return await update.message.reply_text("Использование: /remove @username")
    username = ctx.args[0].lstrip("@").lower()
    if db.remove_account(username):
        await update.message.reply_text(f"🗑 @{username} удалён")
    else:
        await update.message.reply_text(f"⚠️ @{username} не найден")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Список пуст. /add @username")
    text = "📋 **Аккаунты:**\n\n"
    for i, acc in enumerate(accounts, 1):
        tags = db.list_account_keywords(acc)
        excl = db.list_account_exclusions(acc)
        tag_str = ", ".join(tags) if tags else "—"
        line = f"{i}. @{acc} — {tag_str}"
        if excl:
            line += f"\n   🚫 {', '.join(excl)}"
        text += line + "\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# --- Cookies ---

async def cmd_cookies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if ctx.args:
        # Inline JSON
        try:
            cookie_text = " ".join(ctx.args)
            json.loads(cookie_text)
            with open(COOKIES_PATH, "w") as f:
                f.write(cookie_text)
            from scraper import reset_client
            reset_client()
            return await update.message.reply_text("✅ Куки сохранены! Перезапуск клиента.")
        except json.JSONDecodeError:
            return await update.message.reply_text("❌ Невалидный JSON")

    has_cookies = os.path.exists(COOKIES_PATH)
    status = "✅ Загружены" if has_cookies else "❌ Не загружены"
    await update.message.reply_text(
        f"🍪 **Куки Twitter:** {status}\n\n"
        f"Отправь JSON куки следующим сообщением:\n"
        f"1. Установи расширение Cookie-Editor\n"
        f"2. Зайди на x.com\n"
        f"3. Экспортируй куки (JSON)\n"
        f"4. Отправь сюда как сообщение",
        parse_mode="Markdown",
    )
    ctx.user_data["waiting_cookies"] = True
    return WAITING_COOKIES


async def receive_cookies_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle cookie file upload (document)."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    try:
        file = await update.message.document.get_file()
        await file.download_to_drive(COOKIES_PATH)
        # Validate JSON
        with open(COOKIES_PATH) as f:
            json.loads(f.read())
        _normalize_cookies(COOKIES_PATH)
        ctx.user_data.pop("waiting_cookies", None)
        from scraper import reset_client
        reset_client()
        await update.message.reply_text("✅ Куки сохранены! Клиент перезапущен.")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Файл не содержит валидный JSON. Попробуй ещё раз.")
        return WAITING_COOKIES
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return WAITING_COOKIES
    return ConversationHandler.END


async def receive_cookies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle cookie text message."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("❌ Пустое сообщение. Отправь JSON или файл.")
        return WAITING_COOKIES
    try:
        json.loads(text)
        with open(COOKIES_PATH, "w") as f:
            f.write(text)
        _normalize_cookies(COOKIES_PATH)
        ctx.user_data.pop("waiting_cookies", None)
        from scraper import reset_client
        reset_client()
        await update.message.reply_text("✅ Куки сохранены! Клиент перезапущен.")
        return ConversationHandler.END
    except json.JSONDecodeError:
        await update.message.reply_text("❌ Это не JSON. Отправь экспорт куки или /cancel")
        return WAITING_COOKIES


# --- List ID ---

async def cmd_listid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        from config import TWITTER_LIST_ID
        current = TWITTER_LIST_ID or "не установлен"
        return await update.message.reply_text(
            f"📋 **List ID:** `{current}`\n\nУстановить: /listid 1234567890",
            parse_mode="Markdown",
        )
    list_id = ctx.args[0].strip()
    # Save to .env
    from config import _save_env
    _save_env("TWITTER_LIST_ID", list_id)
    # Update runtime — no restart needed
    import config
    import monitor
    config.TWITTER_LIST_ID = list_id
    monitor.TWITTER_LIST_ID = list_id
    await update.message.reply_text(f"✅ List ID: `{list_id}` — применён!", parse_mode="Markdown")


# --- Key management ---

async def cmd_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        current = get_api_key()
        masked = current[:10] + "..." + current[-4:] if len(current) > 14 else "не установлен"
        return await update.message.reply_text(f"🔑 Ключ: `{masked}`\n\nСменить: /key новый\\_ключ", parse_mode="Markdown")
    set_api_key(ctx.args[0].strip())
    await update.message.reply_text("✅ API ключ обновлён")


# --- Models ---

AVAILABLE_MODELS = [
    "stepfun/step-2-16k",
    "stepfun/step-1-8k",
    "google/gemma-2-9b-it:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2-7b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-7b-instruct:free",
]


async def cmd_models(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if ctx.args:
        model_name = " ".join(ctx.args).strip()
        set_model(model_name)
        return await update.message.reply_text(f"✅ Модель: `{model_name}`", parse_mode="Markdown")

    current = get_model()
    text = f"🤖 **Модель:** `{current}`\n\n"
    for i, m in enumerate(AVAILABLE_MODELS, 1):
        marker = "👉 " if m == current else ""
        text += f"{i}. {marker}`{m}`\n"
    text += f"\nСменить: /models `название`"
    await update.message.reply_text(text, parse_mode="Markdown")


# --- Pages ---

async def cmd_pages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("Нет аккаунтов. /add @username")
    await update.message.reply_text(
        "📄 **Выбери аккаунт:**",
        reply_markup=build_pages_keyboard(accounts),
        parse_mode="Markdown",
    )


def build_pages_keyboard(accounts: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for acc in accounts:
        tc = len(db.list_account_keywords(acc))
        ec = len(db.list_account_exclusions(acc))
        row.append(InlineKeyboardButton(f"@{acc} ({tc}t/{ec}x)", callback_data=f"page:{acc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def callback_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_account_tags(query, query.data.split(":", 1)[1])


async def show_account_tags(query, username: str):
    tags = db.list_account_keywords(username)
    exclusions = db.list_account_exclusions(username)
    buttons = []
    for tag in tags:
        buttons.append([
            InlineKeyboardButton(f"🏷 {tag}", callback_data=f"noop:{username}"),
            InlineKeyboardButton("❌", callback_data=f"deltag:{username}:{tag}"),
        ])
    for ex in exclusions:
        buttons.append([
            InlineKeyboardButton(f"🚫 {ex}", callback_data=f"noop:{username}"),
            InlineKeyboardButton("❌", callback_data=f"delexcl:{username}:{ex}"),
        ])
    buttons.append([
        InlineKeyboardButton("➕ Тег", callback_data=f"addtag:{username}"),
        InlineKeyboardButton("➕ Исключение", callback_data=f"addexcl:{username}"),
    ])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:pages")])

    tag_text = "\n".join(f"  🏷 {t}" for t in tags) if tags else "  нет"
    excl_text = "\n".join(f"  🚫 {e}" for e in exclusions) if exclusions else "  нет"
    await query.edit_message_text(
        f"🐦 **@{username}**\n\n**Теги:**\n{tag_text}\n\n**Исключения:**\n{excl_text}\n\n_+ = оба слова_",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def callback_deltag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    db.remove_account_keyword(parts[1], parts[2])
    await show_account_tags(query, parts[1])


async def callback_delexcl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    db.remove_account_exclusion(parts[1], parts[2])
    await show_account_tags(query, parts[1])


async def callback_addtag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.data.split(":", 1)[1]
    ctx.user_data["adding_tag_for"] = username
    await query.edit_message_text(
        f"🏷 Введи тег для **@{username}**:\n_Примеры: giveaway, follow+repost_\n/cancel",
        parse_mode="Markdown",
    )
    return WAITING_TAG


async def callback_addexcl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.data.split(":", 1)[1]
    ctx.user_data["adding_tag_for"] = username
    ctx.user_data["adding_mode"] = "exclusion"
    await query.edit_message_text(
        f"🚫 Введи исключение для **@{username}**:\n/cancel",
        parse_mode="Markdown",
    )
    return WAITING_EXCLUSION


async def receive_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    username = ctx.user_data.get("adding_tag_for")
    if not username:
        return ConversationHandler.END
    tag = update.message.text.strip().lower()
    if tag.startswith("/"):
        return await _cancel(update, ctx)
    db.add_account_keyword(username, tag)
    await update.message.reply_text(f"✅ {tag} → @{username}")
    ctx.user_data.clear()
    await update.message.reply_text("📄 **Аккаунты:**", reply_markup=build_pages_keyboard(db.list_accounts()), parse_mode="Markdown")
    return ConversationHandler.END


async def receive_exclusion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    username = ctx.user_data.get("adding_tag_for")
    if not username:
        return ConversationHandler.END
    word = update.message.text.strip().lower()
    if word.startswith("/"):
        return await _cancel(update, ctx)
    db.add_account_exclusion(username, word)
    await update.message.reply_text(f"✅ 🚫{word} → @{username}")
    ctx.user_data.clear()
    await update.message.reply_text("📄 **Аккаунты:**", reply_markup=build_pages_keyboard(db.list_accounts()), parse_mode="Markdown")
    return ConversationHandler.END


async def _cancel(update, ctx):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def cancel_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await _cancel(update, ctx)


async def callback_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📄 **Аккаунты:**", reply_markup=build_pages_keyboard(db.list_accounts()), parse_mode="Markdown")


async def callback_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# --- Time/Schedule ---

async def cmd_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not ctx.args:
        # Show current schedule
        mode = get_schedule_mode()
        if mode == "interval":
            return await update.message.reply_text(
                f"⏰ **Режим:** каждые {get_interval_min()} мин\n\n"
                f"**Задать расписание (МСК):**\n"
                f"`/time 18:05 18:38 20:49 03:00`\n\n"
                f"**Вернуть интервал:**\n"
                f"`/time30` — каждые 30 мин",
                parse_mode="Markdown",
            )
        else:
            times = get_schedule_times()
            times_str = "  ".join(times) if times else "—"
            return await update.message.reply_text(
                f"⏰ **Режим:** расписание (МСК)\n"
                f"**Время:** `{times_str}`\n\n"
                f"**Изменить:**\n"
                f"`/time 18:05 20:00 03:00`\n\n"
                f"**Вернуть интервал:**\n"
                f"`/time30` — каждые 30 мин",
                parse_mode="Markdown",
            )

    # Parse times
    import re
    times = []
    for arg in ctx.args:
        arg = arg.strip()
        if re.match(r"^\d{1,2}:\d{2}$", arg):
            times.append(arg)
        else:
            return await update.message.reply_text(
                f"❌ Неверный формат: `{arg}`\nИспользуй: `/time 18:05 20:49 03:00`",
                parse_mode="Markdown",
            )

    if not times:
        return await update.message.reply_text("❌ Укажи хотя бы одно время")

    set_schedule_times(times)
    times_str = "  ".join(times)
    await update.message.reply_text(
        f"✅ Расписание (МСК): `{times_str}`\n"
        f"Скан будет в указанное время.",
        parse_mode="Markdown",
    )


async def cmd_time30(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_interval_mode(30)
    await update.message.reply_text("✅ Режим: каждые 30 мин")


# --- Status ---

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    accounts = db.list_accounts()
    from config import TWITTER_LIST_ID
    has_cookies = os.path.exists(COOKIES_PATH)
    mode = get_schedule_mode()
    if mode == "interval":
        schedule_str = f"каждые {get_interval_min()} мин"
    else:
        times = get_schedule_times()
        schedule_str = f"МСК: {', '.join(times)}" if times else "не задано"
    await update.message.reply_text(
        f"📊 **Статус**\n\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"Куки: {'✅' if has_cookies else '❌'}\n"
        f"List ID: `{TWITTER_LIST_ID or 'не установлен'}`\n"
        f"Модель: `{get_model()}`\n"
        f"Расписание: {schedule_str}",
        parse_mode="Markdown",
    )


async def send_tweet_to_chat(app: Application, chat_id: str | int, username: str,
                              tweet_url: str, ai_text: str):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть в X", url=tweet_url)]])
    message = f"🐦 **@{username}**\n\n{ai_text}"
    if len(message) > 4000:
        message = message[:4000] + "..."
    await app.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown", reply_markup=keyboard)


def setup_handlers(app: Application):
    cookie_conv = ConversationHandler(
        entry_points=[CommandHandler("cookies", cmd_cookies)],
        states={
            WAITING_COOKIES: [
                CommandHandler("cancel", cancel_input),
                MessageHandler(filters.Document.ALL, receive_cookies_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cookies),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_input)],
        per_message=False,
    )

    tag_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_addtag, pattern=r"^addtag:")],
        states={WAITING_TAG: [
            CommandHandler("cancel", cancel_input),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tag),
        ]},
        fallbacks=[CommandHandler("cancel", cancel_input)],
        per_message=False,
    )

    excl_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_addexcl, pattern=r"^addexcl:")],
        states={WAITING_EXCLUSION: [
            CommandHandler("cancel", cancel_input),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_exclusion),
        ]},
        fallbacks=[CommandHandler("cancel", cancel_input)],
        per_message=False,
    )

    app.add_handler(cookie_conv)
    app.add_handler(tag_conv)
    app.add_handler(excl_conv)

    for cmd, fn in [
        ("start", cmd_start), ("help", cmd_start), ("add", cmd_add),
        ("remove", cmd_remove), ("list", cmd_list), ("pages", cmd_pages),
        ("key", cmd_key), ("models", cmd_models), ("listid", cmd_listid),
        ("status", cmd_status), ("time", cmd_time), ("time30", cmd_time30),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(CallbackQueryHandler(callback_page, pattern=r"^page:"))
    app.add_handler(CallbackQueryHandler(callback_deltag, pattern=r"^deltag:"))
    app.add_handler(CallbackQueryHandler(callback_delexcl, pattern=r"^delexcl:"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern=r"^back:"))
    app.add_handler(CallbackQueryHandler(callback_noop, pattern=r"^noop:"))
