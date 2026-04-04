"""Scrape tweets from Nitter instances."""
import re
import logging
import httpx
from dataclasses import dataclass
from config import NITTER_INSTANCES

logger = logging.getLogger(__name__)


@dataclass
class Tweet:
    tweet_id: str
    username: str
    text: str
    url: str  # original twitter/x.com link
    timestamp: str


async def fetch_nitter_rss(username: str, client: httpx.AsyncClient) -> list[Tweet]:
    """Try multiple Nitter instances to get RSS feed for a user."""
    tweets = []
    for instance in NITTER_INSTANCES:
        try:
            rss_url = f"{instance}/{username}/rss"
            resp = await client.get(rss_url, timeout=15, follow_redirects=True)
            if resp.status_code == 200:
                tweets = parse_rss(resp.text, username)
                if tweets:
                    logger.info(f"Got {len(tweets)} tweets for @{username} from {instance}")
                    return tweets
        except Exception as e:
            logger.warning(f"Nitter instance {instance} failed for @{username}: {e}")
            continue
    logger.error(f"All Nitter instances failed for @{username}")
    return tweets


def parse_rss(xml_text: str, username: str) -> list[Tweet]:
    """Parse Nitter RSS XML into Tweet objects."""
    tweets = []
    items = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    for item in items:
        title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item, re.DOTALL)
        if not title_m:
            title_m = re.search(r"<title>(.*?)</title>", item, re.DOTALL)

        link_m = re.search(r"<link>(.*?)</link>", item)
        pubdate_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
        desc_m = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", item, re.DOTALL)
        if not desc_m:
            desc_m = re.search(r"<description>(.*?)</description>", item, re.DOTALL)

        if not link_m:
            continue

        nitter_link = link_m.group(1).strip()
        tid_m = re.search(r"/status/(\d+)", nitter_link)
        if not tid_m:
            continue

        tweet_id = tid_m.group(1)
        text = ""
        if desc_m:
            text = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()
        elif title_m:
            text = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()

        x_url = f"https://x.com/{username}/status/{tweet_id}"

        tweets.append(Tweet(
            tweet_id=tweet_id,
            username=username,
            text=text,
            url=x_url,
            timestamp=pubdate_m.group(1).strip() if pubdate_m else "",
        ))
    return tweets


def matches_keywords(tweet: Tweet, keywords: list[str]) -> bool:
    """Check if tweet matches any keyword rule.
    
    Rules:
    - "word" → tweet contains "word"
    - "word1+word2" → tweet contains BOTH "word1" AND "word2"
    - Empty keywords list → all tweets pass
    """
    if not keywords:
        return True
    text_lower = tweet.text.lower()
    for kw in keywords:
        if "+" in kw:
            # Compound: ALL parts must match
            parts = [p.strip() for p in kw.split("+") if p.strip()]
            if parts and all(part in text_lower for part in parts):
                return True
        else:
            if kw in text_lower:
                return True
    return False
