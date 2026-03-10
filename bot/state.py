"""Shared mutable state — singleton-хранилище для scheduler.

Отдельный модуль нужен, чтобы избежать проблемы __main__ vs bot.main:
при запуске через `python -m bot.main` основной файл грузится как __main__,
а admin/router.py импортирует bot.main — Python считает это разными модулями
с разными глобальными переменными. Храним scheduler здесь — одна копия на процесс.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

_scheduler: "AsyncIOScheduler | None" = None


def set_scheduler(s: "AsyncIOScheduler") -> None:
    global _scheduler
    _scheduler = s


def get_scheduler() -> "AsyncIOScheduler | None":
    return _scheduler
