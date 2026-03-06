# Геополитический Telegram Бот — Контекст для Copilot

## Что это

Telegram-бот для автоматической агрегации и публикации геополитических новостей (фокус — Иран и Ближний Восток). Каждые 3 часа (настраиваемо) бот собирает новости из RSS и TheNewsAPI, фильтрует по ключевым словам/стоп-словам, отправляет в LLM (GPT-4o-mini через OpenRouter) для отбора 5 самых важных новостей, формирует русскоязычную сводку и публикует в Telegram-канал.

## Стек

- **Python 3.11+**, async (asyncio)
- **aiogram 3.x** — Telegram Bot API
- **feedparser** — парсинг RSS
- **aiohttp** — HTTP-клиент (TheNewsAPI, OpenRouter)
- **aiosqlite** — async SQLite (курсор, дедупликация, настройки)
- **APScheduler** (AsyncIOScheduler) — планировщик циклов
- **python-dotenv** — загрузка .env
- **Docker + docker-compose** — деплой

## Структура проекта

```
novosti/
├── bot/
│   ├── main.py               # Точка входа, run_cycle(), scheduler
│   ├── config.py             # ENV: TELEGRAM_BOT_TOKEN, CHANNEL_ID, OPENROUTER_API_KEY, THENEWSAPI_KEY, ADMIN_IDS
│   ├── __init__.py
│   ├── fetcher/
│   │   ├── models.py         # NewsItem dataclass (title, url, source, published)
│   │   ├── rss.py            # 10 RSS-фидов, фильтрация по keywords/stopwords
│   │   └── thenewsapi.py     # TheNewsAPI клиент (до 50 статей)
│   ├── cursor/
│   │   └── manager.py        # SQLite: cursor, seen_urls, topics, stopwords, settings, summaries (~310 строк)
│   ├── summarizer/
│   │   └── llm.py            # OpenRouter GPT-4o-mini, выбор 5 новостей, русский промпт
│   ├── poster/
│   │   └── telegram.py       # Публикация в канал (HTML), split по 4096 символов, retry
│   └── admin/
│       └── router.py         # Админ-панель через inline-клавиатуру (~579 строк)
├── data/
│   └── bot.db                # SQLite база
├── logs/
│   └── bot.log
├── .env                      # Секреты (не коммитить)
├── .github/workflows/deploy.yml  # CI/CD: push в main → SSH → git pull → docker compose up --build
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── geopolitics-bot-tz.md     # Оригинальное ТЗ
└── geopolitics-bot-changelog-v2.md  # Changelog v2: GDELT удалён → RSS+TheNewsAPI
```

## Ключевая логика (run_cycle)

1. Курсор из SQLite → время последней проверки
2. Параллельный fetch: RSS (10 фидов) + TheNewsAPI
3. Дедупликация по URL + фильтр seen_urls
4. Лимит 60 статей → LLM (GPT-4o-mini)
5. LLM выбирает 5 важнейших, сводка на русском с цитатами [N]
6. Цитаты [N] → ссылки на источники
7. Публикация в Telegram (HTML, split если > 4096)
8. Отчёт об отклонённых → админам в DM
9. Обновление курсора и seen_urls

## БД (SQLite — data/bot.db)

- `cursor` — время последнего цикла
- `seen_urls` — дедупликация (TTL 7 дней)
- `topics` — ~80+ ключевых слов (Иран/геополитика)
- `stopwords` — блокировка нерелевантного
- `settings` — KV (interval_hours и др.)
- `summaries` — последние 5 сводок (контекст для LLM)

## Админ-панель (Telegram)

- `/admin` — меню: topics, stopwords, интервал, сброс курсора
- `/post` — принудительный цикл
- `/myid` — ID пользователя
- Inline-клавиатура, FSM для ввода

## Деплой

- **Задеплоен на VPS** (`/opt/novosti`)
- **GitHub Actions**: push в `main` → SSH на VPS → `git pull` → `docker compose up --build -d`
- Docker: `python -m bot.main`

## Соглашения

- Код: Python, комментарии/промпты — русский
- Все сетевые вызовы — async (aiohttp)
- Retry: LLM 3×, Telegram 3×
- ENV в config.py, секреты в .env
- ~1100 строк кода всего
