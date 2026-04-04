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
        "/pages — управление тегами по аккаунтам\n"
        "/addkw `слово` — глобальное ключевое слово\n"
        "/rmkw `слово` — удалить глобальное слово\n"
        "/keywords — глобальные ключевые слова\n"
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
        await update.message.reply_text(f"🗑 @{username} удалён (вместе с тегами)")
    else:
        await update.message.reply_text(f"⚠️ @{username} не найден")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Список пуст. Добавь: /add @username")
    text = "📋 **Мониторинг аккаунтов:**\n\n"
    for i, acc in enumerate(accounts, 1):
        tags = db.list_account_keywords(acc)
        tag_str = ", ".join(tags) if tags else "без тегов"
        text += f"{i}. @{acc} — {tag_str}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# --- Pages: per-account tag management with inline buttons ---

async def cmd_pages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show all monitored accounts as buttons."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Нет аккаунтов. Добавь: /add @username")

    buttons = []
    row = []
    for acc in accounts:
        tags_count = len(db.list_account_keywords(acc))
        label = f"@{acc} ({tags_count})"
        row.append(InlineKeyboardButton(label, callback_data=f"page:{acc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await update.message.reply_text(
        "📄 **Выбери аккаунт** для управления тегами:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def callback_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle account button press — show tags for this account."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("page:"):
        return

    username = data.split(":", 1)[1]
    await show_account_tags(query, username)


async def show_account_tags(query, username: str):
    """Display tags for an account with delete buttons + add button."""
    tags = db.list_account_keywords(username)

    buttons = []
    for tag in tags:
        buttons.append([
            InlineKeyboardButton(f"🏷 {tag}", callback_data=f"noop:{username}"),
            InlineKeyboardButton("❌", callback_data=f"deltag:{username}:{tag}"),
        ])

    buttons.append([
        InlineKeyboardButton("➕ Добавить тег", callback_data=f"addtag:{username}"),
    ])
    buttons.append([
        InlineKeyboardButton("⬅️ Назад к аккаунтам", callback_data="back:pages"),
    ])

    tag_text = "\n".join(f"  • {t}" for t in tags) if tags else "  нет тегов"
    text = f"🐦 **@{username}**\n\nТеги:\n{tag_text}\n\n_Используй + для составных тегов (follow+repost = оба слова должны быть в твите)_"

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def callback_deltag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Delete a tag from an account."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("deltag:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 3:
        return
    username = parts[1]
    tag = parts[2]

    db.remove_account_keyword(username, tag)
    await show_account_tags(query, username)


async def callback_addtag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start adding a tag — ask user to type it."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("addtag:"):
        return

    username = data.split(":", 1)[1]
    ctx.user_data["adding_tag_for"] = username

    await query.edit_message_text(
        f"🏷 Введи тег для **@{username}**:\n\n"
        f"_Примеры: giveaway, follow+repost, share+usdt_\n\n"
        f"Отправь /cancel для отмены",
        parse_mode="Markdown",
    )
    return WAITING_TAG


async def receive_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Receive tag text from user."""
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
        await update.message.reply_text(f"⚠️ Тег «{tag}» уже есть для @{username}")

    ctx.user_data.pop("adding_tag_for", None)

    # Show updated pages
    accounts = db.list_accounts()
    buttons = []
    row = []
    for acc in accounts:
        tags_count = len(db.list_account_keywords(acc))
        label = f"@{acc} ({tags_count})"
        row.append(InlineKeyboardButton(label, callback_data=f"page:{acc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await update.message.reply_text(
        "📄 **Выбери аккаунт** для управления тегами:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("adding_tag_for", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def callback_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Back to pages list."""
    query = update.callback_query
    await query.answer()

    accounts = db.list_accounts()
    buttons = []
    row = []
    for acc in accounts:
        tags_count = len(db.list_account_keywords(acc))
        label = f"@{acc} ({tags_count})"
        row.append(InlineKeyboardButton(label, callback_data=f"page:{acc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await query.edit_message_text(
        "📄 **Выбери аккаунт** для управления тегами:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def callback_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Do nothing — just acknowledge."""
    await update.callback_query.answer()


# --- Global keywords (legacy) ---

async def cmd_addkw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    if not ctx.args:
        return await update.message.reply_text("Использование: /addkw слово")
    word = " ".join(ctx.args).lower()
    if db.add_keyword(word):
        await update.message.reply_text(f"✅ Глобальное слово «{word}» добавлено")
    else:
        await update.message.reply_text(f"⚠️ «{word}» уже в списке")


async def cmd_rmkw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    if not ctx.args:
        return await update.message.reply_text("Использование: /rmkw слово")
    word = " ".join(ctx.args).lower()
    if db.remove_keyword(word):
        await update.message.reply_text(f"🗑 «{word}» удалено")
    else:
        await update.message.reply_text(f"⚠️ «{word}» не найдено")


async def cmd_keywords(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keywords = db.list_keywords()
    if not keywords:
        return await update.message.reply_text(
            "📋 Глобальных слов нет.\n"
            "Используй /pages для тегов по аккаунтам.\n"
            "Или /addkw для глобального фильтра."
        )
    text = "🔑 **Глобальные ключевые слова:**\n\n"
    for i, kw in enumerate(keywords, 1):
        text += f"{i}. {kw}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = db.list_accounts()
    global_kw = db.list_keywords()
    acct_with_tags = sum(1 for a in accounts if db.list_account_keywords(a))
    await update.message.reply_text(
        f"📊 **Статус мониторинга**\n\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"С тегами: {acct_with_tags}\n"
        f"Глобальных слов: {len(global_kw)}\n"
        f"Фильтр: {'Активен' if global_kw or acct_with_tags else 'Выключен (все твиты)'}",
        parse_mode="Markdown",
    )


async def send_tweet_to_chat(app: Application, chat_id: str | int, username: str,
                              tweet_url: str, ai_text: str):
    """Send processed tweet to Telegram chat with 'Open in X' button."""
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
    """Register all command and callback handlers."""
    # Conversation handler for adding tags
    tag_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_addtag, pattern=r"^addtag:")],
        states={
            WAITING_TAG: [
                CommandHandler("cancel", cancel_tag),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tag),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_tag)],
        per_message=False,
    )

    app.add_handler(tag_conv)

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("pages", cmd_pages))
    app.add_handler(CommandHandler("addkw", cmd_addkw))
    app.add_handler(CommandHandler("rmkw", cmd_rmkw))
    app.add_handler(CommandHandler("keywords", cmd_keywords))
    app.add_handler(CommandHandler("status", cmd_status))

    # Callback queries
    app.add_handler(CallbackQueryHandler(callback_page, pattern=r"^page:"))
    app.add_handler(CallbackQueryHandler(callback_deltag, pattern=r"^deltag:"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern=r"^back:"))
    app.add_handler(CallbackQueryHandler(callback_noop, pattern=r"^noop:"))
