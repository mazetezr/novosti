import aiosqlite
import logging
from datetime import datetime, timedelta, timezone

from bot.config import DB_PATH

logger = logging.getLogger(__name__)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cursor (
                id INTEGER PRIMARY KEY,
                last_run_at DATETIME NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY,
                seen_at DATETIME NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stopwords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL UNIQUE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_cursor() -> datetime:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db.execute_fetchall("SELECT last_run_at FROM cursor WHERE id = 1")
        if row:
            return datetime.fromisoformat(row[0][0])
        return datetime.now(timezone.utc) - timedelta(hours=3)


async def update_cursor(ts: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO cursor (id, last_run_at) VALUES (1, ?)",
            (ts.isoformat(),),
        )
        await db.commit()


async def filter_seen(urls: list[str]) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        seen = set()
        for url in urls:
            row = await db.execute_fetchall(
                "SELECT 1 FROM seen_urls WHERE url = ?", (url,)
            )
            if row:
                seen.add(url)
        return [u for u in urls if u not in seen]


async def mark_seen(urls: list[str]):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        for url in urls:
            await db.execute(
                "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
                (url, now),
            )
        await db.commit()


async def cleanup_seen(days: int = 7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM seen_urls WHERE seen_at < ?", (cutoff,))
        await db.commit()
    logger.info("Cleaned up seen_urls older than %d days", days)


# --- Settings KV ---

async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return rows[0][0] if rows else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()


# --- Topics CRUD ---

DEFAULT_TOPICS = [
    "war", "conflict", "military", "attack", "airstrike", "missile",
    "Iran", "Israel", "Gaza", "Ukraine", "Russia", "Hamas", "Hezbollah",
    "sanctions", "nuclear", "troops", "offensive", "ceasefire",
    "oil", "OPEC", "gold", "markets", "economy", "inflation",
    "metals", "France", "Germany", "USA", "Europe", "EU", "NATO",
]

DEFAULT_STOPWORDS = [
    "football", "soccer", "basketball", "tennis", "cricket", "baseball",
    "celebrity", "entertainment", "movie", "film", "music", "album",
    "fashion", "recipe", "cooking", "travel", "tourism", "hotel",
    "weather forecast", "horoscope", "lottery", "game", "gaming",
    "reality show", "kardashian", "hollywood", "bollywood",
    "stock tips", "crypto pump", "NFT", "meme coin",
]


async def seed_default_topics():
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT COUNT(*) FROM topics")
        if rows[0][0] == 0:
            for kw in DEFAULT_TOPICS:
                await db.execute(
                    "INSERT OR IGNORE INTO topics (keyword) VALUES (?)", (kw,)
                )
            await db.commit()
            logger.info("Seeded %d default topics", len(DEFAULT_TOPICS))
        # Seed default stopwords
        rows = await db.execute_fetchall("SELECT COUNT(*) FROM stopwords")
        if rows[0][0] == 0:
            for sw in DEFAULT_STOPWORDS:
                await db.execute(
                    "INSERT OR IGNORE INTO stopwords (word) VALUES (?)", (sw,)
                )
            await db.commit()
            logger.info("Seeded %d default stopwords", len(DEFAULT_STOPWORDS))
        # Seed default interval
        rows = await db.execute_fetchall(
            "SELECT 1 FROM settings WHERE key = 'interval_hours'"
        )
        if not rows:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES ('interval_hours', '3')"
            )
            await db.commit()


async def get_topics() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT keyword FROM topics ORDER BY id")
        return [row[0] for row in rows]


async def add_topic(keyword: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO topics (keyword) VALUES (?)", (keyword,)
        )
        await db.commit()
        return cur.rowcount > 0


async def remove_topic(keyword: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM topics WHERE keyword = ?", (keyword,))
        await db.commit()
        return cur.rowcount > 0


# --- Stopwords CRUD ---

async def get_stopwords() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT word FROM stopwords ORDER BY id")
        return [row[0] for row in rows]


async def add_stopword(word: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO stopwords (word) VALUES (?)", (word,)
        )
        await db.commit()
        return cur.rowcount > 0


async def remove_stopword(word: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM stopwords WHERE word = ?", (word,))
        await db.commit()
        return cur.rowcount > 0


async def reset_cursor(hours: int = 3):
    new_cursor = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM cursor")
        await db.execute(
            "INSERT INTO cursor (id, last_run_at) VALUES (1, ?)", (new_cursor,)
        )
        await db.execute("DELETE FROM seen_urls")
        await db.commit()
    logger.info("Cursor reset to %d hours ago, seen_urls cleared", hours)
