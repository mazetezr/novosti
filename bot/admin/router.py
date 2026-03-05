import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

from bot.config import ADMIN_IDS
from bot.cursor.manager import (
    get_topics, add_topic, remove_topic,
    get_stopwords, add_stopword, remove_stopword,
    get_setting, set_setting, reset_cursor,
)

logger = logging.getLogger(__name__)
router = Router()


class AdminFSM(StatesGroup):
    waiting_for_keyword = State()
    waiting_for_interval = State()
    waiting_for_reset_hours = State()
    waiting_for_stopword = State()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список тем", callback_data="topics_list")],
        [InlineKeyboardButton(text="➕ Добавить тему", callback_data="topics_add")],
        [InlineKeyboardButton(text="🗑 Удалить тему", callback_data="topics_del_menu")],
        [InlineKeyboardButton(text="🚫 Стоп-слова", callback_data="stop_menu")],
        [InlineKeyboardButton(text="🕐 Частота постов", callback_data="interval_menu")],
        [InlineKeyboardButton(text="🔄 Сбросить курсор", callback_data="reset_cursor")],
    ])


# --- /admin command ---

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "⚙️ <b>Админ-панель</b>\nУправление темами и настройками",
        reply_markup=_admin_kb(),
        parse_mode="HTML",
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


# --- /post — instant cycle ---

@router.message(Command("post"))
async def cmd_post(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer("⏳ Запускаю сводку...")
    from bot.main import run_cycle
    await run_cycle()
    await message.answer("✅ Цикл завершён.")


# --- Reset cursor ---

@router.callback_query(F.data == "reset_cursor")
async def cb_reset_cursor(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3ч", callback_data="reset_h:3"),
            InlineKeyboardButton(text="6ч", callback_data="reset_h:6"),
            InlineKeyboardButton(text="12ч", callback_data="reset_h:12"),
            InlineKeyboardButton(text="24ч", callback_data="reset_h:24"),
        ],
        [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="reset_h_custom")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")],
    ])
    await callback.message.edit_text(
        "🔄 <b>Сбросить курсор</b>\n\n"
        "За сколько часов назад забрать новости?",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reset_h:"))
async def cb_reset_hours(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    hours = int(callback.data.split(":")[1])
    await reset_cursor(hours)
    await callback.answer(f"Курсор сброшен на {hours}ч назад", show_alert=True)
    await callback.message.edit_text(
        f"✅ Курсор сброшен — следующий цикл заберёт новости за <b>{hours}ч</b>.\n"
        "Используйте /post для немедленной сводки.",
        reply_markup=_admin_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "reset_h_custom")
async def cb_reset_custom(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.waiting_for_reset_hours)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")],
    ])
    await callback.message.edit_text(
        "Введите количество часов (от 1 до 72):",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminFSM.waiting_for_reset_hours)
async def process_reset_hours(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 72):
        await message.answer(
            "⚠️ Введите целое число от 1 до 72.",
            reply_markup=_admin_kb(),
        )
        await state.clear()
        return
    hours = int(text)
    await reset_cursor(hours)
    await state.clear()
    await message.answer(
        f"✅ Курсор сброшен — следующий цикл заберёт новости за <b>{hours}ч</b>.\n"
        "Используйте /post для немедленной сводки.",
        reply_markup=_admin_kb(),
        parse_mode="HTML",
    )


# --- Interval control ---

@router.callback_query(F.data == "interval_menu")
async def cb_interval_menu(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    current = await get_setting("interval_hours", "3")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1ч", callback_data="set_iv:1"),
            InlineKeyboardButton(text="2ч", callback_data="set_iv:2"),
            InlineKeyboardButton(text="3ч", callback_data="set_iv:3"),
        ],
        [
            InlineKeyboardButton(text="4ч", callback_data="set_iv:4"),
            InlineKeyboardButton(text="6ч", callback_data="set_iv:6"),
            InlineKeyboardButton(text="12ч", callback_data="set_iv:12"),
        ],
        [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="set_iv_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
    ])
    await callback.message.edit_text(
        f"🕐 <b>Частота постов</b>\nСейчас: каждые <b>{current}ч</b>\n\nВыберите или введите:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_iv:"))
async def cb_set_interval(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    hours = int(callback.data.split(":")[1])
    await _apply_interval(hours)
    await callback.answer(f"Установлено: каждые {hours}ч", show_alert=True)
    # Return to admin menu
    await callback.message.edit_text(
        f"✅ Частота обновлена: каждые <b>{hours}ч</b>",
        reply_markup=_admin_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "set_iv_custom")
async def cb_set_interval_custom(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.waiting_for_interval)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")],
    ])
    await callback.message.edit_text(
        "Введите частоту в часах (целое число от 1 до 24):",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminFSM.waiting_for_interval)
async def process_interval(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 24):
        await message.answer(
            "⚠️ Введите целое число от 1 до 24.",
            reply_markup=_admin_kb(),
        )
        await state.clear()
        return
    hours = int(text)
    await _apply_interval(hours)
    await state.clear()
    await message.answer(
        f"✅ Частота обновлена: каждые <b>{hours}ч</b>",
        reply_markup=_admin_kb(),
        parse_mode="HTML",
    )


async def _apply_interval(hours: int):
    """Save interval to DB and reschedule the job."""
    await set_setting("interval_hours", str(hours))
    from bot.main import get_scheduler
    from apscheduler.triggers.interval import IntervalTrigger
    sched = get_scheduler()
    if sched:
        try:
            sched.reschedule_job("news_cycle", trigger=IntervalTrigger(hours=hours))
            logger.info("Rescheduled news_cycle to every %d hours", hours)
        except Exception as e:
            logger.error("Failed to reschedule news_cycle: %s", e)
    else:
        logger.warning("Scheduler not running, interval saved to DB but not applied in memory")


# --- List topics ---

@router.callback_query(F.data == "topics_list")
async def cb_topics_list(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    topics = await get_topics()
    if not topics:
        text = "Список тем пуст."
    else:
        text = "<b>📋 Текущие темы:</b>\n\n" + "\n".join(f"• <code>{t}</code>" for t in topics)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- Add topic ---

@router.callback_query(F.data == "topics_add")
async def cb_topics_add(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.waiting_for_keyword)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")],
    ])
    await callback.message.edit_text(
        "Введите ключевые слова через запятую:\n"
        "Например: <code>NATO, drone, ceasefire</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminFSM.waiting_for_keyword)
async def process_add_keyword(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    keywords = [kw.strip() for kw in message.text.split(",") if kw.strip()]
    added = []
    for kw in keywords:
        if await add_topic(kw):
            added.append(kw)
    await state.clear()
    if added:
        text = "✅ Добавлено: " + ", ".join(f"<code>{k}</code>" for k in added)
    else:
        text = "⚠️ Ничего не добавлено (возможно, уже существуют)."
    await message.answer(text, reply_markup=_admin_kb(), parse_mode="HTML")


# --- Delete topic ---

async def _delete_menu_kb() -> InlineKeyboardMarkup:
    topics = await get_topics()
    buttons = []
    row = []
    for t in topics:
        row.append(InlineKeyboardButton(text=f"❌ {t}", callback_data=f"del:{t}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "topics_del_menu")
async def cb_topics_del_menu(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    topics = await get_topics()
    if not topics:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
        ])
        await callback.message.edit_text("Список тем пуст.", reply_markup=kb)
        await callback.answer()
        return
    await callback.message.edit_text(
        "🗑 Нажмите на тему для удаления:",
        reply_markup=await _delete_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def cb_del_topic(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    keyword = callback.data.split(":", 1)[1]
    removed = await remove_topic(keyword)
    if removed:
        await callback.answer(f"Удалено: {keyword}", show_alert=True)
    else:
        await callback.answer("Не найдено", show_alert=True)
    # Refresh delete menu
    topics = await get_topics()
    if not topics:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
        ])
        await callback.message.edit_text("Список тем пуст.", reply_markup=kb)
        return
    await callback.message.edit_text(
        "🗑 Нажмите на тему для удаления:",
        reply_markup=await _delete_menu_kb(),
    )


# --- Stopwords ---

@router.callback_query(F.data == "stop_menu")
async def cb_stop_menu(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    words = await get_stopwords()
    if not words:
        text = "🚫 <b>Стоп-слова</b>\n\nСписок пуст."
    else:
        text = "🚫 <b>Стоп-слова</b> (блокируют нерелевантные новости):\n\n" + "\n".join(
            f"• <code>{w}</code>" for w in words
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="stop_add")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="stop_del_menu")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "stop_add")
async def cb_stop_add(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.waiting_for_stopword)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="stop_menu")],
    ])
    await callback.message.edit_text(
        "Введите стоп-слова через запятую:\n"
        "Например: <code>poker, diet, tiktok</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminFSM.waiting_for_stopword)
async def process_add_stopword(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    words = [w.strip() for w in message.text.split(",") if w.strip()]
    added = []
    for w in words:
        if await add_stopword(w):
            added.append(w)
    await state.clear()
    if added:
        text = "✅ Добавлено: " + ", ".join(f"<code>{w}</code>" for w in added)
    else:
        text = "⚠️ Ничего не добавлено (возможно, уже существуют)."
    await message.answer(text, reply_markup=_admin_kb(), parse_mode="HTML")


async def _stop_del_kb() -> InlineKeyboardMarkup:
    words = await get_stopwords()
    buttons = []
    row = []
    for w in words:
        row.append(InlineKeyboardButton(text=f"❌ {w}", callback_data=f"sdel:{w}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="stop_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "stop_del_menu")
async def cb_stop_del_menu(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    words = await get_stopwords()
    if not words:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="stop_menu")],
        ])
        await callback.message.edit_text("Список стоп-слов пуст.", reply_markup=kb)
        await callback.answer()
        return
    await callback.message.edit_text(
        "🗑 Нажмите на стоп-слово для удаления:",
        reply_markup=await _stop_del_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sdel:"))
async def cb_del_stopword(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    word = callback.data.split(":", 1)[1]
    removed = await remove_stopword(word)
    if removed:
        await callback.answer(f"Удалено: {word}", show_alert=True)
    else:
        await callback.answer("Не найдено", show_alert=True)
    words = await get_stopwords()
    if not words:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="stop_menu")],
        ])
        await callback.message.edit_text("Список стоп-слов пуст.", reply_markup=kb)
        return
    await callback.message.edit_text(
        "🗑 Нажмите на стоп-слово для удаления:",
        reply_markup=await _stop_del_kb(),
    )


# --- Back to main menu ---

@router.callback_query(F.data == "admin_back")
async def cb_admin_back(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\nУправление темами и настройками",
        reply_markup=_admin_kb(),
        parse_mode="HTML",
    )
    await callback.answer()
