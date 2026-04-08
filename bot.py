"""Telegram bot with commands for managing Twitter monitor."""
import asyncio
import json
import logging
import os
import subprocess
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
    get_sleep_window, set_sleep_window, clear_sleep_window,
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
        "/remove — удалить (кнопки)\n"
        "/list — список с тегами\n"
        "/pages — управление тегами (кнопки)\n"
        "/sync — сравнить бот с Twitter-списком\n"
        "/git — запушить аккаунты/теги на GitHub\n\n"
        "**Настройки:**\n"
        "/cookies — загрузить куки Twitter\n"
        "/listid `ID` — установить ID списка Twitter\n"
        "/key `ключ` — сменить OpenRouter API ключ\n"
        "/models — список моделей / сменить\n"
        "/time `18:05 20:49` — расписание скана (МСК)\n"
        "/time `20` — интервал каждые N мин\n"
        "/sleep `02:00-05:00` — время сна (МСК)\n"
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
    if ctx.args:
        username = ctx.args[0].lstrip("@").lower()
        if db.remove_account(username):
            return await update.message.reply_text(f"🗑 @{username} удалён")
        else:
            return await update.message.reply_text(f"⚠️ @{username} не найден")
    accounts = db.list_accounts()
    if not accounts:
        return await update.message.reply_text("📋 Список пуст.")
    await update.message.reply_text(
        "🗑 **Выбери аккаунт для удаления:**",
        reply_markup=build_remove_keyboard(accounts),
        parse_mode="Markdown",
    )


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

async def _fetch_all_models() -> tuple[list[dict], list[dict]]:
    """Fetch all models from OpenRouter API, split into free and paid."""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://openrouter.ai/api/v1/models", timeout=15)
            r.raise_for_status()
            data = r.json()
        free = []
        paid = []
        for m in data.get("data", []):
            pricing = m.get("pricing", {})
            prompt_cost = float(pricing.get("prompt", "1") or "1")
            completion_cost = float(pricing.get("completion", "1") or "1")
            info = {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "context": m.get("context_length", 0),
                "price_in": prompt_cost,
                "price_out": completion_cost,
            }
            if prompt_cost == 0 and completion_cost == 0:
                free.append(info)
            else:
                paid.append(info)
        free.sort(key=lambda x: x["name"].lower())
        paid.sort(key=lambda x: x["name"].lower())
        return free, paid
    except Exception as e:
        logger.error(f"Failed to fetch models: {e}")
        return [], []


def _build_model_chunks(models: list[dict], header: str, current: str, show_price: bool = False) -> list[str]:
    """Build message chunks from model list."""
    chunks = [header]
    for i, m in enumerate(models, 1):
        marker = "👉 " if m["id"] == current else ""
        ctx_k = m["context"] // 1000 if m["context"] else "?"
        if show_price:
            p_in = m['price_in'] * 1_000_000
            p_out = m['price_out'] * 1_000_000
            line = f"{i}. {marker}`{m['id']}`\n    {m['name']} ({ctx_k}k) — ${p_in:.2f}/${p_out:.2f} per 1M tok\n"
        else:
            line = f"{i}. {marker}`{m['id']}`\n    {m['name']} ({ctx_k}k)\n"
        if len(chunks[-1]) + len(line) > 3800:
            chunks.append("")
        chunks[-1] += line
    return chunks


async def cmd_models(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if ctx.args:
        model_name = " ".join(ctx.args).strip()
        set_model(model_name)
        return await update.message.reply_text(f"✅ Модель: `{model_name}`", parse_mode="Markdown")

    await update.message.reply_text("⏳ Загружаю список моделей...")

    free, paid = await _fetch_all_models()
    if not free and not paid:
        return await update.message.reply_text("❌ Не удалось загрузить список моделей")

    current = get_model()

    # Free models
    if free:
        header = f"🤖 **Текущая:** `{current}`\n\n🆓 **Бесплатные ({len(free)}):**\n\n"
        chunks = _build_model_chunks(free, header, current)
        chunks[-1] += f"\nСменить: `/models название`"
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")

    # Paid models
    if paid:
        header = f"💰 **Платные ({len(paid)}):**\n\n"
        chunks = _build_model_chunks(paid, header, current, show_price=True)
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")


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


def build_remove_keyboard(accounts: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for acc in accounts:
        buttons.append([
            InlineKeyboardButton(f"🗑 @{acc}", callback_data=f"removeacc:{acc}"),
        ])
    buttons.append([InlineKeyboardButton("⬅️ Отмена", callback_data="back:cancel")])
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
    target = query.data.split(":", 1)[1] if ":" in query.data else "pages"
    if target == "cancel":
        await query.edit_message_text("Отменено.")
    else:
        await query.edit_message_text("📄 **Аккаунты:**", reply_markup=build_pages_keyboard(db.list_accounts()), parse_mode="Markdown")


async def callback_removeacc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    username = query.data.split(":", 1)[1]
    db.remove_account(username)
    await query.answer(f"@{username} удалён")
    accounts = db.list_accounts()
    if accounts:
        await query.edit_message_text(
            "🗑 **Удалён @" + username + "**\n\nУдалить ещё:",
            reply_markup=build_remove_keyboard(accounts),
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("📋 Все аккаунты удалены.")


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
                f"**Задать интервал:**\n"
                f"`/time 20` — каждые 20 мин\n"
                f"`/time 45` — каждые 45 мин",
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
                f"**Задать интервал:**\n"
                f"`/time 20` — каждые 20 мин",
                parse_mode="Markdown",
            )

    import re

    # Single number = interval mode
    if len(ctx.args) == 1 and re.match(r"^\d+$", ctx.args[0].strip()):
        minutes = int(ctx.args[0].strip())
        if minutes < 1 or minutes > 1440:
            return await update.message.reply_text("❌ Интервал: от 1 до 1440 минут")
        set_interval_mode(minutes)
        return await update.message.reply_text(f"✅ Режим: каждые {minutes} мин")

    # Parse times
    times = []
    for arg in ctx.args:
        arg = arg.strip()
        if re.match(r"^\d{1,2}:\d{2}$", arg):
            times.append(arg)
        else:
            return await update.message.reply_text(
                f"❌ Неверный формат: `{arg}`\nИспользуй: `/time 18:05 20:49 03:00` или `/time 20`",
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


# --- Sleep ---

async def cmd_sleep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    import re

    if not ctx.args:
        window = get_sleep_window()
        if window:
            return await update.message.reply_text(
                f"💤 **Сон:** `{window[0]}` — `{window[1]}` (МСК)\n\n"
                f"Изменить: `/sleep 02:00-05:00`\n"
                f"Отключить: `/sleep 0`",
                parse_mode="Markdown",
            )
        return await update.message.reply_text(
            "💤 **Сон:** выключен\n\n"
            "Включить: `/sleep 02:00-05:00`\n"
            "Формат: `/sleep ЧЧ:ММ-ЧЧ:ММ` (МСК)",
            parse_mode="Markdown",
        )

    arg = " ".join(ctx.args).strip()

    if arg == "0":
        clear_sleep_window()
        return await update.message.reply_text("✅ Сон отключён — бот работает 24/7")

    match = re.match(r"^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})$", arg)
    if not match:
        return await update.message.reply_text(
            "❌ Формат: `/sleep 02:00-05:00` или `/sleep 0`",
            parse_mode="Markdown",
        )

    start, end = match.group(1), match.group(2)
    set_sleep_window(start, end)
    await update.message.reply_text(
        f"✅ Сон: `{start}` — `{end}` (МСК)\n"
        f"Бот не парсит в это время.",
        parse_mode="Markdown",
    )


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
    window = get_sleep_window()
    sleep_str = f"{window[0]}—{window[1]} МСК" if window else "выключен"
    await update.message.reply_text(
        f"📊 **Статус**\n\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"Куки: {'✅' if has_cookies else '❌'}\n"
        f"List ID: `{TWITTER_LIST_ID or 'не установлен'}`\n"
        f"Модель: `{get_model()}`\n"
        f"Расписание: {schedule_str}\n"
        f"Сон: {sleep_str}",
        parse_mode="Markdown",
    )


# --- Sync ---

async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manual sync: compare bot accounts with actual Twitter list members."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🔄 Загружаю участников списка...")

    from scraper import fetch_list_members
    list_members = await fetch_list_members()

    if not list_members:
        return await update.message.reply_text(
            "❌ Не удалось загрузить участников списка.\n"
            "Проверь куки (/cookies) и List ID (/listid)"
        )

    monitored = set(db.list_accounts())

    only_in_list = sorted(list_members - monitored)
    only_in_bot = sorted(monitored - list_members)
    in_both = sorted(list_members & monitored)

    text = f"📊 **Синхронизация**\n\n"
    text += f"✅ В списке и в боте: **{len(in_both)}**\n"

    if only_in_list:
        text += f"\n🆕 **В списке, но НЕ в боте ({len(only_in_list)}):**\n"
        for u in only_in_list:
            text += f"  • @{u}\n"

    if only_in_bot:
        text += f"\n⚠️ **В боте, но НЕ в списке ({len(only_in_bot)}):**\n"
        for u in only_in_bot:
            source = db.get_account_source(u)
            tag = " (manual)" if source == "manual" else ""
            text += f"  • @{u}{tag}\n"

    if not only_in_list and not only_in_bot:
        text += "\n🎉 Всё синхронизировано!"

    if len(text) > 4000:
        text = text[:3950] + "\n\n... (обрезано)"

    await update.message.reply_text(text, parse_mode="Markdown")


# --- Git push ---

async def cmd_git(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Export accounts/tags/exclusions to JSON and push to GitHub."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📦 Экспортирую аккаунты и пушу на GitHub...")

    try:
        # Export accounts with tags and exclusions
        accounts = db.list_accounts()
        export = []
        for acc in accounts:
            source = db.get_account_source(acc)
            tags = db.list_account_keywords(acc)
            exclusions = db.list_account_exclusions(acc)
            export.append({
                "username": acc,
                "source": source or "manual",
                "tags": tags,
                "exclusions": exclusions,
            })

        # Write export file
        bot_dir = os.path.dirname(os.path.abspath(__file__))
        export_path = os.path.join(bot_dir, "accounts_export.json")
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)

        # Git add, commit, push
        def _git_push():
            cwd = bot_dir
            subprocess.run(["git", "add", "-A"], cwd=cwd, check=True, capture_output=True)
            # Check if there are changes to commit
            result = subprocess.run(
                ["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True
            )
            if not result.stdout.strip():
                return "nothing"
            subprocess.run(
                ["git", "commit", "-m", f"bot: update accounts ({len(export)} users)"],
                cwd=cwd, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "push"], cwd=cwd, check=True, capture_output=True, timeout=30,
            )
            return "ok"

        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(None, _git_push)

        if status == "nothing":
            await update.message.reply_text("✅ Нет изменений — GitHub уже актуален")
        else:
            await update.message.reply_text(
                f"✅ Запушено на GitHub!\n"
                f"📋 Аккаунтов: **{len(export)}**",
                parse_mode="Markdown",
            )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        await update.message.reply_text(f"❌ Git ошибка:\n`{stderr[:500]}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


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
        ("status", cmd_status), ("time", cmd_time), ("sleep", cmd_sleep),
        ("sync", cmd_sync), ("git", cmd_git),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(CallbackQueryHandler(callback_removeacc, pattern=r"^removeacc:"))
    app.add_handler(CallbackQueryHandler(callback_page, pattern=r"^page:"))
    app.add_handler(CallbackQueryHandler(callback_deltag, pattern=r"^deltag:"))
    app.add_handler(CallbackQueryHandler(callback_delexcl, pattern=r"^delexcl:"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern=r"^back:"))
    app.add_handler(CallbackQueryHandler(callback_noop, pattern=r"^noop:"))
