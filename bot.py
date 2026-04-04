"""Telegram bot with commands for managing Twitter monitor."""
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from config import TG_BOT_TOKEN, ADMIN_IDS
import database as db

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """Check if user is admin. If ADMIN_IDS is empty, allow everyone."""
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
        "/addkw `слово` — добавить ключевое слово\n"
        "/rmkw `слово` — удалить ключевое слово\n"
        "/keywords — список ключевых слов\n"
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
        await update.message.reply_text(f"🗑 @{username} удалён из мониторинга")
    else:
        await update.message.reply_text(f"⚠️ @{username} не найден")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Список пуст. Добавь: /add @username")
    text = "📋 **Мониторинг аккаунтов:**\n\n"
    for i, acc in enumerate(accounts, 1):
        text += f"{i}. @{acc}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_addkw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔ Нет доступа")
    if not ctx.args:
        return await update.message.reply_text("Использование: /addkw слово")
    word = " ".join(ctx.args).lower()
    if db.add_keyword(word):
        await update.message.reply_text(f"✅ Ключевое слово «{word}» добавлено")
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
        return await update.message.reply_text("📋 Ключевых слов нет. Все твиты будут проходить.\nДобавь: /addkw слово")
    text = "🔑 **Ключевые слова:**\n\n"
    for i, kw in enumerate(keywords, 1):
        text += f"{i}. {kw}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    accounts = db.list_accounts()
    keywords = db.list_keywords()
    await update.message.reply_text(
        f"📊 **Статус мониторинга**\n\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"Ключевых слов: {len(keywords)}\n"
        f"Фильтр: {'Активен' if keywords else 'Выключен (все твиты)'}",
        parse_mode="Markdown",
    )


async def send_tweet_to_chat(app: Application, chat_id: str | int, username: str,
                              tweet_url: str, ai_text: str):
    """Send processed tweet to Telegram chat with 'Open in X' button."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Открыть в X", url=tweet_url)]
    ])
    message = f"🐦 **@{username}**\n\n{ai_text}"
    # Telegram message limit is 4096 chars
    if len(message) > 4000:
        message = message[:4000] + "..."
    await app.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


def setup_handlers(app: Application):
    """Register all command handlers."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("addkw", cmd_addkw))
    app.add_handler(CommandHandler("rmkw", cmd_rmkw))
    app.add_handler(CommandHandler("keywords", cmd_keywords))
    app.add_handler(CommandHandler("status", cmd_status))
