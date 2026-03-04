import aiohttp
import logging
from datetime import datetime

from bot.config import THENEWSAPI_KEY
from bot.fetcher.models import NewsItem
from bot.cursor.manager import get_topics

logger = logging.getLogger(__name__)

API_URL = "https://api.thenewsapi.com/v1/news/all"


async def fetch_thenewsapi(cursor_dt: datetime) -> list[NewsItem]:
    keywords = await get_topics()
    # TheNewsAPI: use | for OR logic, limit to top keywords to avoid too-long query
    top_keywords = keywords[:30] if len(keywords) > 30 else keywords
    search_query = " | ".join(top_keywords) if top_keywords else "war | conflict | Iran | Israel | Ukraine"
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
                    if url:
                        items.append(
                            NewsItem(
                                title=art.get("title", "").strip(),
                                url=url,
                                source=art.get("source", "TheNewsAPI"),
                                published=art.get("published_at", ""),
                            )
                        )
    except Exception as e:
        logger.warning("TheNewsAPI error: %s", e)

    logger.info("TheNewsAPI fetched %d articles", len(items))
    return items
