"""Main monitoring loop — fetches Twitter list on schedule or interval."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from telegram.ext import Application

import database as db
from scraper import fetch_list_tweets, matches_keywords
from ai_processor import process_tweet
from bot import send_tweet_to_chat
from config import TG_CHAT_ID, TWITTER_LIST_ID, get_schedule_mode, get_schedule_times, get_interval_min

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


def _seconds_until_next_run() -> float:
    """Calculate seconds until the next scheduled run."""
    mode = get_schedule_mode()

    if mode == "interval":
        return get_interval_min() * 60

    # Schedule mode — find next MSK time
    times = get_schedule_times()
    if not times:
        return 1800  # fallback 30 min

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
    return max(delta, 10)  # minimum 10 sec safety


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

            logger.info("Fetching Twitter list...")
            tweets = await fetch_list_tweets()

            if not tweets:
                logger.info("No tweets fetched (check cookies/list_id)")
                wait = _seconds_until_next_run()
                logger.info(f"Next check in {wait/60:.1f} min")
                await asyncio.sleep(wait)
                continue

            logger.info(f"Processing {len(tweets)} tweets...")
            monitored = set(db.list_accounts())
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
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.error(f"Error processing @{tweet.username}/{tweet.tweet_id}: {e}")

        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)

        wait = _seconds_until_next_run()
        logger.info(f"Next check in {wait/60:.1f} min")
        await asyncio.sleep(wait)
