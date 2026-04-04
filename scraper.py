"""Fetch tweets from Twitter using twikit (cookie-based auth)."""
import json
import logging
import os
from dataclasses import dataclass
from twikit import Client

from config import COOKIES_PATH, TWITTER_LIST_ID

logger = logging.getLogger(__name__)

_client: Client | None = None


@dataclass
class Tweet:
    tweet_id: str
    username: str
    text: str
    url: str
    timestamp: str


async def get_client() -> Client | None:
    """Get or create authenticated Twitter client."""
    global _client
    if _client is not None:
        return _client

    if not os.path.exists(COOKIES_PATH):
        logger.error(f"cookies.json not found at {COOKIES_PATH}")
        return None

    try:
        client = Client("ru")
        client.load_cookies(COOKIES_PATH)
        _client = client
        logger.info("Twitter client initialized with cookies")
        return _client
    except Exception as e:
        logger.error(f"Failed to init Twitter client: {e}")
        return None


def reset_client():
    """Reset client (e.g. after cookie update)."""
    global _client
    _client = None


async def fetch_list_tweets(list_id: str | None = None) -> list[Tweet]:
    """Fetch latest tweets from a Twitter list."""
    client = await get_client()
    if not client:
        return []

    lid = list_id or TWITTER_LIST_ID
    if not lid:
        logger.error("TWITTER_LIST_ID not set")
        return []

    tweets = []
    try:
        timeline = await client.get_list_tweets(lid)
        for t in timeline:
            username = t.user.screen_name if t.user else "unknown"
            tweets.append(Tweet(
                tweet_id=str(t.id),
                username=username.lower(),
                text=t.text or "",
                url=f"https://x.com/{username}/status/{t.id}",
                timestamp=t.created_at or "",
            ))
        logger.info(f"Got {len(tweets)} tweets from list {lid}")
    except Exception as e:
        logger.error(f"Error fetching list tweets: {e}", exc_info=True)
        # Reset client in case cookies expired
        reset_client()

    return tweets


async def fetch_user_tweets(username: str) -> list[Tweet]:
    """Fetch latest tweets from a specific user (fallback)."""
    client = await get_client()
    if not client:
        return []

    tweets = []
    try:
        user = await client.get_user_by_screen_name(username)
        if not user:
            return []
        user_tweets = await client.get_user_tweets(user.id, "Tweets")
        for t in user_tweets:
            tweets.append(Tweet(
                tweet_id=str(t.id),
                username=username.lower(),
                text=t.text or "",
                url=f"https://x.com/{username}/status/{t.id}",
                timestamp=t.created_at or "",
            ))
        logger.info(f"Got {len(tweets)} tweets from @{username}")
    except Exception as e:
        logger.error(f"Error fetching @{username}: {e}", exc_info=True)

    return tweets


def matches_keywords(tweet: Tweet, keywords: list[str], exclusions: list[str] | None = None) -> bool:
    """Check if tweet matches keyword rules and doesn't hit exclusions.

    Keywords:
    - "word" → tweet contains "word"
    - "word1+word2" → tweet contains BOTH words
    - Empty list → all tweets pass

    Exclusions:
    - If tweet contains ANY exclusion word → rejected
    """
    text_lower = tweet.text.lower()

    if exclusions:
        for ex in exclusions:
            if ex in text_lower:
                return False

    if not keywords:
        return True

    for kw in keywords:
        if "+" in kw:
            parts = [p.strip() for p in kw.split("+") if p.strip()]
            if parts and all(part in text_lower for part in parts):
                return True
        else:
            if kw in text_lower:
                return True
    return False
