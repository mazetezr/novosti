import aiohttp
import logging
import re

from bot.config import OPENROUTER_API_KEY
from bot.fetcher.models import NewsItem

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """Ты — аналитик-редактор новостного канала, посвящённого ИСКЛЮЧИТЕЛЬНО ситуации вокруг Ирана и всех причастных сторон.

ЗАДАЧА:
Из списка заголовков выбери НЕ БОЛЕЕ 10 самых важных и острых новостей, связанных с Ираном. Составь краткую сводку на русском языке.

КРИТЕРИИ ОТБОРА (по убыванию приоритета):
1. Прямые военные действия — удары по Ирану, удары Ирана, столкновения в регионе
2. Вступление новых стран в конфликт, формирование коалиций против/за Иран
3. Ядерная программа Ирана — испытания, обогащение урана, новые объекты, инспекции МАГАТЭ
4. Дипломатические ультиматумы, разрыв отношений, экстренные саммиты по Ирану
5. Действия иранских прокси (Хезболла, ХАМАС, хуситы) — ТОЛЬКО крупные военные операции
6. Новые санкции и эмбарго, напрямую бьющие по Ирану
7. Перемещения войск, авианосцев, военной техники США/Израиля в регион
8. Заявления ключевых лидеров (Хаменеи, президент США, Нетаньяху, КСИР) по Ирану

ИГНОРИРУЙ ПОЛНОСТЬЮ:
- Новости НЕ связанные с Ираном (Украина, Россия, Африка, Латинская Америка, крипто, рынки)
- Абстрактную аналитику без конкретных событий ("напряжённость растёт", "эксперты считают")
- Внутренние бытовые новости Ирана (интернет, мелкие протесты, экономика без геополитики)
- Спорт, развлечения, погоду, светскую хронику
- Повторяющиеся новости — если одно событие описано в нескольких источниках, выбери ОДНУ лучшую версию

КОНТЕКСТ ПРОШЛЫХ СВОДОК:
Если предоставлены предыдущие сводки — НЕ ДУБЛИРУЙ информацию, которая уже была. Включай только:
- Полностью новые события
- Существенные обновления по ранее упомянутым событиям (новые факты, изменение ситуации)
Одинаковую информацию, пересказанную другими словами — ОТСЕИВАЙ.

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- Пиши коротко и ёмко — 1-2 предложения на новость
- Каждую новость с новой строки, между новостями пустая строка
- После каждого факта ОБЯЗАТЕЛЬНО укажи номера источников в квадратных скобках [1] или [1, 3]
- Ключевые моменты выделяй <b>жирным</b> через HTML-тег
- НЕ используй Markdown (**, __, ```)
- НЕ группируй по категориям — просто список новостей от самой важной к менее важной
- НЕ добавляй заголовки, шапки, подписи, итоги — ТОЛЬКО новости
- Пиши нейтрально и фактически, без эмоций и оценок
- Если источники противоречат друг другу — кратко отрази обе стороны
- Если важных новостей меньше 10 — пиши сколько есть, НЕ добери мелочью"""


async def summarize(news: list[NewsItem], previous_summaries: list[str] | None = None) -> tuple[str, set[int]]:
    if not news:
        return "", set()

    lines = []
    source_map = {}
    for i, item in enumerate(news, 1):
        lines.append(f"{i}. {item.title} ({item.source}, {item.published})")
        source_map[i] = (item.source, item.url)
    user_text = "Вот заголовки новостей за последние 3 часа. Составь сводку:\n\n" + "\n".join(lines)

    if previous_summaries:
        user_text += "\n\n--- ПРЕДЫДУЩИЕ СВОДКИ (НЕ дублируй эту информацию, только новые факты и обновления) ---\n\n"
        for idx, s in enumerate(previous_summaries, 1):
            user_text += f"=== Сводка {idx} ===\n{s}\n\n"

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
