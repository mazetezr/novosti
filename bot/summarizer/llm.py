import aiohttp
import logging
import re

from bot.config import OPENROUTER_API_KEY
from bot.fetcher.models import NewsItem

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """Ты — редактор геополитического новостного канала. 
Твоя задача — на основе пронумерованного списка заголовков новостей составить 
структурированную сводку на русском языке.

Правила:
- Группируй по темам: Иран/США, Ближний Восток, Украина/Россия, Европа, 
  Мировые рынки, Прочее
- Пиши коротко и ёмко — 1-3 предложения на событие
- Между каждым пунктом новости оставляй пустую строку
- Указывай причины движений (рост напряжённости, санкции и т.д.)
- Если новостей по теме нет — тему не включай
- Не добавляй ничего от себя — только факты из переданных заголовков
- После каждого факта укажи номера источников в квадратных скобках, например [1] или [1, 3]
- Используй HTML-теги для форматирования: <b> для жирного, <i> для курсива
- НЕ используй Markdown-разметку (**, __, ```) — только HTML-теги
- Названия тем выделяй жирным: <b>🔥 ИРАН / США</b>, <b>⚔️ БЛИЖНИЙ ВОСТОК</b> и т.д.
- Текст каждой новостной категории оборачивай в тег <blockquote>...</blockquote>
- Каждая новость в категории должна быть отдельным абзацом, не все в одном абзаце!
- ВАЖНО: Пропускай новости НЕ связанные с геополитикой, конфликтами, военными действиями, санкциями, мировыми рынками, мировыми активами, криптой. Спорт, развлечения, погода, бытовые происшествия — игнорируй.
- НО: все геополитически значимые новости ОБЯЗАТЕЛЬНО включай. Не сокращай сводку — лучше длинная полная сводка, чем короткая с пропусками.
- Если источники противоречат друг другу по одному событию — отражай обе стороны коротко, без выбора "правой" версии
- Не перенимай тон источника — пиши нейтрально и фактически
- Избегай эмоционально окрашенных формулировок из заголовков
- Формат — Telegram-совместимый HTML

Пример структуры:

<b>🔥 ИРАН / США</b>

<blockquote>Новость 1<\n><\n>Новость 2<\n><\n>Новость 3</blockquote>

<b>⚔️ БЛИЖНИЙ ВОСТОК</b>

<blockquote>Новость 1<\n><\n>Новость 2</blockquote>"""


async def summarize(news: list[NewsItem]) -> str:
    if not news:
        return ""

    lines = []
    source_map = {}
    for i, item in enumerate(news, 1):
        lines.append(f"{i}. {item.title} ({item.source}, {item.published})")
        source_map[i] = (item.source, item.url)
    user_text = "Вот заголовки новостей за последние 3 часа. Составь сводку:\n\n" + "\n".join(lines)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 12000,
        "temperature": 0.3,
    }

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    OPENROUTER_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("OpenRouter %d: %s", resp.status, body)
                        continue
                    data = await resp.json()
                    choice = data["choices"][0]
                    finish = choice.get("finish_reason", "unknown")
                    text = choice["message"]["content"]
                    logger.info("LLM finish_reason=%s, output_len=%d chars", finish, len(text))
                    if finish == "length":
                        logger.warning("LLM output was TRUNCATED (hit max_tokens)")
                    return _inject_links(text, source_map)
        except Exception as e:
            logger.warning("LLM attempt %d failed: %s", attempt + 1, e)

    logger.error("LLM summarization failed after 3 attempts")
    return ""


def _inject_links(text: str, source_map: dict[int, tuple[str, str]]) -> str:
    """Replace [N] and [N, M] markers with <a href="url">source</a> links."""
    def replacer(match):
        inner = match.group(1)
        nums = [n.strip() for n in inner.split(",")]
        parts = []
        for n in nums:
            if n.isdigit() and int(n) in source_map:
                name, url = source_map[int(n)]
                parts.append(f'<a href="{url}">{name}</a>')
            else:
                parts.append(n)
        return ", ".join(parts)
    return re.sub(r'\[([\d,\s]+)\]', replacer, text)
