"""Main monitoring loop — fetches Twitter list on schedule or interval."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from telegram.ext import Application

import database as db
from scraper import fetch_list_tweets, fetch_list_members, matches_keywords
from ai_processor import process_tweet
from bot import send_tweet_to_chat
from config import TG_CHAT_ID, TWITTER_LIST_ID, get_schedule_mode, get_schedule_times, get_interval_min, get_sleep_window

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

# Track error state to avoid spamming
_last_error_notified: str | None = None
# Track manual-not-in-list notifications (only send once per user)
_notified_manual_missing: set[str] = set()


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
        db.add_account_keyword(new_user, "winners")
        logger.info(f"Auto-added @{new_user} with default tag 'winners'")
        if TG_CHAT_ID:
            try:
                await app.bot.send_message(
                    chat_id=TG_CHAT_ID,
                    text=f"🆕 Новый аккаунт из списка: **@{new_user}**\nТег по умолчанию: `winners`\nНастроить: /pages",
                    parse_mode="Markdown",
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

            for tweet in tweets:
                if db.is_seen(tweet.tweet_id):
                    continue

                if tweet.username not in monitored:
                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    continue

                acct_keywords = db.list_account_keywords(tweet.username)
                acct_exclusions = db.list_account_exclusions(tweet.username)

                if not matches_keywords(tweet, acct_keywords, acct_exclusions):
                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    continue

                logger.info(f"Match! @{tweet.username}: {tweet.tweet_id}")
                matched.append(tweet)
                db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)

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
        logger.info(f"Next check in {wait/60:.1f} min")
        await asyncio.sleep(wait)
