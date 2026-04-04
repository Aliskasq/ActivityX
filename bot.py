"""Telegram bot with commands for managing Twitter monitor."""
import logging
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
from config import ADMIN_IDS
import database as db

logger = logging.getLogger(__name__)

# Conversation states
WAITING_TAG = 1
WAITING_EXCLUSION = 2


def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


# --- Commands ---

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🐦 **Twitter Monitor Bot**\n\n"
        "Команды:\n"
        "/add `@username` — добавить аккаунт\n"
        "/remove `@username` — удалить аккаунт\n"
        "/list — список аккаунтов\n"
        "/pages — управление тегами и исключениями\n"
        "/status — статус мониторинга",
        parse_mode="Markdown",
    )


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    if not ctx.args:
        return await update.message.reply_text("Использование: /add @username")
    username = ctx.args[0].lstrip("@").lower()
    if db.add_account(username):
        await update.message.reply_text(f"✅ @{username} добавлен в мониторинг")
    else:
        await update.message.reply_text(f"⚠️ @{username} уже в списке")


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    if not ctx.args:
        return await update.message.reply_text("Использование: /remove @username")
    username = ctx.args[0].lstrip("@").lower()
    if db.remove_account(username):
        await update.message.reply_text(f"🗑 @{username} удалён (вместе с тегами и исключениями)")
    else:
        await update.message.reply_text(f"⚠️ @{username} не найден")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Список пуст. Добавь: /add @username")
    text = "📋 **Мониторинг аккаунтов:**\n\n"
    for i, acc in enumerate(accounts, 1):
        tags = db.list_account_keywords(acc)
        excl = db.list_account_exclusions(acc)
        tag_str = ", ".join(tags) if tags else "—"
        excl_str = ", ".join(f"❌{e}" for e in excl) if excl else ""
        line = f"{i}. @{acc} — {tag_str}"
        if excl_str:
            line += f"\n   Искл: {excl_str}"
        text += line + "\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# --- Pages: per-account tag/exclusion management ---

async def cmd_pages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Нет аккаунтов. Добавь: /add @username")

    buttons = []
    row = []
    for acc in accounts:
        tags_count = len(db.list_account_keywords(acc))
        excl_count = len(db.list_account_exclusions(acc))
        label = f"@{acc} ({tags_count}t/{excl_count}x)"
        row.append(InlineKeyboardButton(label, callback_data=f"page:{acc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await update.message.reply_text(
        "📄 **Выбери аккаунт:**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


def build_pages_keyboard(accounts: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for acc in accounts:
        tags_count = len(db.list_account_keywords(acc))
        excl_count = len(db.list_account_exclusions(acc))
        label = f"@{acc} ({tags_count}t/{excl_count}x)"
        row.append(InlineKeyboardButton(label, callback_data=f"page:{acc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def callback_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.data.split(":", 1)[1]
    await show_account_tags(query, username)


async def show_account_tags(query, username: str):
    tags = db.list_account_keywords(username)
    exclusions = db.list_account_exclusions(username)

    buttons = []

    # Tags section
    for tag in tags:
        buttons.append([
            InlineKeyboardButton(f"🏷 {tag}", callback_data=f"noop:{username}"),
            InlineKeyboardButton("❌", callback_data=f"deltag:{username}:{tag}"),
        ])

    # Exclusions section
    for ex in exclusions:
        buttons.append([
            InlineKeyboardButton(f"🚫 {ex}", callback_data=f"noop:{username}"),
            InlineKeyboardButton("❌", callback_data=f"delexcl:{username}:{ex}"),
        ])

    buttons.append([
        InlineKeyboardButton("➕ Тег", callback_data=f"addtag:{username}"),
        InlineKeyboardButton("➕ Исключение", callback_data=f"addexcl:{username}"),
    ])
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back:pages"),
    ])

    tag_text = "\n".join(f"  🏷 {t}" for t in tags) if tags else "  нет тегов"
    excl_text = "\n".join(f"  🚫 {e}" for e in exclusions) if exclusions else "  нет исключений"
    text = (
        f"🐦 **@{username}**\n\n"
        f"**Теги** (совпадение = отправить):\n{tag_text}\n\n"
        f"**Исключения** (совпадение = пропустить):\n{excl_text}\n\n"
        f"_+ между словами = оба обязательны_"
    )

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def callback_deltag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return
    db.remove_account_keyword(parts[1], parts[2])
    await show_account_tags(query, parts[1])


async def callback_delexcl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return
    db.remove_account_exclusion(parts[1], parts[2])
    await show_account_tags(query, parts[1])


async def callback_addtag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = query.data.split(":", 1)[1]
    ctx.user_data["adding_tag_for"] = username
    ctx.user_data["adding_mode"] = "tag"
    await query.edit_message_text(
        f"🏷 Введи тег для **@{username}**:\n\n"
        f"_Примеры: giveaway, follow+repost, share+usdt_\n"
        f"/cancel для отмены",
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
        f"🚫 Введи слово-исключение для **@{username}**:\n\n"
        f"_Если твит содержит это слово — он будет пропущен_\n"
        f"/cancel для отмены",
        parse_mode="Markdown",
    )
    return WAITING_EXCLUSION


async def receive_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    username = ctx.user_data.get("adding_tag_for")
    if not username:
        return ConversationHandler.END

    tag = update.message.text.strip().lower()
    if tag.startswith("/"):
        await update.message.reply_text("Отменено.")
        return ConversationHandler.END

    if db.add_account_keyword(username, tag):
        await update.message.reply_text(f"✅ Тег «{tag}» добавлен для @{username}")
    else:
        await update.message.reply_text(f"⚠️ Тег «{tag}» уже есть")

    ctx.user_data.pop("adding_tag_for", None)
    ctx.user_data.pop("adding_mode", None)

    accounts = db.list_accounts()
    await update.message.reply_text(
        "📄 **Выбери аккаунт:**",
        reply_markup=build_pages_keyboard(accounts),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def receive_exclusion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    username = ctx.user_data.get("adding_tag_for")
    if not username:
        return ConversationHandler.END

    word = update.message.text.strip().lower()
    if word.startswith("/"):
        await update.message.reply_text("Отменено.")
        return ConversationHandler.END

    if db.add_account_exclusion(username, word):
        await update.message.reply_text(f"✅ Исключение «{word}» добавлено для @{username}")
    else:
        await update.message.reply_text(f"⚠️ «{word}» уже есть")

    ctx.user_data.pop("adding_tag_for", None)
    ctx.user_data.pop("adding_mode", None)

    accounts = db.list_accounts()
    await update.message.reply_text(
        "📄 **Выбери аккаунт:**",
        reply_markup=build_pages_keyboard(accounts),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("adding_tag_for", None)
    ctx.user_data.pop("adding_mode", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def callback_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    accounts = db.list_accounts()
    await query.edit_message_text(
        "📄 **Выбери аккаунт:**",
        reply_markup=build_pages_keyboard(accounts),
        parse_mode="Markdown",
    )


async def callback_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = db.list_accounts()
    acct_with_tags = sum(1 for a in accounts if db.list_account_keywords(a))
    acct_with_excl = sum(1 for a in accounts if db.list_account_exclusions(a))
    global_kw = db.list_keywords()
    await update.message.reply_text(
        f"📊 **Статус мониторинга**\n\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"С тегами: {acct_with_tags}\n"
        f"С исключениями: {acct_with_excl}\n"
        f"Глобальных слов: {len(global_kw)}",
        parse_mode="Markdown",
    )


async def send_tweet_to_chat(app: Application, chat_id: str | int, username: str,
                              tweet_url: str, ai_text: str):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Открыть в X", url=tweet_url)]
    ])
    message = f"🐦 **@{username}**\n\n{ai_text}"
    if len(message) > 4000:
        message = message[:4000] + "..."
    await app.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


def setup_handlers(app: Application):
    # Conversation for adding tags
    tag_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_addtag, pattern=r"^addtag:")],
        states={
            WAITING_TAG: [
                CommandHandler("cancel", cancel_input),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tag),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_input)],
        per_message=False,
    )

    # Conversation for adding exclusions
    excl_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_addexcl, pattern=r"^addexcl:")],
        states={
            WAITING_EXCLUSION: [
                CommandHandler("cancel", cancel_input),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_exclusion),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_input)],
        per_message=False,
    )

    app.add_handler(tag_conv)
    app.add_handler(excl_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("pages", cmd_pages))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CallbackQueryHandler(callback_page, pattern=r"^page:"))
    app.add_handler(CallbackQueryHandler(callback_deltag, pattern=r"^deltag:"))
    app.add_handler(CallbackQueryHandler(callback_delexcl, pattern=r"^delexcl:"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern=r"^back:"))
    app.add_handler(CallbackQueryHandler(callback_noop, pattern=r"^noop:"))
