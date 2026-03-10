# Геополитический Telegram Бот — Контекст для Copilot

## Что это

Telegram-бот для автоматической агрегации и публикации геополитических новостей (фокус — Иран и Ближний Восток). Каждые N часов (настраиваемо, по умолчанию 3) бот собирает новости из RSS и TheNewsAPI, фильтрует по ключевым словам/стоп-словам, отправляет в LLM (GPT-4o-mini через OpenRouter) для отбора важнейших новостей (кол-во настраивается, по умолчанию 5), формирует русскоязычную сводку и публикует в Telegram-канал.

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
│   ├── state.py              # Singleton-хранилище scheduler (обход __main__ vs bot.main)
│   ├── config.py             # ENV: TELEGRAM_BOT_TOKEN, CHANNEL_ID, OPENROUTER_API_KEY, THENEWSAPI_KEY, ADMIN_IDS
│   ├── __init__.py
│   ├── fetcher/
│   │   ├── models.py         # NewsItem dataclass (title, url, source, published)
│   │   ├── rss.py            # 10 RSS-фидов, фильтрация по keywords/stopwords
│   │   └── thenewsapi.py     # TheNewsAPI клиент (до 50 статей)
│   ├── cursor/
│   │   └── manager.py        # SQLite: cursor, seen_urls, topics, stopwords, settings, summaries (~310 строк)
│   ├── summarizer/
│   │   └── llm.py            # OpenRouter GPT-4o-mini, динамический news_count, русский промпт
│   ├── poster/
│   │   └── telegram.py       # Публикация в канал (HTML), split по 4096 символов, retry
│   └── admin/
│       └── router.py         # Админ-панель через inline-клавиатуру (~650 строк)
├── data/
│   └── bot.db                # SQLite база
├── logs/
│   └── bot.log
├── .env                      # Секреты (не коммитить)
├── .github/
│   ├── workflows/deploy.yml  # CI/CD: push в main → SSH → git pull → docker compose up --build
│   └── copilot-instructions.md  # Этот файл — контекст проекта для Copilot
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── geopolitics-bot-tz.md     # Оригинальное ТЗ (v1, устарело — GDELT удалён)
└── geopolitics-bot-changelog-v2.md  # Changelog v2: GDELT удалён → RSS+TheNewsAPI
```

## Ключевая логика (run_cycle в main.py)

1. Курсор из SQLite → время последней проверки
2. Параллельный fetch: RSS (10 фидов) + TheNewsAPI
3. Дедупликация по URL + фильтр seen_urls
4. Лимит 60 статей → LLM (GPT-4o-mini)
5. LLM выбирает N важнейших (настройка `news_count`), сводка на русском с цитатами [N]
6. Цитаты [N] → ссылки на источники (regex замена)
7. Публикация в Telegram (HTML, split если > 4096)
8. Логирование отсеянных статей в bot.log (ранее отправлялись админам в DM — закомментировано)
9. Обновление курсора и seen_urls

## БД (SQLite — data/bot.db)

- `cursor` — время последнего цикла
- `seen_urls` — дедупликация (TTL 7 дней)
- `topics` — ~80+ ключевых слов (Иран/геополитика)
- `stopwords` — блокировка нерелевантного
- `settings` — KV-хранилище:
  - `interval_hours` — частота циклов (по умолчанию 3)
  - `news_count` — кол-во новостей в посте (по умолчанию 5, диапазон 1–20)
- `summaries` — последние 5 сводок (контекст для LLM, антидубль)

## Админ-панель (Telegram)

- `/admin` — главное меню с inline-клавиатурой:
  - 📋 Список тем / ➕ Добавить / 🗑 Удалить
  - 🚫 Стоп-слова (добавить/удалить)
  - 🕐 Частота постов (1–24ч, быстрый выбор + ручной ввод)
  - 📰 Кол-во новостей (3/5/7/8/10/15 или вручную 1–20)
  - 🔄 Сброс курсора (3–72ч назад)
- `/post` — принудительный запуск цикла
- `/myid` — ID пользователя
- `/topics`, `/addtopic`, `/deltopic`, `/resettopics` — текстовое управление темами
- FSM (AdminFSM) для ввода значений

## Деплой

- **Задеплоен на VPS** (`/opt/novosti`)
- **GitHub Actions** (`deploy.yml`): push в `main` → SSH на VPS → `git pull` → `docker compose up --build -d`
- Docker: `python -m bot.main`
- Секреты в GitHub: `SERVER_HOST`, `SERVER_USER`, `SSH_PRIVATE_KEY`, `REPO_URL`

## Соглашения

- Код: Python, комментарии/промпты на русском
- Все сетевые вызовы — async (aiohttp)
- Retry: LLM 3×, Telegram 3× с задержкой
- ENV в config.py, секреты в .env
- ~1200 строк кода всего
- Вебхуки для новостей невозможны — RSS и TheNewsAPI поддерживают только polling

## История сессий

### Сессия 2026-03-06
- Изучен весь проект, создан этот файл copilot-instructions.md
- Добавлена настройка кол-ва новостей в посте (`news_count`) — промпт LLM, main.py, админ-панель
- Обсуждено качество фильтрации: отсеивание в целом хорошее, но при высокой активности 5 новостей мало — рекомендовано увеличить до 7–8

### Сессия 2026-03-10
- **Исправлен баг с частотой постинга**: при `python -m bot.main` модуль грузился как `__main__`, а `admin/router.py` импортировал `bot.main` — Python считал их разными модулями, `get_scheduler()` возвращал `None`, reschedule не работал. Создан `bot/state.py` — единое хранилище scheduler для всего процесса.
- **Отсеянные статьи → логи**: отчёт об отклонённых статьях теперь пишется в `logs/bot.log` вместо DM админам. Функция `_send_rejected_report` в main.py закомментирована (не удалена).
