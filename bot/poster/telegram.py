import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

from aiogram import Bot
from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID

logger = logging.getLogger(__name__)

TZ_OFFSET = timezone(timedelta(hours=2))  # UTC+2
MAX_MSG_LEN = 4096

ALLOWED_TAGS = {"b", "i", "a", "blockquote", "code", "pre", "u", "s"}


def _sanitize_html(text: str) -> str:
    """Fix broken HTML tags so Telegram accepts the message."""
    # Remove tags not supported by Telegram HTML
    def _strip_unknown(m):
        tag = m.group(1).lower().split()[0]
        if tag.lstrip("/") in ALLOWED_TAGS:
            return m.group(0)
        return ""
    text = re.sub(r'<(/?\w[^>]*)>', _strip_unknown, text)

    # Walk through and fix unclosed / orphan tags
    open_stack: list[str] = []
    result_parts: list[str] = []
    pos = 0
    tag_re = re.compile(r'<(/?)(\w+)([^>]*)>')

    for m in tag_re.finditer(text):
        result_parts.append(text[pos:m.start()])
        pos = m.end()
        is_close = m.group(1) == "/"
        tag_name = m.group(2).lower()
        if tag_name not in ALLOWED_TAGS:
            continue
        if is_close:
            if tag_name in open_stack:
                # close any intervening unclosed tags first
                while open_stack and open_stack[-1] != tag_name:
                    result_parts.append(f"</{open_stack.pop()}>")
                open_stack.pop()
                result_parts.append(f"</{tag_name}>")
            # else: orphan closing tag — skip it
        else:
            open_stack.append(tag_name)
            result_parts.append(m.group(0))

    result_parts.append(text[pos:])

    # Close any remaining open tags
    while open_stack:
        result_parts.append(f"</{open_stack.pop()}>")

    return "".join(result_parts)


def _build_header() -> str:
    now = datetime.now(TZ_OFFSET)
    return (
        f"<i>🌍 ГЕОПОЛИТИЧЕСКАЯ СВОДКА\n"
        f"📅 {now.strftime('%d.%m.%Y')} | 🕐 {now.strftime('%H:%M')} UTC+2</i>\n"
    )


def _split_message(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]
    parts = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            parts.append(text)
            break
        # split at last newline before limit
        idx = text.rfind("\n", 0, MAX_MSG_LEN)
        if idx == -1:
            idx = MAX_MSG_LEN
        parts.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return parts


async def send_to_admins(text: str):
    """Send a plain message to all admins (DM). Used for debug reports."""
    from bot.config import ADMIN_IDS
    if not ADMIN_IDS:
        logger.warning("send_to_admins: ADMIN_IDS is empty, skipping")
        return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        parts = _split_message(text)
        for admin_id in ADMIN_IDS:
            for part in parts:
                for attempt in range(3):
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=part,
                            parse_mode="HTML",
                            link_preview_is_disabled=True,
                        )
                        break
                    except Exception as e:
                        logger.warning("DM to admin %d attempt %d failed: %s", admin_id, attempt + 1, e)
                        if attempt < 2:
                            await asyncio.sleep(5)
    finally:
        await bot.session.close()


async def post_to_channel(summary: str):
    if not summary:
        logger.warning("Empty summary, skipping post")
        return

    full_text = _sanitize_html(summary)
    parts = _split_message(full_text)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        for part in parts:
            part = _sanitize_html(part)
            for attempt in range(3):
                try:
                    await bot.send_message(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        text=part,
                        parse_mode="HTML",
                    )
                    break
                except Exception as e:
                    logger.warning("Telegram send attempt %d failed: %s", attempt + 1, e)
                    if attempt < 2:
                        await asyncio.sleep(10)
            else:
                logger.error("Failed to send message after 3 attempts")
    finally:
        await bot.session.close()
