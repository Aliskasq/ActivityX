"""Main monitoring loop — rotates through accounts, checks for new tweets."""
import asyncio
import logging
import httpx
from telegram.ext import Application

import database as db
from scraper import fetch_nitter_rss, matches_keywords
from ai_processor import process_tweet
from bot import send_tweet_to_chat
from config import CHECK_INTERVAL_SEC, TG_CHAT_ID

logger = logging.getLogger(__name__)


async def monitor_loop(app: Application):
    """Main loop: rotate through accounts, one per minute."""
    logger.info("Monitor loop started")
    idx = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    ) as client:
        while True:
            try:
                accounts = db.list_accounts()
                if not accounts:
                    logger.debug("No accounts to monitor, sleeping...")
                    await asyncio.sleep(CHECK_INTERVAL_SEC)
                    continue

                # Rotate
                username = accounts[idx % len(accounts)]
                idx = (idx + 1) % len(accounts)

                logger.info(f"Checking @{username} ({idx}/{len(accounts)})")

                # Fetch tweets
                tweets = await fetch_nitter_rss(username, client)

                # Get per-account keywords (fall back to global if none set)
                acct_keywords = db.list_account_keywords(username)
                if not acct_keywords:
                    acct_keywords = db.list_keywords()

                for tweet in tweets:
                    if db.is_seen(tweet.tweet_id):
                        continue

                    if not matches_keywords(tweet, acct_keywords):
                        db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                        continue

                    logger.info(f"New matching tweet from @{username}: {tweet.tweet_id}")

                    ai_result = await process_tweet(tweet.text, tweet.username)

                    chat_id = TG_CHAT_ID
                    if chat_id:
                        await send_tweet_to_chat(app, chat_id, username, tweet.url, ai_result)

                    db.mark_seen(tweet.tweet_id, tweet.username, tweet.text)
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Monitor error: {e}", exc_info=True)

            await asyncio.sleep(CHECK_INTERVAL_SEC)
