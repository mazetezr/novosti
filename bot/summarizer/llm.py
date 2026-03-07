import aiohttp
import logging
import re

from bot.config import OPENROUTER_API_KEY
from bot.fetcher.models import NewsItem

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT_TEMPLATE = """Ты — редактор новостного канала об Иране.

ЗАДАЧА: Из пронумерованного списка заголовков выбери {news_count} самых важных новостей про Иран. Переведи каждый заголовок на русский и напиши ОДНО предложение — сам факт. Всё.

АНТИДУБЛЬ — КРИТИЧЕСКИ ВАЖНО:
- Тебе даны ПРЕДЫДУЩИЕ СВОДКИ канала (если есть). Ты ОБЯЗАН их прочитать.
- ЗАПРЕЩЕНО включать новость, если ТОТ ЖЕ ФАКТ уже был в предыдущих сводках.
- "Тот же факт" = та же тема, то же событие, даже если другими словами или из другого источника.
- Примеры дублей: "удары по Тегерану" и "взрывы в Тегеране" = ОДНО событие. "Иранские ракеты перехвачены" и "перехват ракет Ирана" = ОДНО событие.
- Если событие РАЗВИВАЕТСЯ (новые детали, новые жертвы, новая реакция) — можно включить ТОЛЬКО НОВУЮ ДЕТАЛЬ, а не пересказывать старое.
- Если после исключения дублей осталось меньше {news_count} уникальных новостей — пиши столько, сколько есть. НЕ ДОБИВАЙ дублями.

СТРОГИЕ ЗАПРЕТЫ:
- ЗАПРЕЩЕНО добавлять свои выводы, интерпретации, пояснения
- ЗАПРЕЩЕНО писать "что свидетельствует о...", "что указывает на...", "что может привести к...", "что подчеркивает...", "что отражает..."
- ЗАПРЕЩЕНО выдумывать информацию, которой нет в заголовке
- ЗАПРЕЩЕНО писать больше одного предложения на новость

НОМЕРА ИСТОЧНИКОВ — КРИТИЧЕСКИ ВАЖНО:
- Каждая новость в списке пронумерована (1, 2, 3...)
- После каждого факта поставь номер ИМЕННО того заголовка, из которого ты взял информацию: [3] или [5, 12]
- НЕ СТАВЬ [1] на всё подряд — используй ПРАВИЛЬНЫЙ номер из списка

ПРИОРИТЕТ ОТБОРА — ДУМАЙ ВНИМАТЕЛЬНО, выбирай то что РЕАЛЬНО меняет ситуацию:
1. УГРОЗЫ И УЛЬТИМАТУМЫ от лидеров стран (Иран угрожает, США угрожают, кто-то вступает в войну)
2. Перемещение войск, кораблей, техники — особенно через Ормузский пролив, Персидский залив
3. КОНКРЕТНЫЕ ИНЦИДЕНТЫ — удары по нефтяным объектам, перехваты ракет, пожары на базах, атаки на танкеры
4. Ядерная программа — обогащение, испытания, МАГАТЭ, опровержения/подтверждения ядерного статуса
5. Дипломатия — медиация, переговоры, разрыв отношений

РУТИНА — БЕРИ ТОЛЬКО ЕСЛИ НЕТ НИЧЕГО ИЗ ПУНКТОВ ВЫШЕ:
- "Израиль бомбит Ливан / укрепления Хезболлы" — это фон, происходит каждый день
- "Хезболла атаковала базу" — фон, если нет чего-то крупнее
- "Беженцы бегут" — гуманитарный фон, не breaking news
- "Эксперт считает / аналитика / мнение" — НЕ БЕРИ вообще

ФОРМАТ:
- Только HTML-теги (<b> для важного)
- Между новостями пустая строка
- Никаких заголовков, шапок, подписей, категорий

ПРИМЕР ПРАВИЛЬНОГО ВЫВОДА:

Иран предупредил: любая страна, присоединившаяся к агрессии США и Израиля, <b>станет законной целью для ответного удара</b>. [8]

США рассматривают план <b>проводки кораблей через Ормузский пролив</b>. [5]

<b>Взрывы в Тегеране</b> — конфликт вошёл в седьмой день. [13]

ПРИМЕР НЕПРАВИЛЬНОГО ВЫВОДА (ТАК ДЕЛАТЬ НЕЛЬЗЯ):
"Взрывы в Тегеране, что указывает на эскалацию насилия в регионе" — ЗАПРЕЩЕНО, убери всё после факта."""


async def summarize(news: list[NewsItem], previous_summaries: list[str] | None = None, news_count: int = 5) -> tuple[str, set[int]]:
    if not news:
        return "", set()

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(news_count=news_count)

    lines = []
    source_map = {}
    for i, item in enumerate(news, 1):
        lines.append(f"{i}. {item.title} ({item.source}, {item.published})")
        source_map[i] = (item.source, item.url)
    user_text = "Вот заголовки новостей за последние 3 часа. Составь сводку:\n\n" + "\n".join(lines)

    if previous_summaries:
        user_text += "\n\n⚠️ ПРЕДЫДУЩИЕ СВОДКИ КАНАЛА — ПРОЧИТАЙ ВНИМАТЕЛЬНО.\n"
        user_text += "Всё что ниже УЖЕ ОПУБЛИКОВАНО. Если новость повторяет факт из этих сводок — НЕ ВКЛЮЧАЙ её, даже если она из другого источника или сформулирована иначе.\n"
        user_text += "Включай ТОЛЬКО то, чего здесь НЕТ, или НОВЫЕ ДЕТАЛИ уже известных событий.\n\n"
        for idx, s in enumerate(previous_summaries, 1):
            user_text += f"=== Сводка {idx} (уже опубликована) ===\n{s}\n\n"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
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
                    raw_text = choice["message"]["content"]
                    logger.info("LLM finish_reason=%s, output_len=%d chars", finish, len(raw_text))
                    if finish == "length":
                        logger.warning("LLM output was TRUNCATED (hit max_tokens)")
                    cited = _extract_cited_indices(raw_text)
                    logger.info("LLM cited %d out of %d articles", len(cited), len(news))
                    return _inject_links(raw_text, source_map), cited
        except Exception as e:
            logger.warning("LLM attempt %d failed: %s", attempt + 1, e)

    logger.error("LLM summarization failed after 3 attempts")
    return "", set()


def _extract_cited_indices(text: str) -> set[int]:
    """Extract all article numbers cited as [N] or [N, M] in the LLM response."""
    indices: set[int] = set()
    for match in re.finditer(r'\[([\d,\s]+)\]', text):
        for n in match.group(1).split(","):
            n = n.strip()
            if n.isdigit():
                indices.add(int(n))
    return indices


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
