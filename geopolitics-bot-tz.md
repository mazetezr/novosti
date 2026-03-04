# ТЗ — Геополитический Telegram Бот

## Обзор

Бот автоматически собирает актуальные новости по геополитике, войнам, конфликтам и мировым активам из нескольких источников, формирует структурированную сводку через LLM и публикует её в Telegram-канал каждые **3 часа** и прилагаються ссылки с источниками вестей.

Дублирование исключается через систему курсора — каждый цикл забирает только новости, опубликованные **после последней проверки**.

---

## Стек

| Компонент | Инструмент |
|---|---|
| Язык | Python 3.11+ |
| Telegram | aiogram 3.x |
| Новости (основной) | GDELT DOC API v2 |
| Новости (резерв) | RSS через feedparser |
| LLM суммаризация | GPT-4o-mini через OpenRouter |
| Планировщик | APScheduler |
| Хранилище курсора | SQLite (через aiosqlite) |
| Хостинг | VPS (Linux) |
| Деплой | Docker + docker-compose |

---

## Архитектура

```
┌─────────────────────────────────────────┐
│              Scheduler (APScheduler)    │
│         запуск каждые 3 часа            │
└────────────────┬────────────────────────┘
                 │
        ┌────────▼────────┐
        │  Fetcher Module │
        │  ┌────────────┐ │
        │  │ GDELT API  │ │  ← основной источник
        │  └────────────┘ │
        │  ┌────────────┐ │
        │  │ RSS Parser │ │  ← резервный источник
        │  └────────────┘ │
        └────────┬────────┘
                 │
        ┌────────▼────────┐
        │ Cursor Manager  │  ← фильтрация по времени,
        │   (SQLite)      │     дедупликация по URL
        └────────┬────────┘
                 │
        ┌────────▼────────┐
        │  LLM Summarizer │  ← OpenRouter / GPT-4o-mini
        └────────┬────────┘
                 │
        ┌────────▼────────┐
        │ Telegram Poster │  ← публикация в канал
        └─────────────────┘
```

---

## Модули

### 1. `fetcher/gdelt.py` — GDELT клиент

**Эндпоинт:**
```
https://api.gdeltproject.org/api/v2/doc/doc
  ?query={query}
  &mode=artlist
  &maxrecords=50
  &startdatetime={cursor}
  &format=json
  &sourcelang=english
```

**Поисковые запросы (темы):**

| Тема | Query |
|---|---|
| Иран / США | `Iran USA military conflict sanctions` |
| Войны и конфликты | `war conflict military attack airstrike` |
| Израиль / Ближний Восток | `Israel Gaza Hamas Lebanon Hezbollah` |
| Украина | `Ukraine Russia war Zelensky frontline` |
| Мировые рынки/активы | `oil price gold markets sanctions economy` |
| Ядерная угроза | `nuclear weapons threat IAEA` |

**Поведение:**
- `startdatetime` — берётся из курсора (время последней успешной проверки)
- Результаты объединяются, дедуплицируются по URL
- Если GDELT вернул ошибку или пустой ответ → fallback на RSS

---

### 2. `fetcher/rss.py` — RSS резерв

**Источники:**

| Источник | RSS URL | Фокус |
|---|---|---|
| Reuters World | `https://feeds.reuters.com/reuters/worldNews` | общемировые |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | Ближний Восток |
| BBC World | `http://feeds.bbci.co.uk/news/world/rss.xml` | общемировые |
| Middle East Eye | `https://www.middleeasteye.net/rss` | Иран, регион |
| Defense News | `https://www.defensenews.com/rss/` | военные события |
| Axios World | `https://api.axios.com/feed/` | США/геополитика |

**Поведение:**
- Парсинг через `feedparser`
- Фильтрация по `entry.published_parsed` — только записи новее курсора
- Фильтрация по ключевым словам в заголовке/описании (список ниже)
- Дедупликация по URL совместно с GDELT-результатами

**Ключевые слова для фильтрации RSS:**
```python
KEYWORDS = [
    "war", "conflict", "military", "attack", "airstrike", "missile",
    "Iran", "Israel", "Gaza", "Ukraine", "Russia", "Hamas", "Hezbollah",
    "sanctions", "nuclear", "troops", "offensive", "ceasefire",
    "oil", "OPEC", "gold", "markets", "economy", "inflation"
]
```

---

### 3. `cursor/manager.py` — Курсор и дедупликация

**Таблицы SQLite:**

```sql
-- Время последней успешной отправки
CREATE TABLE IF NOT EXISTS cursor (
    id INTEGER PRIMARY KEY,
    last_run_at DATETIME NOT NULL
);

-- Уже обработанные URL (антидубль)
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    seen_at DATETIME NOT NULL
);
```

**Логика:**
1. При старте цикла — читаем `last_run_at` из таблицы `cursor`
2. Если записи нет (первый запуск) — берём `NOW() - 3 hours`
3. Все полученные URL проверяем через `seen_urls` — уже виденные отбрасываем
4. После успешной публикации — обновляем `last_run_at = NOW()`, добавляем URL в `seen_urls`
5. `seen_urls` чистится раз в 7 дней (TTL по полю `seen_at`)

---

### 4. `summarizer/llm.py` — LLM суммаризация

**Провайдер:** OpenRouter  
**Модель:** `openai/gpt-4o-mini`  
**Эндпоинт:** `https://openrouter.ai/api/v1/chat/completions`

**Системный промпт:**
```
Ты — редактор геополитического новостного канала. 
Твоя задача — на основе списка заголовков новостей составить 
структурированную сводку на русском языке.

Правила:
- Группируй по темам: Иран/США, Ближний Восток, Украина/Россия, 
  Мировые рынки, Прочее
- Пиши коротко и ёмко — 1-3 предложения на событие
- Указывай причины движений (рост напряжённости, санкции и т.д.)
- Если новостей по теме нет — тему не включай
- Не добавляй ничего от себя — только факты из переданных заголовков
- Формат — Telegram-совместимый (без markdown таблиц, только текст и эмодзи)
- Оставляй ссылки с источниками новостей.
```

**Пользовательский промпт:**
```
Вот заголовки новостей за последние 3 часа. Составь сводку:

{список заголовков с источником и временем}
```

**Лимиты:**
- `max_tokens: 1500`
- `temperature: 0.3`

---

### 5. `poster/telegram.py` — Публикация

**Формат поста:**
```
🌍 ГЕОПОЛИТИЧЕСКАЯ СВОДКА
📅 {дата} | 🕐 {время UTC+2}

🔥 ИРАН / США
...текст сводки...

⚔️ БЛИЖНИЙ ВОСТОК
...

🪖 УКРАИНА / РОССИЯ
...

💹 МИРОВЫЕ РЫНКИ
...

📌 ПРОЧЕЕ
...
```

**Поведение:**
- Если пост > 4096 символов (лимит Telegram) — разбивается на части
- `parse_mode=None` (чистый текст, без HTML/Markdown) по умолчанию, опционально `HTML`
- При ошибке отправки — retry 3 раза с задержкой 10 сек

---

## Структура проекта

```
geopolitics-bot/
├── bot/
│   ├── main.py               # точка входа, запуск scheduler
│   ├── config.py             # ENV переменные
│   ├── fetcher/
│   │   ├── gdelt.py
│   │   └── rss.py
│   ├── cursor/
│   │   └── manager.py
│   ├── summarizer/
│   │   └── llm.py
│   └── poster/
│       └── telegram.py
├── data/
│   └── bot.db                # SQLite (cursor + seen_urls)
├── logs/
│   └── bot.log
├── .env
├── requirements.txt
└── docker-compose.yml
```

---

## Конфигурация `.env`

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID=@your_channel   # или числовой ID
OPENROUTER_API_KEY=...
CHECK_INTERVAL_HOURS=3
LOG_LEVEL=INFO
```

---

## `requirements.txt`

```
aiogram==3.x
feedparser
aiohttp
aiosqlite
apscheduler
python-dotenv
```

---

## `docker-compose.yml`

```yaml
version: "3.9"
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
```

---

## Логика цикла (псевдокод)

```python
async def run_cycle():
    cursor = await get_cursor()             # читаем время последней проверки

    gdelt_news = await fetch_gdelt(cursor)  # GDELT за период
    rss_news   = await fetch_rss(cursor)    # RSS за период

    all_news = deduplicate(gdelt_news + rss_news)  # по URL + seen_urls из БД
    new_news = filter_seen(all_news)

    summary = await summarize(new_news)     # LLM сводка
    await post_to_channel(summary)          # публикация

    await update_cursor(now())              # обновляем курсор
    await mark_seen(new_news)               # сохраняем URL в seen_urls
```

---

## Обработка ошибок

| Ситуация | Действие |
|---|---|
| GDELT недоступен | fallback на RSS, лог WARNING |
| RSS все недоступны | лог ERROR, цикл пропускается |
| LLM ошибка / таймаут | retry 2 раза, затем пропуск цикла |
| Telegram ошибка отправки | retry 3 раза × 10 сек |

---

## MVP — приоритет разработки

1. `cursor/manager.py` — база и курсор
2. `fetcher/gdelt.py` — GDELT клиент
3. `fetcher/rss.py` — RSS резерв
4. `summarizer/llm.py` — LLM через OpenRouter
5. `poster/telegram.py` — постинг
6. `bot/main.py` — сборка + scheduler
7. Docker + деплой на VPS
