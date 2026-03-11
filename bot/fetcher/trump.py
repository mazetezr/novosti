import aiohttp
import html as html_module
import logging
import re
from datetime import datetime, timezone

from bot.fetcher.models import NewsItem
from bot.cursor.manager import get_topics, get_stopwords

logger = logging.getLogger(__name__)

# Публичный архив постов Трампа с Truth Social (CNN/GitHub, обновляется каждые 5 мин)
TRUTH_SOCIAL_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
MAX_TRUMP_POSTS = 20


def _strip_html(text: str) -> str:
    """Убрать HTML-теги и раскодировать entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def _has_stopword(text: str, stopwords: list[str]) -> bool:
    lower = text.lower()
    return any(sw.lower() in lower for sw in stopwords)


async def fetch_trump(cursor_dt: datetime) -> list[NewsItem]:
    """Получить посты Трампа с Truth Social, отфильтровать по темам бота."""
    keywords = await get_topics()
    stopwords = await get_stopwords()
    items: list[NewsItem] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                TRUTH_SOCIAL_ARCHIVE_URL,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Trump archive вернул HTTP %d", resp.status)
                    return []
                posts = await resp.json(content_type=None)

        if not isinstance(posts, list):
            logger.warning("Неожиданный формат архива Трампа: %s", type(posts))
            return []

        for post in posts:
            url = post.get("url", "")
            if not url:
                continue

            created_at_str = post.get("created_at", "")
            if not created_at_str:
                continue

            try:
                pub_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except ValueError:
                continue

            # Пропускаем посты старше курсора
            if pub_dt <= cursor_dt:
                continue

            content_raw = post.get("content", "")
            text = _strip_html(content_raw)
            if not text:
                continue

            # Фильтрация по ключевым словам (Иран, нефть, конфликт и т.д.)
            if not _matches_keywords(text, keywords):
                continue
            if _has_stopword(text, stopwords) and not _matches_keywords(text, keywords):
                continue

            # Используем первые 200 символов как "заголовок"
            title = (text[:197] + "...") if len(text) > 200 else text

            items.append(NewsItem(
                title=title,
                url=url,
                source="Trump (Truth Social)",
                published=pub_dt.isoformat(),
            ))

        # Сортируем по дате (новые вперёд), берём не более MAX_TRUMP_POSTS
        items.sort(key=lambda x: x.published, reverse=True)
        items = items[:MAX_TRUMP_POSTS]

    except Exception as e:
        logger.warning("Ошибка загрузки архива Trump Truth Social: %s", e)
        return []

    logger.info("Trump Truth Social: найдено %d релевантных постов", len(items))
    return items
