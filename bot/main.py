import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import LOG_LEVEL, LOG_PATH, DB_PATH, TELEGRAM_BOT_TOKEN
from bot.cursor.manager import init_db, get_cursor, update_cursor, mark_seen, filter_seen, cleanup_seen, seed_default_topics, get_setting, save_summary, get_last_summaries
from bot.fetcher.models import NewsItem
from bot.fetcher.rss import fetch_rss
from bot.fetcher.thenewsapi import fetch_thenewsapi
from bot.summarizer.llm import summarize
from bot.poster.telegram import post_to_channel
from bot.admin.router import router as admin_router
from bot.utils.dedup import filter_by_previous_titles, cluster_similar_articles
from bot.state import set_scheduler

from datetime import datetime, timezone

# Ensure data/logs directories exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    result = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            result.append(item)
    return result


# async def _send_rejected_report(rejected: list, total: int):
#     """Format and send rejected articles list to admins."""
#     lines = [
#         f"🗑 <b>ОТСЕЯНО БОТОМ</b> — {len(rejected)} из {total} статей\n"
#         f"<i>(новости, не попавшие в сводку)</i>\n"
#     ]
#     for i, item in enumerate(rejected, 1):
#         lines.append(
#             f"{i}. <b>{item.title}</b>\n"
#             f"   <i>{item.source}</i> · <a href=\"{item.url}\">ссылка</a>"
#         )
#     await send_to_admins("\n".join(lines))


async def run_cycle():
    logger.info("=== Starting news cycle ===")
    try:
        cursor_dt = await get_cursor()
        logger.info("Cursor: %s", cursor_dt.isoformat())

        # Fetch from both sources in parallel
        rss_news, api_news = await asyncio.gather(
            fetch_rss(cursor_dt),
            fetch_thenewsapi(cursor_dt),
        )

        if not rss_news and not api_news:
            logger.warning("No news from any source, skipping cycle")
            return

        # Deduplicate across sources
        all_news = deduplicate(rss_news + api_news)
        logger.info("Total articles after dedup: %d", len(all_news))

        # Filter already seen URLs
        all_urls = [item.url for item in all_news]
        new_urls = set(await filter_seen(all_urls))
        new_news = [item for item in all_news if item.url in new_urls]
        logger.info("New articles: %d", len(new_news))

        if not new_news:
            logger.info("No new articles, skipping cycle")
            return

        # Cap articles sent to LLM — sort by published desc, take top 60
        MAX_ARTICLES = 60
        if len(new_news) > MAX_ARTICLES:
            new_news_sorted = sorted(new_news, key=lambda x: x.published, reverse=True)[:MAX_ARTICLES]
            logger.info("Capped articles from %d to %d for LLM", len(new_news), MAX_ARTICLES)
        else:
            new_news_sorted = new_news

        # Get previous summaries for anti-duplicate context
        prev_data = await get_last_summaries(5)

        # --- Python-level дедупликация (до LLM) ---
        # 1. Убрать статьи, дублирующие ранее опубликованные
        all_prev_titles: list[str] = []
        for s in prev_data:
            all_prev_titles.extend(s.get("cited_titles", []))
        if all_prev_titles:
            new_news_sorted = filter_by_previous_titles(
                new_news_sorted, all_prev_titles, threshold=0.35
            )

        # 2. Кластеризовать одинаковые события из разных источников
        new_news_sorted = cluster_similar_articles(new_news_sorted, threshold=0.30)

        if not new_news_sorted:
            logger.info("All articles filtered as duplicates, skipping cycle")
            return

        # Read news_count setting
        news_count = int(await get_setting("news_count", "5"))

        # Summarize with LLM
        summary, cited_indices = await summarize(new_news_sorted, prev_data, news_count=news_count)
        if not summary:
            logger.error("LLM returned empty summary, skipping post")
            return

        # Post to Telegram
        await post_to_channel(summary)
        logger.info("Posted to Telegram successfully")

        # Save summary + cited English titles for future anti-duplicate context
        cited_titles = [
            new_news_sorted[i - 1].title
            for i in cited_indices
            if 1 <= i <= len(new_news_sorted)
        ]
        await save_summary(summary, cited_titles)

        # Логируем отсеянные статьи (не вошли в сводку)
        rejected = [
            item for i, item in enumerate(new_news_sorted, 1)
            if i not in cited_indices
        ]
        if rejected:
            logger.info("Отсеяно %d из %d статей:", len(rejected), len(new_news_sorted))
            for i, item in enumerate(rejected, 1):
                logger.info("  %d. %s [%s] %s", i, item.title, item.source, item.url)

        # Update cursor and mark URLs as seen
        await update_cursor(datetime.now(timezone.utc))
        await mark_seen([item.url for item in new_news])

        # Periodic cleanup
        await cleanup_seen(days=7)

        logger.info("=== Cycle complete ===")

    except Exception as e:
        logger.exception("Cycle failed: %s", e)


async def main():
    logger.info("Initializing database...")
    await init_db()
    await seed_default_topics()

    saved = await get_setting("interval_hours", "3")
    interval = int(saved)
    logger.info("Starting scheduler (every %d hours)...", interval)
    scheduler = AsyncIOScheduler()
    set_scheduler(scheduler)
    scheduler.add_job(
        run_cycle,
        trigger=IntervalTrigger(hours=interval),
        id="news_cycle",
        replace_existing=True,
    )
    scheduler.start()

    logger.info("Starting bot polling (admin commands)...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(admin_router)

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
