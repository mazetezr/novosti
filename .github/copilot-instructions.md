# Геополитический Telegram Бот — Контекст для Copilot

## Что это

Telegram-бот для автоматической агрегации и публикации геополитических новостей. Основные темы: Иран, Ближний Восток, Китай/Тайвань, Трамп/США, нефть и энергетика в геополитическом контексте.

Каждые N часов (настраиваемо, по умолчанию 3) бот:

1. забирает новости из RSS и TheNewsAPI;
2. фильтрует их по тематическим кластерам, co-occurrence и стоп-словам;
3. ранжирует статьи по свежести, качеству источника и event importance;
4. убирает дубли по URL, прошлым постам и похожим событиям;
5. дополнительно режет пул до strongest candidates перед LLM;
6. получает русскоязычную сводку и публикует её в Telegram-канал.

## Стек

- **Python 3.11+**, async (`asyncio`)
- **aiogram 3.x** — Telegram Bot API
- **feedparser** — парсинг RSS
- **aiohttp** — HTTP-клиент
- **aiosqlite** — async SQLite
- **APScheduler** (`AsyncIOScheduler`) — планировщик
- **python-dotenv** — загрузка `.env`
- **Docker + docker-compose** — деплой

## Структура проекта

```text
novosti/
├── bot/
│   ├── main.py                    # Точка входа, run_cycle(), scheduler
│   ├── state.py                   # Единое хранилище scheduler
│   ├── config.py                  # ENV: TELEGRAM_BOT_TOKEN, CHANNEL_ID, OPENROUTER_API_KEY, THENEWSAPI_KEY, ADMIN_IDS
│   ├── admin/
│   │   └── router.py              # Админ-панель
│   ├── cursor/
│   │   └── manager.py             # SQLite: cursor, seen_urls, topics, stopwords, settings, summaries
│   ├── fetcher/
│   │   ├── models.py              # NewsItem dataclass
│   │   ├── rss.py                 # 17 RSS-фидов + фильтрация
│   │   ├── thenewsapi.py          # TheNewsAPI + quality/source filter
│   │   └── trump.py               # Не используется, архивный фетчер
│   ├── poster/
│   │   └── telegram.py            # Публикация в канал
│   ├── summarizer/
│   │   └── llm.py                 # OpenRouter GPT-4o-mini, русский prompt
│   └── utils/
│       ├── dedup.py               # Python-level дедупликация событий
│       └── news_priority.py       # Topic-кластеры, source rank, URL stoplist, sorting helpers
├── data/
│   └── bot.db                     # SQLite база
├── logs/
│   └── bot.log
├── .github/
│   ├── workflows/deploy.yml
│   └── copilot-instructions.md    # Этот файл
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## RSS-фиды (bot/fetcher/rss.py) — 17 источников

| Источник | Категория |
|---|---|
| Reuters World | Глобальные |
| Al Jazeera | Глобальные |
| BBC World | Глобальные |
| Associated Press | Глобальные |
| France 24 | Ближний Восток |
| Middle East Eye | Ближний Восток |
| Times of Israel | Ближний Восток |
| Iran International | Иран |
| Axios World | Глобальные |
| Defense News | Оборона |
| Reuters Politics | Трамп/США |
| Politico | Трамп/США |
| White House | Официальные заявления США |
| Reuters Asia | Китай/Тайвань |
| South China Morning Post | Китай/Тайвань |
| The Diplomat | Индо-Тихоокеанский регион |
| Taiwan News | Тайвань |

## Ключевая логика `run_cycle()` (bot/main.py)

1. Берётся курсор последнего цикла из SQLite.
2. Параллельно запускаются `fetch_rss()` и `fetch_thenewsapi()`.
3. Выполняется дедупликация по URL.
4. Отфильтровываются уже виденные URL через `seen_urls`.
5. Кандидаты **всегда сортируются до дедупа** по `published desc + source_rank`.
6. Пул режется до 60 статей перед отправкой в LLM.
7. Берутся **10 последних сводок** для антидубля.
8. Python-дедуп:
   - `filter_by_previous_titles(..., threshold=0.60)`
   - `cluster_similar_articles(..., threshold=0.45)`
9. После дедупа вызывается `prioritize_candidates(...)`: в LLM уходит только сильнейший пул, обычно `max(news_count + 3, 8)` статей.
10. LLM выбирает до `news_count` сильнейших карточек.
11. Цитаты `[N]` заменяются на ссылки на источники.
12. Сводка публикуется в Telegram.
13. В БД сохраняются summary, cited_titles, seen_urls и новый cursor.

## Фильтрация и приоритизация (bot/utils/news_priority.py)

### Что добавлено

- **Topic-кластеры** вместо голого substring-match.
- **Co-occurrence логика**: одной общей темы недостаточно, нужны якорные и контекстные сигналы.
- **URL/format stoplist**: режутся `opinion`, `commentary`, `feature`, `live`, `sports`, `podcast`, часть локального Hong Kong/business-контента у SCMP.
- **Low-priority gating**: режутся или резко штрафуются `gallery`, explainers, TV/discover-материалы, solidarity/march stories, generic economy-impact pieces, political mood/process stories.
- **Source rank**: Reuters / AP / BBC / White House / официальные источники выше региональных и вторичных.
- **TheNewsAPI quality filter**: слабые источники и мусорные внешние сайты не проходят.
- **Сортировка до дедупа**: лучший представитель события выбирается не по порядку фидов, а по времени и качеству источника.
- **Priority pruning до LLM**: отбор кандидатов теперь учитывает `source_rank + topic hits + high-impact terms - routine penalties`, чтобы не перегружать модель слабым фоном.

### Почему это важно

Раньше проходили ложные совпадения вроде Papa John's / robot arrested / локальный Hong Kong business-контент из-за широкого substring-match по словам вроде `Qatar`, `China`, `oil`, `Trump`.

Теперь статья должна подтверждаться либо тематическим кластером, либо более сильным keyword-signal с контекстом. Даже после этого слабые типы материалов дополнительно режутся scoring/gating-слоем до LLM.

## Python-дедупликация (bot/utils/dedup.py)

- `filter_by_previous_titles()` сравнивает новые статьи не только по title overlap, но и по **event similarity**.
- `cluster_similar_articles()` группирует статьи об одном событии и оставляет **лучший** материал в кластере по `article_selection_key`, а не только по свежести.
- Для event-level дедупа используются:
  - нормализованные токены события;
  - словарь синонимов (`vessel`/`tanker`/`ship`, `manoeuvre`/`maneuver`, `destruction`/`damage` и т.д.);
  - токены из URL slug, если они помогают распознать событие.
- Для near-duplicates дополнительно используется комбинированное правило `title_similarity + event_similarity`, чтобы схлопывать близкие заголовки даже если общий порог кластера не пробит.

### Пороги

- `filter_by_previous_titles(..., threshold=0.60)` — только явные дубли.
- `cluster_similar_articles(..., threshold=0.45)` — один инфоповод из разных источников.

## TheNewsAPI (bot/fetcher/thenewsapi.py)

- Запрос строится через `build_api_search_query()`, а не через первые 30 keywords подряд.
- После ответа API статьи проходят:
  - quality/source filter;
  - topic relevance filter;
  - stopword/format filter.

Идея: API нужен как дополнительный источник, но не как канал для мусорных внешних сайтов.

## Prompt LLM (bot/summarizer/llm.py)

LLM получает жёсткие инструкции:

- **не добивать до N**, если сильных событий меньше;
- **1 событие = 1 карточка**;
- **operational developments выше риторики**;
- учитывать **source priority**, если одно событие есть у нескольких источников;
- не брать аналитику, opinion, фон и рутину, если есть более сильные события;
- отдельно пропускать side-stories: solidarity marches, galleries, market mood/economy reaction, political process pieces без нового decision/action.

### Приоритет отбора

1. Операционные изменения: перемещения войск, патрули, сопровождение судов, перекрытия, реальные приказы.
2. Конкретные инциденты: атаки, удары, столкновения, санкции/тарифы/экспортные ограничения.
3. Ядерка / чипы / логистика / Ормуз / ОПЕК.
4. Дипломатия и решения.
5. Риторика — только если есть немедленное практическое последствие.
6. Фон — только если сильных событий нет.

## БД (SQLite — data/bot.db)

- `cursor` — время последнего цикла
- `seen_urls` — дедупликация URL, TTL 7 дней
- `topics` — ключевые слова
- `stopwords` — стоп-слова
- `settings`:
  - `interval_hours`
  - `news_count`
- `summaries` — **последние 10 сводок** с `cited_titles` для антидубля

## Ключевые слова (cursor/manager.py)

### DEFAULT_TOPICS

Базовое ядро:

- Иран / КСИР / ядерка / Ормуз
- Ближний Восток
- США / Пентагон / Трамп / tariffs / executive orders
- нефть / OPEC / crude / energy
- Китай / Тайвань / Xi Jinping / PLA / TSMC / Taiwan Strait / South China Sea

### EXTRA_TOPICS

Расширяют покрытие по:

- Natanz / Fordow / Quds Force / CENTCOM / tanker / Security Council
- PLA Navy / PLA Air Force / Lai Ching-te / Huawei / SMIC / export controls / East China Sea / Spratlys / Taiwan Relations Act

### DEPRECATED_TOPICS

Удаляются на старте как нерелевантные:

- Украина / Россия / НАТО
- Африка / Латинская Америка
- крипто
- прочая внутренняя рутина вне фокуса проекта

## Админ-панель

- `/admin` — inline-меню:
  - темы;
  - стоп-слова;
  - частота постов;
  - число новостей;
  - сброс курсора.
- `/post` — ручной запуск цикла **со сбросом таймера** планировщика.
- `/myid`
- `/topics`, `/addtopic`, `/deltopic`, `/resettopics`

## Деплой

- Сервер: `/opt/novosti`
- `deploy.yml`: push в `main` -> SSH -> `git pull` -> `docker compose up --build -d`
- Docker entrypoint: `python -m bot.main`

## Соглашения

- Код на Python, комментарии и prompt-ы на русском.
- Все сетевые вызовы — async.
- Retry: LLM 3 раза, Telegram 3 раза.
- Логи отсеянных статей идут в `logs/bot.log`, не в DM админам.
- Вебхуков для новостей нет: RSS и TheNewsAPI работают по polling.

## История изменений

### 2026-03-06

- изучен проект;
- создан `copilot-instructions.md`;
- добавлена настройка `news_count`.

### 2026-03-10

- исправлен баг с scheduler через `bot/state.py`;
- отчёт по отсеянным статьям перенесён из DM в `bot.log`.

### 2026-03-11

- добавлены источники по Трампу: Reuters Politics, Politico, White House;
- добавлены источники по Китаю/Тайваню: Reuters Asia, SCMP, The Diplomat, Taiwan News;
- `/post` теперь сбрасывает таймер планировщика;
- пороги дедупа ослаблены до безопасных `0.60 / 0.45`;
- prompt расширен с иранского фокуса до 4 тем.

### 2026-03-12

- введён `bot/utils/news_priority.py`;
- RSS и TheNewsAPI переведены на topic-кластеры, co-occurrence и URL/format stoplist;
- добавлен quality/source filter для TheNewsAPI;
- сортировка кандидатов перенесена **до** Python-дедупа;
- дедуп улучшен до event-level, а не только title-level;
- LLM prompt обновлён: `не добивай до N`, `1 событие = 1 карточка`, `operational > rhetoric`, `source priority`;
- антидубль теперь использует **10 последних постов**, а не 5.

### 2026-03-13

- добавлен второй слой отбора до LLM: `prioritize_candidates()` после Python-дедупа;
- scoring теперь учитывает high-impact / medium-impact сигналы и штрафует explainers, galleries, solidarity stories, generic economy-impact и political mood/process материалы;
- `cluster_similar_articles()` теперь лучше схлопывает near-duplicates и выбирает представителя кластера по общему quality/importance, а не только по свежести;
- prompt ужесточён против side-stories, маршей, рыночной реакции и общей риторики без нового operational consequence;
- цель изменений: чтобы в LLM доходили не все формально релевантные статьи, а более узкий пул действительно сильных событий.
