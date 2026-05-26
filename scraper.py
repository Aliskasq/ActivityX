"""Fetch tweets from Twitter using direct GraphQL API (cookie-based auth)."""
import asyncio
import json
import logging
import os
from dataclasses import dataclass

import httpx

from config import COOKIES_PATH, TWITTER_LIST_ID

logger = logging.getLogger(__name__)

import re as _re

BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
LIST_GQL_HASH = "EaZggwYxthCW30dKBN807Q"
MEMBERS_GQL_HASH = "qC0uLn_94QWJSpRZzzaJ-A"
USER_TWEETS_GQL_HASH = "3AS73VJOTCg8ePuvJndFew"
USER_BY_SCREEN_NAME_GQL_HASH = "IGgvgiOx4QZndDHuD3x9TQ"

# Operations we track for auto-update
_GQL_OPERATIONS = {
    "ListLatestTweetsTimeline": "LIST_GQL_HASH",
    "ListMembers": "MEMBERS_GQL_HASH",
    "UserTweets": "USER_TWEETS_GQL_HASH",
    "UserByScreenName": "USER_BY_SCREEN_NAME_GQL_HASH",
}

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

MEMBERS_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}

_cookies: dict | None = None


def _find_key(obj, key: str) -> list:
    """Recursively find all values for a given key in nested dicts/lists."""
    results = []
    if isinstance(obj, dict):
        if key in obj and obj[key]:
            results.append(obj[key])
        for v in obj.values():
            results.extend(_find_key(v, key))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_find_key(item, key))
    return results


def _find_screen_name(user_result: dict) -> str | None:
    """Extract screen_name from a user result object (handles API changes)."""
    # Try legacy.screen_name first (old format)
    legacy = user_result.get("legacy", {})
    if legacy.get("screen_name"):
        return legacy["screen_name"]
    # Try core.screen_name
    core = user_result.get("core", {})
    if core.get("screen_name"):
        return core["screen_name"]
    # Recursive search as fallback
    found = _find_key(user_result, "screen_name")
    if found:
        return found[0]
    return None


@dataclass
class Tweet:
    tweet_id: str
    username: str
    text: str
    url: str
    timestamp: str
    images: list[str] = None  # List of image URLs

    def __post_init__(self):
        if self.images is None:
            self.images = []


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


async def fetch_gql_hashes() -> dict[str, str]:
    """Fetch current GQL hashes from Twitter's JS bundles.

    Returns dict like {"UserTweets": "abc123", "ListLatestTweetsTimeline": "def456", ...}
    """
    found: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            # Step 1: Get main page to find JS bundle URLs
            r = await client.get("https://x.com", headers={
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            # Find all JS bundle URLs
            js_urls = _re.findall(r'https://abs\.twimg\.com/responsive-web/client-web[^"\']+\.js', r.text)
            if not js_urls:
                # Try alternative pattern
                js_urls = _re.findall(r'https://abs\.twimg\.com/responsive-web/[^"\']+\.js', r.text)
            logger.info(f"[fix_hashes] Found {len(js_urls)} JS bundles")

            # Step 2: Search each bundle for operation hashes
            operations = set(_GQL_OPERATIONS.keys())
            for js_url in js_urls:
                if len(found) == len(operations):
                    break
                try:
                    jr = await client.get(js_url, headers={
                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    })
                    js_text = jr.text

                    # Pattern: queryId:"hash",operationName:"OpName"
                    # or operationName:"OpName",... queryId:"hash"
                    for op in operations - set(found.keys()):
                        # Try pattern 1: queryId before operationName
                        m = _re.search(
                            r'queryId\s*:\s*"([A-Za-z0-9_-]+)"[^}]{0,100}operationName\s*:\s*"'
                            + _re.escape(op) + r'"',
                            js_text,
                        )
                        if not m:
                            # Try pattern 2: operationName before queryId
                            m = _re.search(
                                r'operationName\s*:\s*"' + _re.escape(op)
                                + r'"[^}]{0,100}queryId\s*:\s*"([A-Za-z0-9_-]+)"',
                                js_text,
                            )
                        if m:
                            found[op] = m.group(1)
                            logger.info(f"[fix_hashes] {op} -> {m.group(1)}")
                except Exception as e:
                    logger.debug(f"[fix_hashes] Error reading {js_url}: {e}")
                    continue

    except Exception as e:
        logger.error(f"[fix_hashes] Error fetching JS bundles: {e}", exc_info=True)

    return found


async def auto_fix_hashes() -> dict:
    """Fetch new GQL hashes, validate them, and update in-memory + scraper.py.

    Returns {"updated": [...], "failed": [...], "unchanged": [...]}
    """
    global LIST_GQL_HASH, MEMBERS_GQL_HASH, USER_TWEETS_GQL_HASH, USER_BY_SCREEN_NAME_GQL_HASH

    new_hashes = await fetch_gql_hashes()
    if not new_hashes:
        return {"updated": [], "failed": ["Не удалось извлечь хеши из JS бандлов"], "unchanged": []}

    current = {
        "ListLatestTweetsTimeline": LIST_GQL_HASH,
        "ListMembers": MEMBERS_GQL_HASH,
        "UserTweets": USER_TWEETS_GQL_HASH,
        "UserByScreenName": USER_BY_SCREEN_NAME_GQL_HASH,
    }

    updated = []
    failed = []
    unchanged = []

    # Validate each new hash with a test request
    cookies = _load_cookies()
    headers = _build_headers(cookies) if cookies else {}

    for op, new_hash in new_hashes.items():
        old_hash = current.get(op, "")
        if new_hash == old_hash:
            unchanged.append(op)
            continue

        # Test the new hash
        valid = False
        if cookies and headers:
            try:
                if op == "UserByScreenName":
                    test_url = f"https://x.com/i/api/graphql/{new_hash}/UserByScreenName"
                    test_vars = json.dumps({"screen_name": "binance"})
                    test_features = json.dumps(GQL_FEATURES)
                elif op == "UserTweets":
                    test_url = f"https://x.com/i/api/graphql/{new_hash}/UserTweets"
                    test_vars = json.dumps({"userId": "877807935493033984", "count": 1,
                                            "includePromotedContent": False, "withV2Timeline": True})
                    test_features = json.dumps(GQL_FEATURES)
                elif op == "ListLatestTweetsTimeline":
                    from config import TWITTER_LIST_ID as _lid
                    test_url = f"https://x.com/i/api/graphql/{new_hash}/ListLatestTweetsTimeline"
                    test_vars = json.dumps({"listId": _lid or "0", "count": 1})
                    test_features = json.dumps(GQL_FEATURES)
                elif op == "ListMembers":
                    from config import TWITTER_LIST_ID as _lid
                    test_url = f"https://x.com/i/api/graphql/{new_hash}/ListMembers"
                    test_vars = json.dumps({"listId": _lid or "0", "count": 1})
                    test_features = json.dumps(MEMBERS_FEATURES)
                else:
                    valid = True  # Unknown op, trust it

                if not valid:
                    async with httpx.AsyncClient() as client:
                        tr = await client.get(
                            test_url, headers=headers,
                            params={"variables": test_vars, "features": test_features},
                            timeout=15, follow_redirects=True,
                        )
                    valid = tr.status_code == 200
                    logger.info(f"[fix_hashes] Test {op}: {new_hash} -> {tr.status_code}")
            except Exception as e:
                logger.error(f"[fix_hashes] Test {op} failed: {e}")
                valid = False
        else:
            # No cookies — accept without validation
            valid = True

        if valid:
            # Update in-memory
            if op == "ListLatestTweetsTimeline":
                LIST_GQL_HASH = new_hash
            elif op == "ListMembers":
                MEMBERS_GQL_HASH = new_hash
            elif op == "UserTweets":
                USER_TWEETS_GQL_HASH = new_hash
            elif op == "UserByScreenName":
                USER_BY_SCREEN_NAME_GQL_HASH = new_hash

            # Update scraper.py file
            var_name = _GQL_OPERATIONS[op]
            _update_hash_in_file(var_name, new_hash)
            updated.append(f"{op}: {old_hash} → {new_hash}")
        else:
            failed.append(f"{op}: новый хеш {new_hash} не прошёл проверку")

    return {"updated": updated, "failed": failed, "unchanged": unchanged}


def _update_hash_in_file(var_name: str, new_hash: str):
    """Update a GQL hash variable in scraper.py on disk."""
    try:
        filepath = os.path.join(os.path.dirname(__file__), "scraper.py")
        with open(filepath, "r") as f:
            content = f.read()
        # Match: VAR_NAME = "old_hash"
        pattern = _re.compile(r'(' + _re.escape(var_name) + r'\s*=\s*")[^"]*(")')
        new_content = pattern.sub(r'\g<1>' + new_hash + r'\2', content, count=1)
        if new_content != content:
            with open(filepath, "w") as f:
                f.write(new_content)
            logger.info(f"[fix_hashes] Updated {var_name} = {new_hash!r} in scraper.py")
    except Exception as e:
        logger.error(f"[fix_hashes] Failed to update {var_name} in file: {e}")


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


def _parse_tweet_entries(instructions: list, fallback_username: str | None = None) -> list[Tweet]:
    """Parse tweet entries from GraphQL instructions (shared by list and user timeline).

    Args:
        fallback_username: if set, used when screen_name can't be extracted from tweet.
    """
    tweets = []
    for instruction in instructions:
        entries = instruction.get("entries", [])
        # Include pinned tweet (singular "entry" key)
        pinned = instruction.get("entry")
        if pinned:
            entries = list(entries) + [pinned]
        # Flatten: include module sub-items (profile-conversation threads)
        flat_items = []
        for entry in entries:
            content = entry.get("content", {})
            typename = content.get("__typename", "")
            if typename == "TimelineTimelineItem":
                flat_items.append(content)
            elif typename == "TimelineTimelineModule":
                for sub in content.get("items", []):
                    sub_item = sub.get("item", {})
                    if sub_item:
                        flat_items.append(sub_item)
        for content in flat_items:
            result = content.get("itemContent", {}).get("tweet_results", {}).get("result", {})
            if not result:
                continue
            # Handle tweet with tombstone or limited visibility
            if result.get("__typename") == "TweetWithVisibilityResults":
                result = result.get("tweet", result)
            legacy = result.get("legacy", {})
            core = result.get("core", {}).get("user_results", {}).get("result", {})
            # Extract screen_name (handles API structure changes)
            screen = _find_screen_name(core)
            username = (screen.lower() if screen else None) or (
                fallback_username.lower() if fallback_username else "unknown"
            )
            tweet_id = legacy.get("id_str", "")
            # Prefer note_tweet (full text for long tweets 280+)
            note = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
            text = note.get("text", "") or legacy.get("full_text", "")
            created_at = legacy.get("created_at", "")
            # Extract images
            images = []
            media_list = legacy.get("entities", {}).get("media", [])
            if not media_list:
                media_list = legacy.get("extended_entities", {}).get("media", [])
            for media in media_list:
                if media.get("type") == "photo":
                    img_url = media.get("media_url_https", "")
                    if img_url:
                        images.append(img_url)

            if tweet_id:
                tweets.append(Tweet(
                    tweet_id=tweet_id,
                    username=username,
                    text=text,
                    url=f"https://x.com/{username}/status/{tweet_id}",
                    timestamp=created_at,
                    images=images,
                ))
    return tweets


def _parse_tweets(data: dict) -> list[Tweet]:
    """Extract tweets from list GraphQL response."""
    try:
        instructions = data["data"]["list"]["tweets_timeline"]["timeline"]["instructions"]
        return _parse_tweet_entries(instructions)
    except (KeyError, TypeError) as e:
        logger.error(f"Error parsing list tweets: {e}")
        return []


def _parse_user_tweets(data: dict, fallback_username: str | None = None) -> list[Tweet]:
    """Extract tweets from user timeline GraphQL response."""
    try:
        user_result = data["data"]["user"]["result"]
        timeline = user_result.get("timeline_v2") or user_result.get("timeline")
        instructions = timeline["timeline"]["instructions"]
        return _parse_tweet_entries(instructions, fallback_username=fallback_username)
    except (KeyError, TypeError) as e:
        logger.error(f"Error parsing user tweets: {e}")
        return []


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
    variables = json.dumps({"listId": lid, "count": 100})
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


async def fetch_list_members(list_id: str | None = None) -> set[str]:
    """Fetch actual members of a Twitter list via GraphQL ListMembers."""
    cookies = _load_cookies()
    if not cookies:
        return set()

    lid = list_id or TWITTER_LIST_ID
    if not lid:
        logger.error("TWITTER_LIST_ID not set")
        return set()

    headers = _build_headers(cookies)
    variables = json.dumps({"listId": lid, "count": 200})
    features = json.dumps(MEMBERS_FEATURES)
    url = f"https://x.com/i/api/graphql/{MEMBERS_GQL_HASH}/ListMembers"

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
            logger.error(f"ListMembers API error {r.status_code}: {r.text[:200]}")
            if r.status_code in (401, 403):
                reset_client()
            return set()

        data = r.json()
        members = set()
        try:
            instructions = data["data"]["list"]["members_timeline"]["timeline"]["instructions"]
            for instruction in instructions:
                entries = instruction.get("entries", [])
                for entry in entries:
                    content = entry.get("content", {})
                    if content.get("__typename") != "TimelineTimelineItem":
                        continue
                    result = content.get("itemContent", {}).get("user_results", {}).get("result", {})
                    if not result:
                        continue
                    screen_name = _find_screen_name(result)
                    if screen_name:
                        members.add(screen_name.lower())
                        # Cache user rest_id for timeline fetching
                        rest_id = result.get("rest_id")
                        if rest_id:
                            import database as db_mod
                            db_mod.set_cached_user_id(screen_name.lower(), rest_id)
        except (KeyError, TypeError) as e:
            logger.error(f"Error parsing list members: {e}")

        logger.info(f"Got {len(members)} members from list {lid}")
        return members

    except Exception as e:
        logger.error(f"Error fetching list members: {e}", exc_info=True)
        return set()


async def _resolve_user_id(screen_name: str, cookies: dict, headers: dict) -> str | None:
    """Resolve screen_name to Twitter rest_id via GraphQL."""
    import database as db_mod
    # Check cache first
    cached = db_mod.get_cached_user_id(screen_name)
    if cached:
        return cached

    variables = json.dumps({"screen_name": screen_name, "withSafetyModeUserFields": True})
    features = json.dumps(MEMBERS_FEATURES)
    url = f"https://x.com/i/api/graphql/{USER_BY_SCREEN_NAME_GQL_HASH}/UserByScreenName"

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
            logger.error(f"UserByScreenName error {r.status_code} for @{screen_name}")
            return None
        data = r.json()
        rest_id = data.get("data", {}).get("user", {}).get("result", {}).get("rest_id")
        if rest_id:
            db_mod.set_cached_user_id(screen_name, rest_id)
            logger.info(f"Resolved @{screen_name} → {rest_id}")
        return rest_id
    except Exception as e:
        logger.error(f"Error resolving user id for @{screen_name}: {e}")
        return None


def _extract_bottom_cursor(data: dict, mode: str = "user") -> str | None:
    """Extract the bottom cursor from a GraphQL timeline response for pagination."""
    try:
        if mode == "user":
            user_result = data["data"]["user"]["result"]
            timeline = user_result.get("timeline_v2") or user_result.get("timeline")
            instructions = timeline["timeline"]["instructions"]
        else:
            instructions = data["data"]["list"]["tweets_timeline"]["timeline"]["instructions"]

        for instruction in instructions:
            entries = instruction.get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                if content.get("__typename") == "TimelineTimelineCursor" and \
                   content.get("cursorType") == "Bottom":
                    return content.get("value")
                # Also check entryType pattern
                if entry.get("entryId", "").startswith("cursor-bottom"):
                    return content.get("value")
    except (KeyError, TypeError):
        pass
    return None


async def fetch_user_tweets(username: str, count: int = 20) -> list[Tweet]:
    """Fetch latest tweets from a specific user's timeline via GraphQL.

    Uses cursor-based pagination to fetch up to `count` tweets.
    """
    cookies = _load_cookies()
    if not cookies:
        return []

    headers = _build_headers(cookies)
    username = username.strip().lstrip("@").lower()

    # Resolve user_id
    user_id = await _resolve_user_id(username, cookies, headers)
    if not user_id:
        logger.error(f"Cannot fetch timeline for @{username}: no user_id")
        return []

    features = json.dumps(GQL_FEATURES)
    url = f"https://x.com/i/api/graphql/{USER_TWEETS_GQL_HASH}/UserTweets"
    all_tweets: list[Tweet] = []
    seen_ids: set[str] = set()
    cursor: str | None = None
    max_pages = 5  # Safety limit

    for page in range(max_pages):
        vars_dict = {
            "userId": user_id,
            "count": min(count, 40),  # Twitter typically caps per-page at ~40
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            vars_dict["cursor"] = cursor

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=headers,
                    params={"variables": json.dumps(vars_dict), "features": features},
                    timeout=20,
                    follow_redirects=True,
                )
            if r.status_code != 200:
                logger.error(f"UserTweets error {r.status_code} for @{username}: {r.text[:200]}")
                if r.status_code in (401, 403):
                    reset_client()
                break

            data = r.json()
            tweets = _parse_user_tweets(data, fallback_username=username)

            # Deduplicate
            new_count = 0
            for t in tweets:
                if t.tweet_id not in seen_ids:
                    seen_ids.add(t.tweet_id)
                    all_tweets.append(t)
                    new_count += 1

            logger.info(
                f"[page {page+1}] Got {len(tweets)} tweets from @{username} "
                f"(+{new_count} new, total {len(all_tweets)})"
            )

            # Enough tweets or no new results
            if len(all_tweets) >= count or new_count == 0:
                break

            # Get next page cursor
            cursor = _extract_bottom_cursor(data, mode="user")
            if not cursor:
                break

            # Small delay between pages
            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error fetching user tweets for @{username}: {e}", exc_info=True)
            break

    logger.info(f"Got {len(all_tweets)} tweets from @{username} timeline")
    return all_tweets[:count]


def _word_in_text(word: str, text: str) -> bool:
    """Check if word appears in text as a whole word (not substring).

    Uses regex word boundaries so 'rt' won't match inside 'part',
    but 'giveaway' will still match 'giveaway!' (punctuation boundary).
    """
    import re
    return bool(re.search(r'\b' + re.escape(word) + r'\b', text))


def matches_keywords(tweet: Tweet, keywords: list[str], exclusions: list[str] | None = None) -> bool:
    """Check if tweet matches keyword rules and doesn't hit exclusions."""
    text_lower = tweet.text.lower()

    if exclusions:
        for ex in exclusions:
            if _word_in_text(ex.lower(), text_lower):
                return False

    if not keywords:
        return False

    for kw in keywords:
        kw_lower = kw.lower()
        if "+" in kw_lower:
            parts = [p.strip() for p in kw_lower.split("+") if p.strip()]
            if parts and all(_word_in_text(part, text_lower) for part in parts):
                return True
        else:
            if _word_in_text(kw_lower, text_lower):
                return True
    return False
