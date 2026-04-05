"""Main monitoring loop — fetches Twitter list every 30 min."""
import asyncio
import logging
from telegram.ext import Application

import database as db
from scraper import fetch_list_tweets, matches_keywords
from ai_processor import process_tweet
from bot import send_tweet_to_chat
from config import CHECK_INTERVAL_SEC, TG_CHAT_ID, TWITTER_LIST_ID

logger = logging.getLogger(__name__)


async def monitor_loop(app: Application):
    """Main loop: fetch list tweets every 30 min, filter by per-account tags."""
    logger.info("Monitor loop started")

    if not TWITTER_LIST_ID:
        logger.warning("TWITTER_LIST_ID not set — monitor will wait for it")

    while True:
        try:
            if not TWITTER_LIST_ID:
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue

            logger.info("Fetching Twitter list...")
            tweets = await fetch_list_tweets()

            if not tweets:
                logger.info("No tweets fetched (check cookies/list_id)")
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue

            logger.info(f"Processing {len(tweets)} tweets...")
            monitored = set(db.list_accounts())
            matched = []

            for tweet in tweets:
                # Skip already seen
                if db.is_seen(tweet.tweet_id):
                    continue

                # Only process tweets from monitored accounts
                if tweet.username not in monitored:
                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    continue

                # Per-account keywords & exclusions
                acct_keywords = db.list_account_keywords(tweet.username)
                acct_exclusions = db.list_account_exclusions(tweet.username)

                if not matches_keywords(tweet, acct_keywords, acct_exclusions):
                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    continue

                logger.info(f"Match! @{tweet.username}: {tweet.tweet_id}")
                matched.append(tweet)
                db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)

            # Process matched tweets one by one (queue)
            if matched:
                logger.info(f"Processing {len(matched)} matched tweets through AI...")
            for tweet in matched:
                try:
                    ai_result = await process_tweet(tweet.text, tweet.username)
                    if TG_CHAT_ID:
                        await send_tweet_to_chat(app, TG_CHAT_ID, tweet.username, tweet.url, ai_result)
                    await asyncio.sleep(3)  # Rate limit: AI + TG
                except Exception as e:
                    logger.error(f"Error processing @{tweet.username}/{tweet.tweet_id}: {e}")

        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)

        await asyncio.sleep(CHECK_INTERVAL_SEC)
