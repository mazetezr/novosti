from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import unquote, urlparse

from bot.fetcher.models import NewsItem


@dataclass(frozen=True)
class TopicCluster:
    name: str
    anchors: tuple[str, ...]
    contexts: tuple[str, ...]


SOURCE_RANKS = {
    "reuters": 100,
    "associated press": 97,
    "ap": 97,
    "bbc": 96,
    "white house": 96,
    "al jazeera": 93,
    "politico": 92,
    "axios": 91,
    "france 24": 90,
    "defense news": 89,
    "financial times": 89,
    "bloomberg": 88,
    "the diplomat": 88,
    "south china morning post": 87,
    "taiwan news": 86,
    "times of israel": 85,
    "iran international": 85,
    "middle east eye": 84,
    "nikkei asia": 84,
    "cnn": 82,
    "the guardian": 81,
    "washington post": 81,
    "new york times": 81,
}

DOMAIN_RANKS = {
    "reuters.com": 100,
    "apnews.com": 97,
    "bbc.com": 96,
    "bbci.co.uk": 96,
    "whitehouse.gov": 96,
    "aljazeera.com": 93,
    "politico.com": 92,
    "axios.com": 91,
    "france24.com": 90,
    "defensenews.com": 89,
    "ft.com": 89,
    "bloomberg.com": 88,
    "thediplomat.com": 88,
    "scmp.com": 87,
    "taiwannews.com.tw": 86,
    "timesofisrael.com": 85,
    "iranintl.com": 85,
    "middleeasteye.net": 84,
    "nikkei.com": 84,
    "cnn.com": 82,
    "theguardian.com": 81,
    "washingtonpost.com": 81,
    "nytimes.com": 81,
}

MIN_API_SOURCE_RANK = 80

_GENERIC_URL_FRAGMENTS = (
    "/opinion/",
    "/opinions/",
    "/op-ed/",
    "/commentary/",
    "/feature/",
    "/features/",
    "/live/",
    "/liveblog/",
    "/live-blog/",
    "/live-updates/",
    "/sport/",
    "/sports/",
    "/lifestyle/",
    "/entertainment/",
    "/culture/",
    "/travel/",
    "/podcast/",
    "/video/",
)

_SCMP_URL_FRAGMENTS = (
    "/news/hong-kong/",
    "/business/",
)

_BLOCKED_TITLE_PATTERNS = (
    "live updates",
    "live blog",
    "minute by minute",
    "podcast",
)

_GLOBAL_CONTEXT_TERMS = (
    "military",
    "missile",
    "drone",
    "strike",
    "strikes",
    "attack",
    "attacks",
    "escort",
    "navy",
    "warship",
    "warships",
    "carrier",
    "carriers",
    "troops",
    "exercise",
    "exercises",
    "drill",
    "drills",
    "patrol",
    "patrols",
    "blockade",
    "sanctions",
    "tariff",
    "tariffs",
    "uranium",
    "enrichment",
    "tanker",
    "shipping",
    "bases",
    "base",
    "security council",
    "arms sales",
    "export controls",
)

_GENERIC_TOPIC_KEYWORDS = {
    "war",
    "conflict",
    "strike",
    "attack",
    "military",
    "energy",
    "oil",
    "crude",
    "navy",
    "troops",
    "weapons",
    "sanctions",
    "missile",
    "drone",
    "chip",
    "chips",
}

TOPIC_CLUSTERS = (
    TopicCluster(
        name="iran",
        anchors=(
            "iran",
            "iranian",
            "tehran",
            "khamenei",
            "mojtaba khamenei",
            "irgc",
            "natanz",
            "fordow",
            "iaea",
            "strait of hormuz",
            "hormuz",
            "persian gulf",
            "hezbollah",
            "houthi",
        ),
        contexts=(
            "missile",
            "drone",
            "strike",
            "strikes",
            "attack",
            "attacks",
            "escort",
            "navy",
            "warship",
            "tanker",
            "uranium",
            "enrichment",
            "nuclear",
            "security council",
            "unsc",
            "troops",
            "carrier",
            "military",
            "base",
            "bases",
            "shipping",
            "blockade",
            "patrol",
        ),
    ),
    TopicCluster(
        name="china-taiwan",
        anchors=(
            "china",
            "chinese",
            "taiwan",
            "taipei",
            "xi jinping",
            "pla",
            "beijing",
            "taiwan strait",
            "cross-strait",
            "south china sea",
            "tsmc",
            "smic",
            "lai ching-te",
        ),
        contexts=(
            "drill",
            "drills",
            "exercise",
            "exercises",
            "patrol",
            "patrols",
            "manoeuvre",
            "maneuver",
            "maneuvers",
            "incursion",
            "military",
            "navy",
            "warship",
            "missile",
            "blockade",
            "carrier",
            "destroyer",
            "air force",
            "export controls",
            "chip",
            "semiconductor",
            "arms sales",
        ),
    ),
    TopicCluster(
        name="trump-us",
        anchors=(
            "trump",
            "white house",
            "executive order",
            "pentagon",
            "state department",
            "u.s. navy",
            "us navy",
            "u.s. military",
            "tariff",
        ),
        contexts=(
            "iran",
            "hormuz",
            "taiwan",
            "china",
            "gaza",
            "israel",
            "sanctions",
            "tariff",
            "tariffs",
            "military",
            "troops",
            "warship",
            "escort",
            "bases",
            "strike",
            "strikes",
            "attack",
            "attacks",
            "order",
            "orders",
        ),
    ),
    TopicCluster(
        name="energy",
        anchors=(
            "oil",
            "crude",
            "opec",
            "opec+",
            "tanker",
            "shipping",
            "lng",
            "energy",
        ),
        contexts=(
            "iran",
            "hormuz",
            "persian gulf",
            "gulf",
            "sanctions",
            "attack",
            "attacks",
            "strike",
            "strikes",
            "war",
            "drone",
            "missile",
            "blockade",
            "supply",
            "shipping",
            "navy",
            "security council",
        ),
    ),
)

_EVENT_SYNONYMS = {
    "vessel": "shipping",
    "vessels": "shipping",
    "ship": "shipping",
    "ships": "shipping",
    "tanker": "shipping",
    "tankers": "shipping",
    "freighter": "shipping",
    "freighters": "shipping",
    "cargo": "shipping",
    "maritime": "shipping",
    "seafront": "coast",
    "waterfront": "coast",
    "coastal": "coast",
    "port": "port",
    "harbor": "port",
    "harbour": "port",
    "dock": "port",
    "docks": "port",
    "mine": "mine",
    "mines": "mine",
    "mined": "mine",
    "destruction": "damage",
    "destroyed": "damage",
    "destroy": "damage",
    "damaged": "damage",
    "damage": "damage",
    "damaging": "damage",
    "manoeuvres": "maneuver",
    "manoeuvre": "maneuver",
    "maneuvers": "maneuver",
    "exercises": "exercise",
    "drills": "exercise",
}

_EVENT_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "amid",
        "after",
        "before",
        "into",
        "over",
        "under",
        "about",
        "report",
        "reports",
        "says",
        "said",
        "live",
        "blog",
        "update",
        "updates",
        "breaking",
    }
)


def _slug_tokens(url: str) -> set[str]:
    path = unquote(urlparse(url).path)
    return set(re.findall(r"[a-z0-9]{3,}", path.casefold()))


@lru_cache(maxsize=None)
def _term_regex(term: str) -> re.Pattern[str]:
    parts = re.findall(r"[a-z0-9]+", term.casefold())
    if not parts:
        return re.compile(r"(?!x)x")
    pattern = r"\b" + r"\W+".join(re.escape(part) for part in parts) + r"\b"
    return re.compile(pattern, re.IGNORECASE)


def has_term(text: str, term: str) -> bool:
    return bool(_term_regex(term).search(text))


def matched_terms(text: str, terms: list[str] | tuple[str, ...]) -> set[str]:
    return {term for term in terms if has_term(text, term)}


def is_blocked_format(title: str, url: str) -> bool:
    lower_url = url.casefold()
    lower_title = title.casefold()

    if any(fragment in lower_url for fragment in _GENERIC_URL_FRAGMENTS):
        return True
    if "scmp.com" in lower_url and any(fragment in lower_url for fragment in _SCMP_URL_FRAGMENTS):
        return True
    return any(pattern in lower_title for pattern in _BLOCKED_TITLE_PATTERNS)


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


def source_rank(source: str, url: str = "") -> int:
    source_key = source.casefold().strip()
    domain = domain_from_url(url)

    rank = 40
    for candidate, candidate_rank in SOURCE_RANKS.items():
        if candidate in source_key:
            rank = max(rank, candidate_rank)
    for candidate, candidate_rank in DOMAIN_RANKS.items():
        if domain == candidate or domain.endswith(f".{candidate}"):
            rank = max(rank, candidate_rank)
    return rank


def build_api_search_query(keywords: list[str]) -> str:
    preferred_terms = [
        "Iran",
        "Tehran",
        "IRGC",
        "Khamenei",
        "Strait of Hormuz",
        "IAEA",
        "Security Council",
        "Trump",
        "White House",
        "executive order",
        "tariff",
        "China",
        "Taiwan",
        "PLA",
        "Taiwan Strait",
        "South China Sea",
        "Xi Jinping",
        "TSMC",
        "oil tanker",
        "OPEC",
        "crude",
    ]
    seen: set[str] = set()
    ordered_terms: list[str] = []

    for term in preferred_terms + keywords:
        clean = term.strip()
        if not clean:
            continue
        key = clean.casefold()
        if key in seen or key in _GENERIC_TOPIC_KEYWORDS:
            continue
        seen.add(key)
        ordered_terms.append(clean)
        if len(ordered_terms) >= 24:
            break

    return " | ".join(ordered_terms) if ordered_terms else "Iran | Taiwan | Trump | Strait of Hormuz"


def parse_published_at(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def article_sort_key(item: NewsItem) -> tuple[datetime, int]:
    return parse_published_at(item.published), source_rank(item.source, item.url)


def sort_articles(items: list[NewsItem]) -> list[NewsItem]:
    return sorted(items, key=article_sort_key, reverse=True)


def match_topic_clusters(text: str) -> set[str]:
    matched: set[str] = set()
    for cluster in TOPIC_CLUSTERS:
        anchors = matched_terms(text, cluster.anchors)
        contexts = matched_terms(text, cluster.contexts)
        if anchors and (contexts or len(anchors) >= 2):
            matched.add(cluster.name)
    return matched


def has_keyword_signal(text: str, keywords: list[str]) -> bool:
    keyword_hits = matched_terms(text, keywords)
    specific_hits = {
        hit for hit in keyword_hits
        if hit.casefold() not in _GENERIC_TOPIC_KEYWORDS
    }
    context_hits = matched_terms(text, _GLOBAL_CONTEXT_TERMS)
    return len(specific_hits) >= 2 or (bool(specific_hits) and bool(context_hits))


def has_stopword_signal(text: str, stopwords: list[str]) -> bool:
    return bool(matched_terms(text, stopwords))


def is_relevant_article(title: str, summary: str, url: str, keywords: list[str]) -> bool:
    if is_blocked_format(title, url):
        return False

    full_text = f"{title}\n{summary}\n{url}"
    return bool(match_topic_clusters(full_text) or has_keyword_signal(full_text, keywords))


def is_quality_api_article(title: str, url: str, source: str) -> bool:
    if is_blocked_format(title, url):
        return False
    return source_rank(source, url) >= MIN_API_SOURCE_RANK


def event_tokens(title: str, url: str = "") -> set[str]:
    slug_text = " ".join(_slug_tokens(url))
    tokens = set(re.findall(r"[a-z0-9]{3,}", f"{title} {slug_text}".casefold()))
    normalized: set[str] = set()
    for token in tokens:
        if token in _EVENT_STOPWORDS:
            continue
        canonical = _EVENT_SYNONYMS.get(token, token)
        if len(canonical) > 4:
            canonical = canonical[:5]
        normalized.add(canonical)
    return normalized
