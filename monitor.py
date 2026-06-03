"""Main monitoring loop — fetches Twitter list on schedule or interval."""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from telegram.ext import Application

import database as db
from scraper import fetch_list_tweets, fetch_list_members, fetch_user_tweets, matches_keywords, auto_fix_hashes
from ai_processor import process_tweet
from bot import send_tweet_to_chat
from config import (
    TG_CHAT_ID, TWITTER_LIST_ID,
    get_schedule_mode, get_schedule_times, get_interval_min, get_sleep_window,
    get_scan_windows, get_scan_period_min,
)

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

# Track cleanup state
_last_cleanup_date: str | None = None

# Track error state to avoid spamming
_last_error_notified: str | None = None
# Track manual-not-in-list notifications (only send once per user)
_notified_manual_missing: set[str] = set()

# Timeline scan state
_timeline_scan_requested: bool = False  # Manual scan trigger
_single_account_scan: dict | None = None  # {"username": ..., "count": ..., "chat_id": ...}


def request_manual_scan():
    """Trigger a manual timeline scan (called from bot /scan_now)."""
    global _timeline_scan_requested
    _timeline_scan_requested = True


def request_single_account_scan(username: str, count: int, chat_id: int):
    """Trigger a scan of a single account (called from bot)."""
    global _single_account_scan
    _single_account_scan = {"username": username, "count": count, "chat_id": chat_id}


def _is_sleeping() -> bool:
    """Check if current MSK time is within sleep window."""
    window = get_sleep_window()
    if not window:
        return False
    now_msk = datetime.now(MSK)
    current = now_msk.hour * 60 + now_msk.minute

    start_h, start_m = map(int, window[0].split(":"))
    end_h, end_m = map(int, window[1].split(":"))
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m

    if start <= end:
        return start <= current < end
    else:
        return current >= start or current < end


def _seconds_until_wake() -> float:
    """Seconds until sleep window ends (MSK)."""
    window = get_sleep_window()
    if not window:
        return 0
    now_msk = datetime.now(MSK)
    end_h, end_m = map(int, window[1].split(":"))
    wake = now_msk.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    if wake <= now_msk:
        wake += timedelta(days=1)
    return (wake - now_msk).total_seconds()


def _seconds_until_next_run() -> float:
    """Calculate seconds until the next scheduled run."""
    mode = get_schedule_mode()

    if mode == "interval":
        return get_interval_min() * 60

    times = get_schedule_times()
    if not times:
        return 1800

    now_msk = datetime.now(MSK)
    upcoming = []

    for t_str in times:
        try:
            parts = t_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            candidate = now_msk.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= now_msk:
                candidate += timedelta(days=1)
            upcoming.append(candidate)
        except (ValueError, IndexError):
            continue

    if not upcoming:
        return 1800

    nearest = min(upcoming)
    delta = (nearest - now_msk).total_seconds()
    return max(delta, 10)


async def _notify_error(app: Application, error_key: str, message: str):
    """Send error notification to TG (once per error type, no spam)."""
    global _last_error_notified
    if _last_error_notified == error_key:
        return
    _last_error_notified = error_key
    if TG_CHAT_ID:
        try:
            await app.bot.send_message(chat_id=TG_CHAT_ID, text=message)
        except Exception as e:
            logger.error(f"Failed to send error notification: {e}")


async def _clear_error():
    """Clear error state after successful fetch."""
    global _last_error_notified
    _last_error_notified = None


async def sync_members(app: Application) -> set[str] | None:
    """Sync bot accounts with actual Twitter list members.

    Returns set of list members if successful, None on error.
    """
    global _notified_manual_missing

    logger.info("Fetching list members...")
    list_members = await fetch_list_members()
    if not list_members:
        logger.warning("Could not fetch list members (empty or error) — skipping sync")
        return None

    monitored = set(db.list_accounts())

    # Add new users from list
    new_users = list_members - monitored
    for new_user in sorted(new_users):
        db.add_account(new_user, source="list")
        logger.info(f"Auto-added @{new_user} from list")
        if TG_CHAT_ID:
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏷 Настроить теги", callback_data=f"page:{new_user}")],
                    [InlineKeyboardButton("🚫 Исключения", callback_data=f"addexcl:{new_user}"),
                     InlineKeyboardButton("⏭ Пропустить", callback_data=f"syncskip:{new_user}")],
                ])
                await app.bot.send_message(
                    chat_id=TG_CHAT_ID,
                    text=f"🆕 **@{new_user}** добавлен из Twitter-списка!\n\nДобавь теги и исключения для фильтрации:",
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            except Exception:
                pass

    # Handle users no longer in list
    removed_users = monitored - list_members
    for old_user in sorted(removed_users):
        source = db.get_account_source(old_user)
        if source == "manual":
            if old_user not in _notified_manual_missing:
                _notified_manual_missing.add(old_user)
                logger.info(f"@{old_user} (manual) not in Twitter list — notifying")
                if TG_CHAT_ID:
                    try:
                        await app.bot.send_message(
                            chat_id=TG_CHAT_ID,
                            text=f"⚠️ @{old_user} добавлен вручную, но его нет в Twitter-списке!\nДобавь в список или удали: /remove @{old_user}",
                        )
                    except Exception:
                        pass
        else:
            db.remove_account(old_user)
            logger.info(f"Auto-removed @{old_user} (not in Twitter list)")
            if TG_CHAT_ID:
                try:
                    await app.bot.send_message(
                        chat_id=TG_CHAT_ID,
                        text=f"🗑 @{old_user} удалён (нет в Twitter-списке)",
                    )
                except Exception:
                    pass

    # Clear manual-missing notifications for users now back in list
    _notified_manual_missing -= list_members

    return list_members


async def _daily_cleanup(app: Application):
    """Delete seen tweets older than 7 days. Runs once per day after 00:00 MSK."""
    global _last_cleanup_date
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    if _last_cleanup_date == today:
        return
    now_msk = datetime.now(MSK)
    if now_msk.hour < 0 or (now_msk.hour == 0 and now_msk.minute < 0):
        return
    _last_cleanup_date = today
    deleted = db.cleanup_old(days=45)
    if deleted:
        logger.info(f"🧹 Cleanup: deleted {deleted} seen tweets older than 7 days")


async def monitor_loop(app: Application):
    """Main loop: fetch list tweets on schedule, filter by per-account tags."""
    logger.info("Monitor loop started")

    if not TWITTER_LIST_ID:
        logger.warning("TWITTER_LIST_ID not set — monitor will wait for it")

    while True:
        try:
            if not TWITTER_LIST_ID:
                await asyncio.sleep(60)
                continue

            # Sleep mode check
            if _is_sleeping():
                wake_in = _seconds_until_wake()
                logger.info(f"💤 Sleep mode — wake in {wake_in/60:.0f} min")
                await asyncio.sleep(min(wake_in, 300))
                continue

            # Daily cleanup of old seen tweets
            await _daily_cleanup(app)

            # Sync members with actual Twitter list (every scan)
            await sync_members(app)

            logger.info("Fetching Twitter list tweets...")
            try:
                tweets = await fetch_list_tweets()
            except Exception as e:
                error_msg = str(e).lower()
                if "cookie" in error_msg or "401" in error_msg or "403" in error_msg:
                    await _notify_error(app, "cookies", "🚨 Куки Twitter протухли! Обнови через /cookies")
                else:
                    await _notify_error(app, "fetch", f"🚨 Ошибка загрузки Twitter: {e}")
                logger.error(f"Fetch error: {e}", exc_info=True)
                wait = _seconds_until_next_run()
                await asyncio.sleep(wait)
                continue

            if not tweets:
                logger.info("No tweets fetched (check cookies/list_id)")
                await _notify_error(app, "empty", "⚠️ Twitter вернул 0 твитов — возможно куки протухли. Проверь /cookies")
                wait = _seconds_until_next_run()
                logger.info(f"Next check in {wait/60:.1f} min")
                await asyncio.sleep(wait)
                continue

            await _clear_error()

            monitored = set(db.list_accounts())
            logger.info(f"Processing {len(tweets)} tweets...")
            matched = []

            new_count = 0
            skip_seen = 0
            skip_unmonitored = 0
            for tweet in tweets:
                if db.is_seen(tweet.tweet_id):
                    skip_seen += 1
                    continue

                new_count += 1
                if tweet.username not in monitored:
                    skip_unmonitored += 1
                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    continue

                acct_keywords = db.list_account_keywords(tweet.username)
                acct_exclusions = db.list_account_exclusions(tweet.username)

                is_match = matches_keywords(tweet, acct_keywords, acct_exclusions)
                logger.info(
                    f"@{tweet.username}/{tweet.tweet_id} match={is_match} "
                    f"kw={acct_keywords} excl={acct_exclusions} "
                    f"text={tweet.text[:100]!r}"
                )

                if not is_match:
                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    continue

                logger.info(f"✅ Match! @{tweet.username}: {tweet.tweet_id}")
                matched.append(tweet)
                db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)

            # Count unknown usernames for health alert
            unknown_count = sum(1 for t in tweets if t.username == "unknown")
            logger.info(
                f"Scan summary: {len(tweets)} total, {skip_seen} seen, "
                f"{new_count} new, {skip_unmonitored} unmonitored, "
                f"{len(matched)} matched, {unknown_count} unknown"
            )

            # Health alerts
            if unknown_count > len(tweets) * 0.5 and len(tweets) > 0:
                await _notify_error(
                    app, "unknown_users",
                    f"⚠️ Проблема парсинга: {unknown_count}/{len(tweets)} твитов "
                    f"с username=unknown.\nВозможно Twitter сменил структуру API.\n"
                    f"Попробуй /fix_hashes"
                )
            if matched:
                logger.info(f"Processing {len(matched)} matched tweets through AI...")
            for tweet in matched:
                try:
                    ai_result = await process_tweet(tweet.text, tweet.username)
                    if TG_CHAT_ID:
                        await send_tweet_to_chat(app, TG_CHAT_ID, tweet.username, tweet.url, ai_result)
                    # 30 sec pause between AI requests to avoid 429 on free models
                    await asyncio.sleep(30)
                except Exception as e:
                    logger.error(f"Error processing @{tweet.username}/{tweet.tweet_id}: {e}")

        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
            await _notify_error(app, "crash", f"🚨 Монитор упал: {e}")

        wait = _seconds_until_next_run()
        # Add jitter to avoid bot-like patterns
        interval_min = wait / 60
        if interval_min <= 20:
            jitter = random.uniform(-1.5, 1.5) * 60  # ±1.5 min
        elif interval_min <= 40:
            jitter = random.uniform(-3, 3) * 60  # ±3 min
        else:
            jitter = random.uniform(-5, 5) * 60  # ±5 min
        wait = max(60, wait + jitter)  # Minimum 1 min
        logger.info(f"Next check in {wait/60:.1f} min (jitter applied)")
        await asyncio.sleep(wait)


async def _process_account_tweets(app: Application, username: str, tweets: list) -> int:
    """Process tweets from a single account timeline. Returns number of matches."""
    if not tweets:
        return 0

    monitored = set(db.list_accounts())
    acct_keywords = db.list_account_keywords(username)
    acct_exclusions = db.list_account_exclusions(username)
    matched = []

    for tweet in tweets:
        if db.is_seen(tweet.tweet_id):
            continue

        if tweet.username not in monitored:
            db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
            continue

        is_match = matches_keywords(tweet, acct_keywords, acct_exclusions)
        logger.info(
            f"[timeline] @{tweet.username}/{tweet.tweet_id} match={is_match} "
            f"kw={acct_keywords} excl={acct_exclusions} "
            f"text={tweet.text[:100]!r}"
        )

        db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
        if is_match:
            logger.info(f"✅ Timeline match! @{tweet.username}: {tweet.tweet_id}")
            matched.append(tweet)

    for tweet in matched:
        try:
            ai_result = await process_tweet(tweet.text, tweet.username)
            if TG_CHAT_ID:
                await send_tweet_to_chat(app, TG_CHAT_ID, tweet.username, tweet.url, ai_result)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Error processing timeline tweet @{tweet.username}/{tweet.tweet_id}: {e}")

    return len(matched)


def _in_time_window(now_msk: datetime, start_str: str, end_str: str) -> bool:
    """Check if current MSK time is within a window (handles overnight)."""
    current = now_msk.hour * 60 + now_msk.minute
    sh, sm = map(int, start_str.split(":"))
    eh, em = map(int, end_str.split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= current < end
    else:
        return current >= start or current < end


def _window_key(start: str, end: str) -> str:
    return f"{start}-{end}"


async def _run_single_account_scan(app: Application, username: str, count: int, chat_id: int):
    """Scan a single account's timeline with fresh seen state."""
    logger.info(f"📡 Single account scan: @{username}, count={count}")

    # Clear seen tweets for this account
    cleared = db.clear_seen_for_user(username)
    logger.info(f"Cleared {cleared} seen tweets for @{username}")

    try:
        tweets = await fetch_user_tweets(username, count=count)
        matches = await _process_account_tweets(app, username, tweets)
        logger.info(
            f"[single-scan] @{username}: {len(tweets)} fetched, {matches} matched"
        )

        # Send result to chat
        try:
            text = (
                f"🔍 Скан @{username} завершён\n\n"
                f"Получено твитов: {len(tweets)}\n"
                f"Совпадений: {matches}\n"
                f"Очищено seen: {cleared}"
            )
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[single-scan] Error scanning @{username}: {e}", exc_info=True)
        try:
            await app.bot.send_message(
                chat_id=chat_id, text=f"❌ Ошибка скана @{username}: {e}"
            )
        except Exception:
            pass


async def _run_timeline_scan(app: Application, label: str = "window"):
    """Run one full pass through all accounts' timelines with delays."""
    accounts = db.list_accounts()
    if not accounts:
        return
    period_min = get_scan_period_min()
    total_matched = 0

    logger.info(f"📡 Timeline scan started ({label}): {len(accounts)} accounts, period={period_min}min")
    if TG_CHAT_ID:
        try:
            await app.bot.send_message(
                chat_id=TG_CHAT_ID,
                text=f"📡 Скан аккаунтов начался ({label}): {len(accounts)} акков",
            )
        except Exception:
            pass

    for i, username in enumerate(accounts):
        try:
            count = random.randint(19, 27)
            tweets = await fetch_user_tweets(username, count=count)
            unknown_count = sum(1 for t in tweets if t.username == "unknown")
            matches = await _process_account_tweets(app, username, tweets)
            total_matched += matches
            logger.info(
                f"[timeline] @{username}: {len(tweets)} fetched, {matches} matched, "
                f"{unknown_count} unknown ({i+1}/{len(accounts)})"
            )
            # Alert if too many unknowns in timeline scan
            if unknown_count > len(tweets) * 0.5 and len(tweets) > 5:
                await _notify_error(
                    app, f"unknown_{username}",
                    f"⚠️ @{username}: {unknown_count}/{len(tweets)} твитов "
                    f"с username=unknown. Twitter мог сменить API.\n"
                    f"Попробуй /fix_hashes"
                )
        except Exception as e:
            logger.error(f"[timeline] Error scanning @{username}: {e}", exc_info=True)

        # Delay between accounts (except after last one)
        if i < len(accounts) - 1:
            delay = period_min * 60 + random.randint(1, 30)
            logger.info(f"[timeline] Next account in {delay}s")
            await asyncio.sleep(delay)

    logger.info(f"📡 Timeline scan finished ({label}): {total_matched} total matches")
    if TG_CHAT_ID:
        try:
            await app.bot.send_message(
                chat_id=TG_CHAT_ID,
                text=f"✅ Скан аккаунтов завершён ({label}): {total_matched} совпадений",
            )
        except Exception:
            pass


async def timeline_scan_loop(app: Application):
    """Background loop: scan individual account timelines during configured windows."""
    global _timeline_scan_requested, _single_account_scan

    logger.info("Timeline scan loop started")
    # Track which windows were completed (cleared only when window becomes inactive,
    # NOT on date change — this fixes overnight windows like 21:00-02:00 firing twice)
    completed_windows: dict[str, datetime] = {}  # window_key -> when completed (MSK)

    while True:
        try:
            # Check for single account scan request
            if _single_account_scan is not None:
                req = _single_account_scan
                _single_account_scan = None
                await _run_single_account_scan(
                    app, req["username"], req["count"], req["chat_id"]
                )
                continue

            # Check for manual scan request
            if _timeline_scan_requested:
                _timeline_scan_requested = False
                logger.info("Manual timeline scan triggered")
                await _run_timeline_scan(app, label="ручной")
                continue

            # Check scan windows
            windows = get_scan_windows()
            if not windows:
                await asyncio.sleep(60)
                continue

            now_msk = datetime.now(MSK)

            # Clean completed_windows: remove entries for windows that are
            # no longer active (the window has ended since we last scanned).
            # This way overnight windows stay "completed" until they fully close.
            for start, end in windows:
                wk = _window_key(start, end)
                if wk in completed_windows and not _in_time_window(now_msk, start, end):
                    del completed_windows[wk]
                    logger.info(f"[timeline] Window {wk} ended, cleared from completed")

            # Also clean keys that no longer match any configured window
            configured_keys = {_window_key(s, e) for s, e in windows}
            for wk in list(completed_windows.keys()):
                if wk not in configured_keys:
                    del completed_windows[wk]

            active_window = None
            for start, end in windows:
                wk = _window_key(start, end)
                if _in_time_window(now_msk, start, end) and wk not in completed_windows:
                    active_window = (start, end)
                    break

            if not active_window:
                await asyncio.sleep(60)
                continue

            wk = _window_key(active_window[0], active_window[1])

            # Random start delay within the first hour of the window
            wh, wm = map(int, active_window[0].split(":"))
            window_start_min = wh * 60 + wm
            current_min = now_msk.hour * 60 + now_msk.minute
            # How many minutes since window started
            elapsed = current_min - window_start_min
            if elapsed < 0:
                elapsed += 24 * 60  # overnight window

            if elapsed < 60:
                # We're in the first hour — pick random delay within remaining time
                remaining = max(0, 60 - elapsed)
                if remaining > 1:
                    delay_min = random.randint(0, remaining - 1)
                    logger.info(f"[timeline] Window {wk} active, random start in {delay_min} min")
                    await asyncio.sleep(delay_min * 60 + random.randint(0, 59))
                    # Re-check that we're still in the window
                    now_msk = datetime.now(MSK)
                    if not _in_time_window(now_msk, active_window[0], active_window[1]):
                        continue

            # Run the scan
            await _run_timeline_scan(app, label=f"окно {wk}")
            completed_windows[wk] = datetime.now(MSK)

        except Exception as e:
            logger.error(f"Timeline scan loop error: {e}", exc_info=True)
            await asyncio.sleep(300)
