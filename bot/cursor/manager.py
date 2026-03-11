import aiosqlite
import json
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                cited_titles TEXT NOT NULL DEFAULT '[]',
                created_at DATETIME NOT NULL
            )
        """)
        # Migrate: add cited_titles if missing
        try:
            await db.execute("ALTER TABLE summaries ADD COLUMN cited_titles TEXT NOT NULL DEFAULT '[]'")
        except Exception:
            pass  # column already exists
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


# --- Summaries history (for anti-duplicate context) ---

async def save_summary(text: str, cited_titles: list[str] | None = None):
    now = datetime.now(timezone.utc).isoformat()
    titles_json = json.dumps(cited_titles or [], ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO summaries (text, cited_titles, created_at) VALUES (?, ?, ?)",
            (text, titles_json, now),
        )
        # Keep only last 5 summaries
        await db.execute("""
            DELETE FROM summaries WHERE id NOT IN (
                SELECT id FROM summaries ORDER BY id DESC LIMIT 5
            )
        """)
        await db.commit()


async def get_last_summaries(n: int = 5) -> list[dict]:
    """Return last N summaries with text and cited_titles."""
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            "SELECT text, cited_titles FROM summaries ORDER BY id DESC LIMIT ?", (n,)
        )
        result = []
        for row in rows:
            try:
                titles = json.loads(row[1]) if row[1] else []
            except (json.JSONDecodeError, TypeError):
                titles = []
            result.append({"text": row[0], "cited_titles": titles})
        return result


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
    # Core Iran
    "Iran", "IRGC", "Khamenei", "Tehran", "Persian Gulf", "Strait of Hormuz",
    # Nuclear
    "uranium", "enrichment", "IAEA", "ballistic", "warhead", "nonproliferation",
    # Iran proxies
    "Hezbollah", "Hamas", "Houthi",
    # Middle East theater
    "Israel", "Gaza", "Lebanon", "Syria", "Iraq", "Yemen",
    # Key adversaries / agencies
    "USA", "Pentagon", "CIA", "Mossad", "IDF", "Netanyahu",
    # Regional actors
    "Saudi Arabia", "UAE", "Qatar", "Turkey", "Erdogan",
    # Military terms (Iran context)
    "sanctions", "nuclear", "airstrike", "missile", "drone", "strike",
    "bombing", "military", "attack", "war", "conflict", "ceasefire",
    "escalation", "deterrence", "provocation",
    "navy", "warship", "blockade",
    "arms deal", "weapons supply", "military aid", "troop deployment",
    "sabotage", "espionage", "cyberattack", "assassination",
    # Trump / US policy
    "Trump", "White House", "tariff", "executive order",
    # Нефть и энергетика (релевантно для Ирана и региона)
    "oil", "OPEC", "crude", "energy",
]

EXTRA_TOPICS = [
    # Extended Iran
    "ayatollah", "Quds Force", "Basij", "proxy war",
    "Natanz", "Fordow", "Bushehr", "Parchin",
    "West Bank", "Rafah", "Red Sea",
    "aircraft carrier", "CENTCOM", "B-52",
    "oil tanker", "Strait of Hormuz",
    "Pakistan", "Oman", "Bahrain", "Kuwait",
    "chemical", "biological", "hypersonic",
    "troops", "offensive", "explosion", "weapons",
    "Security Council", "UN",
]

# Topics to remove on startup (no longer relevant after Iran-focus pivot)
DEPRECATED_TOPICS = [
    "Ukraine", "Russia", "Zelensky", "Kremlin", "FSB",
    "Europe", "EU", "NATO", "France", "Germany",
    "Poland", "Hungary", "Estonia", "Latvia", "Lithuania", "Finland", "Sweden",
    "inflation", "economy", "markets", "gold", "metals",
    "North Korea", "Taiwan", "Xi Jinping", "Modi", "Tibet", "Xinjiang",
    "South China Sea", "South Korea", "China", "India",
    "Sudan", "Mali", "Libya", "Sahel", "Niger", "coup", "Somalia",
    "Ethiopia", "Burkina Faso", "mercenary", "Wagner",
    "Venezuela", "Cuba", "Maduro", "Nicaragua", "Haiti", "cartel",
    "Colombia", "Bolivia",
    "Bitcoin", "crypto", "cryptocurrency", "blockchain", "CBDC",
    "stablecoin", "Tether", "crypto sanctions",
    "frontline", "conscription", "mobilization", "prisoner exchange",
    "war crimes", "genocide", "evacuation",
    "artillery", "rebel", "insurgency",
]

DEFAULT_STOPWORDS = [
    "football", "soccer", "basketball", "tennis", "cricket", "baseball",
    "celebrity", "entertainment", "movie", "film", "music", "album",
    "fashion", "recipe", "cooking", "travel", "tourism", "hotel",
    "weather forecast", "horoscope", "lottery", "game", "gaming",
    "reality show", "kardashian", "hollywood", "bollywood",
    "stock tips", "crypto pump", "NFT", "meme coin",
    "Ukraine", "Zelensky", "Kremlin", "frontline",
]


async def seed_default_topics():
    async with aiosqlite.connect(DB_PATH) as db:
        # Remove deprecated topics that are no longer relevant
        removed = 0
        for kw in DEPRECATED_TOPICS:
            cur = await db.execute("DELETE FROM topics WHERE keyword = ?", (kw,))
            removed += cur.rowcount
        if removed:
            await db.commit()
            logger.info("Removed %d deprecated topics", removed)

        # Ensure all default + extra topics exist
        added = 0
        for kw in DEFAULT_TOPICS + EXTRA_TOPICS:
            cur = await db.execute(
                "INSERT OR IGNORE INTO topics (keyword) VALUES (?)", (kw,)
            )
            added += cur.rowcount
        if added:
            await db.commit()
            logger.info("Added %d Iran-focused topics", added)

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
