"""
Дедупликация статей по заголовкам (Python-level, без LLM).
Используем 4-char prefix stemming + overlap coefficient.
"""
import logging
import re

from bot.fetcher.models import NewsItem
from bot.utils.news_priority import article_sort_key, event_tokens

logger = logging.getLogger(__name__)

# Слова, не несущие смысловой нагрузки для сравнения
_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "has", "her", "was", "one", "our", "out", "day", "had", "how",
    "its", "may", "new", "now", "old", "see", "way", "who", "did",
    "get", "let", "say", "she", "too", "use", "from", "with", "that",
    "this", "they", "been", "have", "will", "what", "when", "where",
    "which", "their", "there", "about", "after", "would", "could",
    "over", "into", "more", "than", "some", "very", "just", "also",
    "says", "said", "report", "reports", "according", "amid", "as",
    "on", "in", "at", "to", "of", "by", "an", "is", "it", "be",
    "or", "if", "so", "up", "no", "do", "my", "we", "he",
})


def _stem(word: str) -> str:
    """4-char prefix для слов > 4 букв. Надёжно ловит морфологию:
    missiles/missile → miss, Israeli/Israel → isra, Iranian/Iran → iran."""
    if len(word) > 4:
        return word[:4]
    return word


def _title_words(title: str) -> set[str]:
    """Извлечь стемированные слова из заголовка."""
    words = re.findall(r"[a-zA-Z]{3,}", title.lower())
    return {_stem(w) for w in words if w not in _STOPWORDS}


def title_similarity(a: str, b: str) -> float:
    """Overlap coefficient — |A∩B| / min(|A|,|B|).
    Лучше Jaccard когда один заголовок короче другого."""
    wa = _title_words(a)
    wb = _title_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def title_jaccard(a: str, b: str) -> float:
    """Jaccard similarity для кластеризации (заголовки примерно одной длины)."""
    wa = _title_words(a)
    wb = _title_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def event_similarity(
    a_title: str,
    b_title: str,
    a_url: str = "",
    b_url: str = "",
) -> float:
    ea = event_tokens(a_title, a_url)
    eb = event_tokens(b_title, b_url)
    if not ea or not eb:
        return 0.0
    return len(ea & eb) / len(ea | eb)


def filter_by_previous_titles(
    articles: list[NewsItem],
    previous_titles: list[str],
    threshold: float = 0.35,
) -> list[NewsItem]:
    """
    Убрать статьи, чьи заголовки слишком похожи на ранее опубликованные.
    threshold=0.35 — достаточно агрессивно отсеивает дубли.
    """
    if not previous_titles or not articles:
        return articles

    kept: list[NewsItem] = []
    filtered_count = 0

    for art in articles:
        max_sim = max(
            max(
                title_similarity(art.title, prev),
                event_similarity(art.title, prev),
            )
            for prev in previous_titles
        )
        if max_sim >= threshold:
            filtered_count += 1
            logger.info(
                "Dedup filtered (sim=%.2f): %s", max_sim, art.title[:100]
            )
        else:
            kept.append(art)

    if filtered_count:
        logger.info(
            "Title dedup vs previous: %d → %d articles (-%d)",
            len(articles), len(kept), filtered_count,
        )
    return kept


def cluster_similar_articles(
    articles: list[NewsItem],
    threshold: float = 0.45,
) -> list[NewsItem]:
    """
    Сгруппировать похожие статьи (разные источники об одном событии).
    Оставить по одной из каждого кластера (первую по порядку = самую свежую).
    """
    if not articles:
        return articles

    used: set[int] = set()
    kept: list[NewsItem] = []

    for i, art in enumerate(articles):
        if i in used:
            continue
        cluster_members = [art]
        for j in range(i + 1, len(articles)):
            if j in used:
                continue
            other = articles[j]
            similarity = max(
                title_jaccard(art.title, other.title),
                event_similarity(art.title, other.title, art.url, other.url),
            )
            if similarity >= threshold:
                used.add(j)
                cluster_members.append(other)
        cluster_size = len(cluster_members)
        if cluster_size > 1:
            logger.debug(
                "Cluster of %d: %s", cluster_size, art.title[:80]
            )
        kept.append(max(cluster_members, key=article_sort_key))

    if len(kept) < len(articles):
        logger.info(
            "Cluster dedup: %d → %d articles (-%d same-event dupes)",
            len(articles), len(kept), len(articles) - len(kept),
        )
    return kept
