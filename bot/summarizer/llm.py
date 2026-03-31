import aiohttp
import logging
import re

from bot.config import OPENROUTER_API_KEY
from bot.fetcher.models import NewsItem

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-5-nano"


def _strip_html(text: str) -> str:
    """Убрать HTML-теги из текста для чистого контекста."""
    return re.sub(r"<[^>]+>", "", text)

SYSTEM_PROMPT_TEMPLATE = """Ты — редактор новостного Telegram-канала о геополитике. Канал освещает:
- Иран: ядерная программа, КСИР, прокси-войны, конфликты на Ближнем Востоке
- Китай и Тайвань: военные учения, кризис в Тайваньском проливе, противостояние НОАК/США
- Трамп и США: внешняя политика, тарифы, ультиматумы, военные приказы
- Нефть и энергетика: если связана с геополитикой (Ормуз, ОПЕК+, санкции)

ЗАДАЧА: Из пронумерованного списка заголовков выбери ДО {news_count} самых важных новостей. Переведи каждый заголовок на русский и напиши ОДНО предложение — сам факт. Всё.

КОЛИЧЕСТВО И УНИКАЛЬНОСТЬ:
- Если сильных уникальных событий меньше {news_count}, напиши меньше.
- НЕ ДОБИВАЙ список до {news_count} слабыми, повторяющимися или риторическими новостями.
- 1 событие = 1 карточка. Если несколько заголовков описывают один и тот же эпизод, возьми только один лучший заголовок и сделай только одну карточку.

АНТИДУБЛЬ — КРИТИЧЕСКИ ВАЖНО:
- Тебе даны ПРЕДЫДУЩИЕ СВОДКИ канала (если есть). Ты ОБЯЗАН их прочитать.
- ЗАПРЕЩЕНО включать новость, если ТОТ ЖЕ ФАКТ уже был в предыдущих сводках.
- "Тот же факт" = та же тема, то же событие, даже если другими словами или из другого источника.
- Примеры дублей: "удары по Тегерану" и "взрывы в Тегеране" = ОДНО событие. "Иранские ракеты перехвачены" и "перехват ракет Ирана" = ОДНО событие.
- Если событие РАЗВИВАЕТСЯ (новые детали, новые жертвы, новая реакция) — можно включить ТОЛЬКО НОВУЮ ДЕТАЛЬ, а не пересказывать старое.

СТРОГИЕ ЗАПРЕТЫ:
- ЗАПРЕЩЕНО добавлять свои выводы, интерпретации, пояснения
- ЗАПРЕЩЕНО писать "что свидетельствует о...", "что указывает на...", "что может привести к...", "что подчеркивает...", "что отражает..."
- ЗАПРЕЩЕНО выдумывать информацию, которой нет в заголовке
- ЗАПРЕЩЕНО писать больше одного предложения на новость

НОМЕРА ИСТОЧНИКОВ — КРИТИЧЕСКИ ВАЖНО:
- Каждая новость в списке пронумерована (1, 2, 3...)
- После каждого факта поставь номер ИМЕННО того заголовка, из которого ты взял информацию: [3] или [5, 12]
- НЕ СТАВЬ [1] на всё подряд — используй ПРАВИЛЬНЫЙ номер из списка

ПРИОРИТЕТ ОТБОРА — выбирай то что РЕАЛЬНО меняет ситуацию:
1. ОПЕРАЦИОННЫЕ ИЗМЕНЕНИЯ: перемещение войск, кораблей и техники, патрули, проводка судов, перекрытия, перехваты, удары, учения, реальные приказы.
2. КОНКРЕТНЫЕ ИНЦИДЕНТЫ: атаки на танкеры, базы, нефтяную инфраструктуру, столкновения, новые санкции/тарифы/экспортные ограничения, если они уже объявлены.
3. ЯДЕРКА / ЧИПЫ / ЛОГИСТИКА: Иран, Тайвань, TSMC, экспортный контроль, Ормуз, ОПЕК — если это меняет расклад сил.
4. ДИПЛОМАТИЯ: медиация, переговоры, голосования СБ ООН, официальные решения.
5. ТРАМП О ВОЙНЕ С ИРАНОМ: любые заявления, угрозы, решения Трампа, связанные с Ираном и войной — ВСЕГДА БЕРИ, даже если это риторика без немедленного действия. Трамп — главнокомандующий, его слова по войне важны.
6. РИТОРИКА И УГРОЗЫ (кроме Трампа по Ирану) — только если за ними стоит немедленное практическое последствие или если нет более сильных operational developments.
7. ФОН / РУТИНА — только в самом крайнем случае.

ПРИОРИТЕТ ИСТОЧНИКОВ:
- Если одно и то же событие описано разными заголовками, предпочитай более сильный источник.
- Приоритет источников: Reuters / AP / BBC / White House / официальные структуры > Al Jazeera / Politico / Axios / France 24 > профильные и региональные издания.
- Не выбирай слабый, локальный или вторичный источник, если в списке есть тот же факт у более сильного источника.

РУТИНА — БЕРИ ТОЛЬКО ЕСЛИ НЕТ НИЧЕГО ИЗ ПУНКТОВ ВЫШЕ:
- "Израиль бомбит Ливан / укрепления Хезболлы" — фон, происходит каждый день
- "Хезболла атаковала базу" — фон, если нет чего-то крупнее
- "Беженцы бегут" — гуманитарный фон, не breaking news
- "Эксперт считает / аналитика / мнение" — НЕ БЕРИ вообще
- Слова вроде "warns", "vows", "slams", "region will go dark" сами по себе НЕ делают новость важной
- Human-interest, individual profiles, isolated crimes, кампусные/общественные side-stories и локальные бытовые последствия — ПРОПУСКАЙ, если это не меняет государственные решения, военные действия или логистику
- Марши, митинги солидарности, галереи, фотоподборки, политические настроения, рыночные реакции и общие разговоры про "удар по экономике" — ПРОПУСКАЙ, если там нет нового официального решения, санкции, приказа, удара, перехвата или сбоя поставок
- Спорт, культура, реклама, внутренняя политика без геополитики — ПРОПУСКАЙ

ФОРМАТ:
- Только HTML-теги (<b> для важного)
- Между новостями пустая строка
- Никаких заголовков, шапок, подписей, категорий

ПРИМЕР ПРАВИЛЬНОГО ВЫВОДА:

США рассматривают план <b>проводки кораблей через Ормузский пролив</b>. [5]

Совбез ООН потребовал от Ирана <b>прекратить атаки</b>. [8]

Китай провёл <b>масштабные военные учения вблизи Тайваня</b> с участием авиации и флота. [13]

ПРИМЕР НЕПРАВИЛЬНОГО ВЫВОДА (ТАК ДЕЛАТЬ НЕЛЬЗЯ):
"Взрывы в Тегеране, что указывает на эскалацию насилия в регионе" — ЗАПРЕЩЕНО, убери всё после факта."""

async def summarize(news: list[NewsItem], previous_summaries: list[dict] | None = None, news_count: int = 5) -> tuple[str, set[int]]:
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
        # Collect all previously cited English titles for direct comparison
        all_prev_titles = []
        for s in previous_summaries:
            all_prev_titles.extend(s.get("cited_titles", []))

        if all_prev_titles:
            user_text += "\n\n🚫 СТОП-ЛИСТ ЗАГОЛОВКОВ — эти статьи УЖЕ были в предыдущих постах канала.\n"
            user_text += "НЕ БЕРИ новости на ту же тему, даже если заголовок немного отличается:\n\n"
            for i, title in enumerate(all_prev_titles, 1):
                user_text += f"  ✗ {title}\n"

        user_text += "\n\n⚠️ ПРЕДЫДУЩИЕ СВОДКИ КАНАЛА (русский текст, уже опубликовано):\n"
        user_text += "Если новость повторяет факт отсюда — НЕ ВКЛЮЧАЙ.\n\n"
        for idx, s in enumerate(previous_summaries, 1):
            clean_text = _strip_html(s.get("text", ""))
            user_text += f"=== Сводка {idx} ===\n{clean_text}\n\n"

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
            elif n.isdigit():
                logger.warning("LLM cited [%s] but only %d articles in pool", n, len(source_map))
        if not parts:
            return ""
        return " " + ", ".join(parts)
    return re.sub(r'\s*\[([\d,\s]+)\]', replacer, text)
