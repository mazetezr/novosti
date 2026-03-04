import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import LOG_LEVEL, LOG_PATH, DB_PATH, TELEGRAM_BOT_TOKEN
from bot.cursor.manager import init_db, get_cursor, update_cursor, mark_seen, filter_seen, cleanup_seen, seed_default_topics, get_setting
from bot.fetcher.models import NewsItem
from bot.fetcher.rss import fetch_rss
from bot.fetcher.thenewsapi import fetch_thenewsapi
from bot.summarizer.llm import summarize
from bot.poster.telegram import post_to_channel
from bot.admin.router import router as admin_router

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

        # Summarize with LLM
        summary = await summarize(new_news_sorted)
        if not summary:
            logger.error("LLM returned empty summary, skipping post")
            return

        # Post to Telegram
        await post_to_channel(summary)
        logger.info("Posted to Telegram successfully")

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

    logger.info("Running initial cycle...")
    await run_cycle()

    saved = await get_setting("interval_hours", "3")
    interval = int(saved)
    logger.info("Starting scheduler (every %d hours)...", interval)
    global scheduler
    scheduler = AsyncIOScheduler()
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


scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    return scheduler


if __name__ == "__main__":
    asyncio.run(main())
