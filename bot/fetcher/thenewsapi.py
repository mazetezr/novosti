import aiohttp
import logging
from datetime import datetime

from bot.config import THENEWSAPI_KEY
from bot.cursor.manager import get_stopwords, get_topics
from bot.fetcher.models import NewsItem
from bot.utils.news_priority import (
    build_api_search_query,
    has_stopword_signal,
    is_quality_api_article,
    is_relevant_article,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.thenewsapi.com/v1/news/all"


async def fetch_thenewsapi(cursor_dt: datetime) -> list[NewsItem]:
    keywords = await get_topics()
    stopwords = await get_stopwords()
    search_query = build_api_search_query(keywords)
    params = {
        "api_token": THENEWSAPI_KEY,
        "search": search_query,
        "search_fields": "title",
        "language": "en",
        "published_after": cursor_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "limit": "50",
    }
    items: list[NewsItem] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("TheNewsAPI returned %d: %s", resp.status, body[:300])
                    return []
                data = await resp.json()
                for art in data.get("data", []):
                    url = art.get("url", "")
                    title = art.get("title", "").strip()
                    summary = art.get("description", "") or ""
                    source = art.get("source", "TheNewsAPI")
                    if not url or not title:
                        continue
                    if not is_quality_api_article(title, url, source):
                        continue
                    if not is_relevant_article(title, summary, url, keywords):
                        continue
                    if has_stopword_signal(f"{title} {summary}", stopwords) and not is_relevant_article(title, "", url, keywords):
                        continue

                    items.append(
                        NewsItem(
                            title=title,
                            url=url,
                            source=source,
                            published=art.get("published_at", ""),
                        )
                    )
    except Exception as e:
        logger.warning("TheNewsAPI error: %s", e)

    logger.info("TheNewsAPI fetched %d articles", len(items))
    return items
