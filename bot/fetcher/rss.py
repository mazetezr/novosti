import asyncio
import feedparser
import logging
from datetime import datetime, timezone
from time import mktime

from bot.fetcher.models import NewsItem
from bot.cursor.manager import get_topics, get_stopwords

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    # Global / wire
    ("Reuters World", "https://feeds.reuters.com/reuters/worldNews"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Associated Press", "https://apnews.com/rss"),
    ("Axios World", "https://api.axios.com/feed/"),
    # Middle East / Iran
    ("Middle East Eye", "https://www.middleeasteye.net/rss"),
    ("Times of Israel", "https://www.timesofisrael.com/feed/"),
    ("Iran International", "https://www.iranintl.com/en/rss"),
    # Ukraine / Russia
    ("ISW", "https://www.understandingwar.org/rss.xml"),
    ("Kyiv Independent", "https://kyivindependent.com/feed/"),
    ("Kyiv Post", "https://www.kyivpost.com/rss"),
    ("UNIAN", "https://www.unian.info/rss/news.rss"),
    # Defense
    ("Defense News", "https://www.defensenews.com/rss/"),
    # Crypto (geopolitical)
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    # Markets / Energy
    ("CNBC World", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("OilPrice", "https://oilprice.com/rss/main"),
]


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def _has_stopword(text: str, stopwords: list[str]) -> bool:
    lower = text.lower()
    return any(sw.lower() in lower for sw in stopwords)


def _parse_feed(name: str, url: str) -> tuple[str, object]:
    """Blocking feedparser call — runs in thread executor."""
    return name, feedparser.parse(url)


def _extract_items(
    name: str,
    feed,
    keywords: list[str],
    stopwords: list[str],
    cursor_ts: float,
) -> list[NewsItem]:
    items = []
    for entry in feed.entries:
        link = entry.get("link", "")
        if not link:
            continue

        title = entry.get("title", "")
        summary = entry.get("summary", "")
        text = f"{title} {summary}"

        if not _matches_keywords(text, keywords):
            continue
        if _has_stopword(text, stopwords) and not _matches_keywords(title, keywords):
            continue

        pub = entry.get("published_parsed")
        if pub:
            pub_ts = mktime(pub)
            if pub_ts <= cursor_ts:
                continue
            pub_str = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
        else:
            pub_str = datetime.now(timezone.utc).isoformat()

        items.append(NewsItem(title=title.strip(), url=link, source=name, published=pub_str))
    return items


async def fetch_rss(cursor_dt: datetime) -> list[NewsItem]:
    keywords = await get_topics()
    stopwords = await get_stopwords()
    cursor_ts = cursor_dt.timestamp()
    loop = asyncio.get_event_loop()

    # Fetch all feeds in parallel via thread executor
    tasks = [
        loop.run_in_executor(None, _parse_feed, name, url)
        for name, url in RSS_FEEDS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[NewsItem] = []
    seen_urls: set[str] = set()

    for result in results:
        if isinstance(result, Exception):
            logger.warning("RSS fetch error: %s", result)
            continue
        name, feed = result
        try:
            feed_items = _extract_items(name, feed, keywords, stopwords, cursor_ts)
            for item in feed_items:
                if item.url not in seen_urls:
                    seen_urls.add(item.url)
                    items.append(item)
        except Exception as e:
            logger.warning("RSS parse error for '%s': %s", name, e)

    logger.info("RSS fetched %d articles from %d feeds", len(items), len(RSS_FEEDS))
    return items
