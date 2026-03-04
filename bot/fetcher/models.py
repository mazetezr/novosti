from dataclasses import dataclass


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: str  # ISO datetime string
