# Геополитический Telegram Бот — Контекст для Copilot

## Что это

Telegram-бот для автоматической агрегации и публикации геополитических новостей (фокус — Иран, Ближний Восток, Китай/Тайвань, Трамп/США). Каждые N часов (настраиваемо, по умолчанию 3) бот собирает новости из RSS и TheNewsAPI, фильтрует по ключевым словам/стоп-словам, отправляет в LLM (GPT-4o-mini через OpenRouter) для отбора важнейших новостей (кол-во настраивается, по умолчанию 5), формирует русскоязычную сводку и публикует в Telegram-канал.

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
│   │   ├── rss.py            # 17 RSS-фидов, фильтрация по keywords/stopwords
│   │   ├── thenewsapi.py     # TheNewsAPI клиент (до 50 статей)
│   │   └── trump.py          # (файл есть, не используется — архив Truth Social мёртв с 2022)
│   ├── cursor/
│   │   └── manager.py        # SQLite: cursor, seen_urls, topics, stopwords, settings, summaries
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

## RSS-фиды (bot/fetcher/rss.py) — 17 источников

| Источник | Категория |
|---|---|
| Reuters World | Глобальные |
| Al Jazeera | Глобальные |
| BBC World | Глобальные |
| Associated Press | Глобальные |
| France 24 (Middle East) | Ближний Восток |
| Middle East Eye | Ближний Восток |
| Times of Israel | Ближний Восток |
| Iran International | Иран |
| Axios World | Глобальные |
| Defense News | Оборона |
| Reuters Politics | Трамп/США |
| Politico | Трамп/США |
| White House (whitehouse.gov/feed/) | Официальные заявления Трампа |
| Reuters Asia | Китай/Тайвань |
| South China Morning Post | Китай/Тайвань |
| The Diplomat | Китай/Тайвань/Индо-Тихоокеанский регион |
| Taiwan News | Тайвань |

## Ключевая логика (run_cycle в main.py)

1. Курсор из SQLite → время последней проверки
2. Параллельный fetch: RSS (17 фидов) + TheNewsAPI
3. Дедупликация по URL + фильтр seen_urls
4. Лимит 60 статей → Python-дедуп → LLM (GPT-4o-mini)
5. Python-дедуп: `filter_by_previous_titles` (threshold=0.60) + `cluster_similar_articles` (threshold=0.45)
6. LLM выбирает N важнейших (настройка `news_count`), сводка на русском с цитатами [N]
7. Цитаты [N] → ссылки на источники (regex замена)
8. Публикация в Telegram (HTML, split если > 4096)
9. Логирование отсеянных статей в bot.log
10. Обновление курсора и seen_urls

## Python-дедупликация (bot/utils/dedup.py)

- `filter_by_previous_titles(articles, prev_titles, threshold=0.60)` — убирает статьи, чьи заголовки слишком похожи на уже опубликованные. Метрика: overlap coefficient (|A∩B| / min(|A|,|B|)) по 4-char стемированным словам. **Порог 0.60** — только явные дубли.
- `cluster_similar_articles(articles, threshold=0.45)` — кластеризует разные источники об одном событии, оставляет одну статью на кластер. Метрика: Jaccard. **Порог 0.45**.
- Оба порога настроены эмпирически: слишком низкие (0.35/0.30) убивали релевантные новости про Трампа и нефть.

## БД (SQLite — data/bot.db)

- `cursor` — время последнего цикла
- `seen_urls` — дедупликация (TTL 7 дней)
- `topics` — ~110 ключевых слов (Иран/геополитика + Трамп/нефть + Китай/Тайвань)
- `stopwords` — блокировка нерелевантного
- `settings` — KV-хранилище:
  - `interval_hours` — частота циклов (по умолчанию 3)
  - `news_count` — кол-во новостей в посте (по умолчанию 5, диапазон 1–20)
- `summaries` — последние 5 сводок (контекст для LLM, антидубль)

## Ключевые слова (cursor/manager.py)

**DEFAULT_TOPICS** (~30): Иран/КСИР/ядерка, Ближний Восток, Израиль, США/Пентагон, Трамп, нефть/ОПЕК, **China/Taiwan/Xi Jinping/PLA/CCP/Beijing/Taiwan Strait/South China Sea/semiconductor/chip war/PRC/TSMC/cross-strait**

**EXTRA_TOPICS** (~50): расширенный Иран (Натанз, Кудс и др.), **PLA Navy/Air Force, Lai Ching-te, Huawei, SMIC, export controls, East China Sea, Spratlys, amphibious, Taiwan Relations Act, arms sales Taiwan** и др.

**DEPRECATED_TOPICS**: Украина/Россия/НАТО, Африка, Латинская Америка, крипто, внутриполитическая рутина. China/Taiwan/Xi Jinping убраны из deprecated в сессии 2026-03-11.

## Промпт LLM (summarizer/llm.py)

Канал освещает 4 темы (все в системном промпте):
1. **Иран** — ядерная программа, КСИР, прокси-войны
2. **Китай и Тайвань** — учения НОАК, кризис в Тайваньском проливе
3. **Трамп и США** — внешняя политика, тарифы, ультиматумы
4. **Нефть и энергетика** — если связана с геополитикой (Ормуз, ОПЕК+, санкции)

Приоритет отбора: угрозы/ультиматумы → перемещение войск → конкретные инциденты → ядерка/чипы → дипломатия → нефть. Рутина (Ливан/Хезболла каждый день, беженцы, аналитика, спорт) — в последнюю очередь.

## Админ-панель (Telegram)

- `/admin` — главное меню с inline-клавиатурой:
  - 📋 Список тем / ➕ Добавить / 🗑 Удалить
  - 🚫 Стоп-слова (добавить/удалить)
  - 🕐 Частота постов (1–24ч, быстрый выбор + ручной ввод)
  - 📰 Кол-во новостей (3/5/7/8/10/15 или вручную 1–20)
  - 🔄 Сброс курсора (3–72ч назад)
- `/post` — принудительный запуск цикла + **сброс таймера** (следующий авто-пост через interval_hours от момента ручного запуска)
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
- ~1300 строк кода всего
- Вебхуки для новостей невозможны — RSS и TheNewsAPI поддерживают только polling

## История сессий

### Сессия 2026-03-06
- Изучен весь проект, создан этот файл copilot-instructions.md
- Добавлена настройка кол-ва новостей в посте (`news_count`) — промпт LLM, main.py, админ-панель
- Обсуждено качество фильтрации: отсеивание в целом хорошее, но при высокой активности 5 новостей мало — рекомендовано увеличить до 7–8

### Сессия 2026-03-10
- **Исправлен баг с частотой постинга**: при `python -m bot.main` модуль грузился как `__main__`, а `admin/router.py` импортировал `bot.main` — Python считал их разными модулями, `get_scheduler()` возвращал `None`, reschedule не работал. Создан `bot/state.py` — единое хранилище scheduler для всего процесса.
- **Отсеянные статьи → логи**: отчёт об отклонённых статьях теперь пишется в `logs/bot.log` вместо DM админам. Функция `_send_rejected_report` в main.py закомментирована (не удалена).

### Сессия 2026-03-11 (утро)
- **Добавлены источники про Трампа**: RSS-фиды Reuters Politics, Politico + White House (официальные заявления/указы). Ключевые слова пополнены: `Trump`, `White House`, `tariff`, `executive order`, `oil`, `OPEC`, `crude`, `energy`.
- **Попытка Truth Social**: создан `bot/fetcher/trump.py` для архива Truth Social постов. Архив мёртв (последний пост — февраль 2022). Фетчер отключён (файл оставлен), вместо него добавлен White House RSS.

### Сессия 2026-03-11 (вечер)
- **Мониторинг Китая/Тайваня**: добавлены 4 RSS-фида (Reuters Asia, South China Morning Post, The Diplomat, Taiwan News). Ключевые слова China/Taiwan/Xi Jinping/PLA/CCP/TSMC и др. добавлены в DEFAULT_TOPICS и EXTRA_TOPICS. China/Taiwan/Xi Jinping убраны из DEPRECATED_TOPICS.
- **Reschedule после `/post`**: ручной `/post` теперь сбрасывает таймер планировщика — следующий авто-пост будет ровно через `interval_hours` от момента ручного запуска (а не в ранее запланированное время).
- **Исправлен агрессивный дедуп**: threshold `filter_by_previous_titles` поднят 0.35→0.60, `cluster_similar_articles` 0.30→0.45. Прежние пороги убивали релевантные новости про Трампа и нефть.
- **Расширен промпт LLM**: был "редактор канала об Иране" — стал охватывать все 4 темы (Иран, Китай/Тайвань, Трамп/США, нефть/энергетика). Добавлены примеры с тайваньскими учениями в шаблон промпта.

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
│   │   ├── rss.py            # 13 RSS-фидов, фильтрация по keywords/stopwords
│   │   ├── thenewsapi.py     # TheNewsAPI клиент (до 50 статей)
│   │   └── trump.py          # (файл есть, не используется — архив Truth Social мёртв с 2022)
│   ├── cursor/
│   │   └── manager.py        # SQLite: cursor, seen_urls, topics, stopwords, settings, summaries
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

## RSS-фиды (bot/fetcher/rss.py) — 13 источников

| Источник | Категория |
|---|---|
| Reuters World | Глобальные |
| Al Jazeera | Глобальные |
| BBC World | Глобальные |
| Associated Press | Глобальные |
| France 24 (Middle East) | Ближний Восток |
| Middle East Eye | Ближний Восток |
| Times of Israel | Ближний Восток |
| Iran International | Иран |
| Axios World | Глобальные |
| Defense News | Оборона |
| Reuters Politics | Трамп/США |
| Politico | Трамп/США |
| White House (whitehouse.gov/feed/) | Официальные заявления Трампа |

## Ключевая логика (run_cycle в main.py)

1. Курсор из SQLite → время последней проверки
2. Параллельный fetch: RSS (13 фидов) + TheNewsAPI
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
- `topics` — ~90 ключевых слов (Иран/геополитика + Трамп/нефть)
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

### Сессия 2026-03-11
- **Добавлены источники про Трампа**: RSS-фиды Reuters Politics, Politico + White House (официальные заявления/указы). Ключевые слова пополнены: `Trump`, `White House`, `tariff`, `executive order`, `oil`, `OPEC`, `crude`, `energy` (`oil`/`OPEC` убраны из DEPRECATED — релевантны для Ирана).
- **Попытка Truth Social**: создан `bot/fetcher/trump.py` для архива Truth Social постов (CNN/GitHub JSON). Выяснилось, что архив мёртв (последний пост — февраль 2022). Фетчер отключён (файл оставлен), вместо него добавлен White House RSS.
- **Замечание по дедупу**: агрессивный дедуп (threshold 0.35/0.30) иногда отфильтровывает релевантные трамповские статьи как похожие на предыдущие сводки — норм поведение, следить в логах.
