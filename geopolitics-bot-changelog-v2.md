# Changelog ТЗ — v1 → v2

## Причина обновления

GDELT DOC API удалён из архитектуры. Причина — агрессивный rate limiting со стороны GDELT в периоды высокой геополитической активности. API молча зависает без ответа, что делает его ненадёжным как основной источник.

---

## Изменения

### Источники новостей

**Было:**
- Основной: GDELT DOC API
- Резерв: RSS (feedparser)

**Стало:**
- Основной №1: RSS (feedparser)
- Основной №2: TheNewsAPI (бесплатный план, 100 req/день)

Оба источника запускаются параллельно в каждом цикле. Результаты объединяются и дедуплицируются по URL перед передачей в LLM.

---

### RSS источники (основной)

| Источник | RSS URL | Фокус |
|---|---|---|
| Reuters World | `feeds.reuters.com/reuters/worldNews` | общемировые |
| Al Jazeera | `aljazeera.com/xml/rss/all.xml` | Ближний Восток |
| Middle East Eye | `middleeasteye.net/rss` | Иран / Израиль |
| BBC World | `feeds.bbci.co.uk/news/world/rss.xml` | общий фон |
| Axios World | `api.axios.com/feed/` | США / геополитика |
| Defense News | `defensenews.com/rss/` | военные события |

Фильтрация по ключевым словам в заголовке/описании + по дате публикации (новее курсора).

---

### TheNewsAPI (основной, параллельно с RSS)

Запускается одновременно с RSS в каждом цикле, не как fallback.

- Эндпоинт: `https://api.thenewsapi.com/v1/news/all`
- Параметры: `search=war conflict Iran Israel Ukraine`, `language=en`, `published_after={cursor}`
- Бесплатный план: 100 запросов/день — при цикле раз в 3 часа = 8 запросов/день, лимит не превышается

---

### Удалено из кода

- `fetcher/gdelt.py` — модуль удаляется полностью
- Все GDELT-специфичные query-параметры (`startdatetime`, `maxrecords`, `sourcelang`, `theme`)

---

### Без изменений

- Курсор и дедупликация (SQLite) — без изменений
- LLM суммаризация (OpenRouter / GPT-4o-mini) — без изменений
- Telegram постер — без изменений
- Scheduler (APScheduler, каждые 3 часа) — без изменений
- Docker / docker-compose — без изменений
- Расчёт стоимости — без изменений (~$0.3–1/месяц)
