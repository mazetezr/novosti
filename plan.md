# Геополитический Telegram Бот — План реализации

## Статус: MVP готов ✅

Все модули реализованы, первый цикл успешно отработал (RSS → LLM → Telegram).

## Выполнено
- ✅ config.py — загрузка .env
- ✅ cursor/manager.py — SQLite курсор + дедупликация
- ✅ fetcher/rss.py — RSS (6 источников)
- ✅ fetcher/thenewsapi.py — TheNewsAPI (заменил GDELT)
- ✅ fetcher/models.py — NewsItem dataclass
- ✅ summarizer/llm.py — OpenRouter GPT-4o-mini
- ✅ poster/telegram.py — публикация в канал
- ✅ main.py — APScheduler, параллельный fetch
- ✅ Dockerfile + docker-compose.yml
- ✅ requirements.txt

## Что осталось / следующие шаги
- Тестовый запуск с TheNewsAPI (проверить что ключ работает)
- Проверить Docker-сборку (нужен запущенный Docker Desktop)
- Деплой на VPS

