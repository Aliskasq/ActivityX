"""Fetch tweets from Twitter using direct GraphQL API (cookie-based auth)."""
import json
import logging
import os
from dataclasses import dataclass

import httpx

from config import COOKIES_PATH, TWITTER_LIST_ID

logger = logging.getLogger(__name__)

BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
LIST_GQL_HASH = "HjsWc-nwwHKYwHenbHm-tw"
GQL_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "communities_web_enable_tweet_community_results_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

_cookies: dict | None = None


@dataclass
class Tweet:
    tweet_id: str
    username: str
    text: str
    url: str
    timestamp: str


def _load_cookies() -> dict | None:
    global _cookies
    if _cookies is not None:
        return _cookies
    if not os.path.exists(COOKIES_PATH):
        logger.error(f"cookies.json not found at {COOKIES_PATH}")
        return None
    try:
        with open(COOKIES_PATH) as f:
            data = json.load(f)
        # Normalize wrapped format
        if isinstance(data, dict) and "cookies" in data:
            cookies_list = data["cookies"]
            data = {c["name"]: c["value"] for c in cookies_list if "name" in c and "value" in c}
            with open(COOKIES_PATH, "w") as f:
                json.dump(data, f, indent=2)
        elif isinstance(data, list):
            data = {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
            with open(COOKIES_PATH, "w") as f:
                json.dump(data, f, indent=2)
        _cookies = data
        logger.info(f"Loaded {len(data)} cookies")
        return _cookies
    except Exception as e:
        logger.error(f"Failed to load cookies: {e}")
        return None


def reset_client():
    global _cookies
    _cookies = None


def _normalize_cookies(path: str):
    """Normalize cookie file to {name: value} dict."""
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict) and "cookies" in data:
            simple = {c["name"]: c["value"] for c in data["cookies"] if "name" in c}
            with open(path, "w") as f:
                json.dump(simple, f, indent=2)
            logger.info(f"Normalized cookies: {len(simple)} entries")
        elif isinstance(data, list):
            simple = {c["name"]: c["value"] for c in data if "name" in c}
            with open(path, "w") as f:
                json.dump(simple, f, indent=2)
            logger.info(f"Normalized cookies: {len(simple)} entries")
    except Exception as e:
        logger.error(f"Cookie normalization failed: {e}")


def _build_headers(cookies: dict) -> dict:
    return {
        "authorization": BEARER,
        "x-csrf-token": cookies.get("ct0", ""),
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "referer": "https://x.com/",
    }


def _parse_tweets(data: dict) -> list[Tweet]:
    """Extract tweets from GraphQL response."""
    tweets = []
    try:
        instructions = data["data"]["list"]["tweets_timeline"]["timeline"]["instructions"]
        for instruction in instructions:
            entries = instruction.get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                if content.get("__typename") != "TimelineTimelineItem":
                    continue
                result = content.get("itemContent", {}).get("tweet_results", {}).get("result", {})
                if not result:
                    continue
                # Handle tweet with tombstone or limited visibility
                if result.get("__typename") == "TweetWithVisibilityResults":
                    result = result.get("tweet", result)
                legacy = result.get("legacy", {})
                core = result.get("core", {}).get("user_results", {}).get("result", {})
                user_legacy = core.get("legacy", {})
                username = user_legacy.get("screen_name", "unknown").lower()
                tweet_id = legacy.get("id_str", "")
                # Prefer note_tweet (full text for long tweets 280+)
                note = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
                text = note.get("text", "") or legacy.get("full_text", "")
                created_at = legacy.get("created_at", "")
                if tweet_id:
                    tweets.append(Tweet(
                        tweet_id=tweet_id,
                        username=username,
                        text=text,
                        url=f"https://x.com/{username}/status/{tweet_id}",
                        timestamp=created_at,
                    ))
    except (KeyError, TypeError) as e:
        logger.error(f"Error parsing tweets: {e}")
    return tweets


async def fetch_list_tweets(list_id: str | None = None) -> list[Tweet]:
    """Fetch latest tweets from a Twitter list via GraphQL."""
    cookies = _load_cookies()
    if not cookies:
        return []

    lid = list_id or TWITTER_LIST_ID
    if not lid:
        logger.error("TWITTER_LIST_ID not set")
        return []

    headers = _build_headers(cookies)
    variables = json.dumps({"listId": lid, "count": 40})
    features = json.dumps(GQL_FEATURES)
    url = f"https://x.com/i/api/graphql/{LIST_GQL_HASH}/ListLatestTweetsTimeline"

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                headers=headers,
                params={"variables": variables, "features": features},
                timeout=20,
                follow_redirects=True,
            )
        if r.status_code != 200:
            logger.error(f"Twitter API error {r.status_code}: {r.text[:200]}")
            if r.status_code in (401, 403):
                reset_client()
            return []

        data = r.json()
        tweets = _parse_tweets(data)
        logger.info(f"Got {len(tweets)} tweets from list {lid}")
        return tweets

    except Exception as e:
        logger.error(f"Error fetching list tweets: {e}", exc_info=True)
        reset_client()
        return []


async def fetch_user_tweets(username: str) -> list[Tweet]:
    """Fetch latest tweets from a specific user (fallback, not used with lists)."""
    return []


def matches_keywords(tweet: Tweet, keywords: list[str], exclusions: list[str] | None = None) -> bool:
    """Check if tweet matches keyword rules and doesn't hit exclusions."""
    text_lower = tweet.text.lower()

    if exclusions:
        for ex in exclusions:
            if ex.lower() in text_lower:
                return False

    if not keywords:
        return True

    for kw in keywords:
        kw_lower = kw.lower()
        if "+" in kw_lower:
            parts = [p.strip() for p in kw_lower.split("+") if p.strip()]
            if parts and all(part in text_lower for part in parts):
                return True
        else:
            if kw_lower in text_lower:
                return True
    return False
