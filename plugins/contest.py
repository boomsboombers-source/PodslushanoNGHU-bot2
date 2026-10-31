# plugins/contest.py
"""
Плагин «Конкурс аватарок ТГК».
Команды:
  !начать_конкурс    — запустить конкурс (админ)
  !завершить_конкурс — завершить приём и опубликовать работы (админ)
  !дополнить_вариант — добавить работу в идущее голосование (админ, фото/документ с подписью)
  !результаты        — опубликовать результаты в канал (админ)
  !конкурс_статус    — краткий статус конкурса (админ)
  !конкурс_сброс     — полный сброс состояния конкурса (админ, с подтверждением)
  !конкурс           — отправить фото на конкурс (все)
"""

import os
import json
import logging
import asyncio

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from config import CHANNEL_ID, LOG_CHAT_ID, ADMIN_IDS, DATA_DIR

# ==============================================================================
# ================= МЕТАДАННЫЕ ДЛЯ МЕНЮ «🔌 ПЛАГИНЫ» ===========================
# ==============================================================================

PLUGIN_INFO = {
    "name": "Конкурс аватарок ТГК",
    "description": "Конкурс на новую аватарку канала с голосованием и сменой голоса",
    "commands": [
        ("!начать_конкурс", "запустить конкурс (админ)"),
        ("!завершить_конкурс", "завершить приём и опубликовать работы (админ)"),
        ("!дополнить_вариант", "добавить работу в идущее голосование (админ)"),
        ("!результаты", "опубликовать результаты в канал (админ)"),
        ("!конкурс_статус", "краткий статус конкурса (админ)"),
        ("!конкурс_сброс", "полный сброс состояния конкурса (админ)"),
        ("!конкурс", "отправить фото на конкурс (все)"),
    ],
}

# ==============================================================================
# ================= РОУТЕР =====================================================
# ==============================================================================

router = Router(name="contest")

# ==============================================================================
# ================= ХРАНИЛИЩЕ ==================================================
# ==============================================================================

CONTEST_DIR = os.path.join(DATA_DIR, "contest")
CONTEST_VOTES_FILE = os.path.join(CONTEST_DIR, "votes.json")
CONTEST_ACTIVE_FILE = os.path.join(CONTEST_DIR, "active.json")
CONTEST_REJECTED_FILE = os.path.join(CONTEST_DIR, "rejected.json")

os.makedirs(CONTEST_DIR, exist_ok=True)

contest_entries = {}      # {user_id_str: {"file_id": str, "number": int, "message_id": int, "type": "photo"|"document"}}
contest_votes = {}        # {voter_id_str: variant_number}
contest_is_active = False
rejected_entries = set()  # {user_id_str, ...}
results_published = False

contest_file_lock = asyncio.Lock()
pending_reset = set()     # {admin_id, ...} — кто нажал «Сброс», ждём подтверждения


def load_contest_data():
    global contest_entries, contest_votes, contest_is_active, rejected_entries, results_published
    try:
        if os.path.exists(CONTEST_VOTES_FILE):
            with open(CONTEST_VOTES_FILE, "r", encoding="utf-8") as f:
                contest_votes = json.load(f)
        if os.path.exists(CONTEST_REJECTED_FILE):
            with open(CONTEST_REJECTED_FILE, "r", encoding="utf-8") as f:
                rejected_entries = set(json.load(f))
        if os.path.exists(CONTEST_ACTIVE_FILE):
            with open(CONTEST_ACTIVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                contest_is_active = data.get("active", False)
                contest_entries = data.get("entries", {})
                results_published = data.get("results_published", False)
    except Exception as e:
        logging.error(f"Ошибка загрузки данных конкурса: {e}")


async def save_contest_data():
    async with contest_file_lock:
        try:
            with open(CONTEST_VOTES_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(contest_votes, f)
            os.replace(CONTEST_VOTES_FILE + ".tmp", CONTEST_VOTES_FILE)

            with open(CONTEST_ACTIVE_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump({
                    "active": contest_is_active,
                    "entries": contest_entries,
                    "results_published": results_published,
                }, f)
            os.replace(CONTEST_ACTIVE_FILE + ".tmp", CONTEST_ACTIVE_FILE)

            with open(CONTEST_REJECTED_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(list(rejected_entries), f)
            os.replace(CONTEST_REJECTED_FILE + ".tmp", CONTEST_REJECTED_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения данных конкурса: {e}")


load_contest_data()


# ==============================================================================
# ================= ВСПОМОГАТЕЛЬНОЕ ============================================
# ==============================================================================

def _max_number() -> int:
    """Максимальный номер среди уже присвоенных вариантов."""
    nums = [e.get("number", 0) for e in contest_entries.values()]
    return max(nums) if nums else 0


def _variant_exists(variant_num: int) -> bool:
    """Существует ли вариант с таким номером среди неотклонённых."""
    for uid, e in contest_entries.items():
        if uid in rejected_entries:
            continue
        if e.get("number") == variant_num:
            return True
    return False


def _vote_kb(variant_num: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗳 Голосовать за вариант {variant_num}", callback_data=f"vote_{variant_num}")],
        [InlineKeyboardButton(text="🔁 Изменить голос", callback_data="change_vote")],
    ])


async def _publish_entry(bot, entry: dict, variant_num: int) -> bool:
    """Публикует работу в канал с кнопками. Возвращает True при успехе."""
    caption = f"🎨 <b>Вариант {variant_num}</b>\nГолосуйте за эту работу!"
    try:
        if entry.get("type") == "document":
            sent = await bot.send_document(
                CHANNEL_ID, document=entry["file_id"],
                caption=caption, reply_markup=_vote_kb(variant_num),
                parse_mode=ParseMode.HTML
            )
        else:
            sent = await bot.send_photo(
                CHANNEL_ID, photo=entry["file_id"],
                caption=caption, reply_markup=_vote_kb(variant_num),
                parse_mode=ParseMode.HTML
            )
        entry["message_id"] = sent.message_id
        return True
    except Exception as e:
        logging.error(f"Ошибка публикации варианта {variant_num}: {e}")
        return False


# ==============================================================================
# ================= КОМАНДЫ АДМИНА =============================================
# ==============================================================================

@router.message(F.text.lower().startswith("!начать_конкурс"), F.from_user.id.in_(ADMIN_IDS))
async def start_contest(message: Message):
    global contest_is_active, contest_entries, contest_votes, rejected_entries, results_published

    if contest_is_active:
        await message.answer("⚠️ Конкурс уже запущен! Сначала завершите текущий (!завершить_конкурс).")
        return

    # Удаляем старые посты вариантов из канала (если есть message_id)
    old_msg_ids = [e.get("message_id") for e in contest_entries.values() if e.get("message_id")]
    for mid in old_msg_ids:
        try:
            await message.bot.delete_message(CHANNEL_ID, mid)
        except Exception:
            pass

    contest_is_active = True
    contest_entries = {}
    contest_votes = {}
    rejected_entries = set()
    results_published = False
    await save_contest_data()

    await message.bot.send_message(
        CHANNEL_ID,
        "🎨 <b>КОНКУРС НА НОВУЮ АВАТАРКУ КАНАЛА!</b>\n\n"
        "Присылайте свои варианты картинок <b>боту в личные сообщения</b>.\n"
        "В подписи к фото обязательно напишите <b>!конкурс</b>.\n\n"
        "📜 <b>Основные правила:</b>\n"
        "1. Аватарка должна быть хотя бы косвенно связана с училищем.\n"
        "2. Фотографии эротического и порнографического характера запрещены.\n\n"
        "🏆 Лучший вариант станет новой аватаркой нашего канала!\n\n"
        "⏳ Прием заявок открыт. Ждем именно твой креатив!",
        parse_mode=ParseMode.HTML
    )
    await message.answer("✅ Конкурс запущен! Участники могут присылать картинки с пометкой !конкурс.")


@router.message(F.text.lower().startswith("!завершить_конкурс"), F.from_user.id.in_(ADMIN_IDS))
async def end_contest(message: Message):
    global contest_is_active, results_published

    if not contest_is_active:
        await message.answer("⚠️ Конкурс не запущен.")
        return
    if not contest_entries:
        await message.answer("⚠️ Никто не прислал ни одной работы. Конкурс отменен.")
        contest_is_active = False
        await save_contest_data()
        return

    contest_is_active = False
    results_published = False
    await save_contest_data()

    await message.answer(f"🏁 Прием заявок завершен! Найдено работ: {len(contest_entries)}. Начинаю публикацию...")

    variant_num = 0
    published_count = 0
    for user_id, entry in contest_entries.items():
        if user_id in rejected_entries:
            continue
        variant_num += 1
        entry["number"] = variant_num
        if await _publish_entry(message.bot, entry, variant_num):
            published_count += 1
        else:
            await message.answer(f"⚠️ Не удалось опубликовать вариант {variant_num}.")
        await asyncio.sleep(1.0)

    await save_contest_data()

    if published_count == 0:
        await message.answer("⚠️ Все работы были отклонены или не опубликованы. Публиковать нечего.")
    else:
        await message.answer(f"✅ Опубликовано {published_count} работ. Теперь участники могут голосовать!")


@router.message((F.photo | F.document) & F.caption.lower().startswith("!дополнить_вариант"), F.from_user.id.in_(ADMIN_IDS))
async def add_late_entry(message: Message):
    """Добавляет работу в идущее голосование (после !завершить_конкурс, до !результаты)."""
    global contest_entries

    if contest_is_active:
        await message.answer("⚠️ Приём ещё идёт. Работа добавится при !завершить_конкурс, отдельная команда не нужна.")
        return
    if results_published:
        await message.answer("⚠️ Результаты уже опубликованы. Добавлять работы поздно.")
        return
    if not contest_entries:
        await message.answer("⚠️ Нет ни одной работы. Сначала запустите и завершите конкурс.")
        return

    # Определяем file_id и тип
    if message.photo:
        file_id = message.photo[-1].file_id
        entry_type = "photo"
    else:
        doc = message.document
        if not doc.mime_type or not doc.mime_type.startswith("image/"):
            await message.answer("⚠️ Нужна картинка (jpg, png и т.д.).")
            return
        file_id = doc.file_id
        entry_type = "document"

    # user_id — из подписи: !дополнить_вариант <id>, иначе id админа
    parts = (message.caption or "").split(maxsplit=2)
    if len(parts) >= 2 and parts[1].isdigit():
        user_id = parts[1]
    else:
        user_id = str(message.from_user.id)

    if user_id in contest_entries:
        await message.answer(f"⚠️ У пользователя {user_id} уже есть работа. Если нужно заменить — сначала отклоните старую.")
        return

    new_number = _max_number() + 1
    contest_entries[user_id] = {
        "file_id": file_id,
        "number": new_number,
        "type": entry_type,
    }

    if await _publish_entry(message.bot, contest_entries[user_id], new_number):
        await save_contest_data()
        await message.answer(f"✅ Вариант {new_number} добавлен в голосование (user_id: {user_id}).")
    else:
        contest_entries.pop(user_id, None)
        await message.answer("❌ Не удалось опубликовать вариант.")


@router.message(F.text.lower().startswith("!результаты"), F.from_user.id.in_(ADMIN_IDS))
async def contest_results(message: Message):
    global results_published

    if contest_is_active:
        await message.answer("⚠️ Конкурс ещё идёт. Сначала !завершить_конкурс.")
        return
    if not contest_votes:
        await message.answer("⚠️ Голосов пока нет.")
        return

    results = {}
    for variant in contest_votes.values():
        results[variant] = results.get(variant, 0) + 1

    sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
    top3 = sorted_results[:3]
    total_votes = sum(results.values())
    total_participants = len([u for u in contest_entries if u not in rejected_entries])

    medals = ["🥇", "🥈", "🥉"]
    lines = ["📊 <b>Результаты конкурса аватарок!</b>\n"]
    for i, (variant, count) in enumerate(top3):
        medal = medals[i] if i < len(medals) else "•"
        lines.append(f"{medal} Вариант {variant} — <b>{count}</b> голосов")
    lines.append(f"\n🗳 Всего голосов: <b>{total_votes}</b>")
    lines.append(f"👥 Участников: <b>{total_participants}</b>")
    lines.append("\n🏆 Победитель станет новой аватаркой канала!")
    channel_text = "\n".join(lines)

    winner_entry = None
    if top3:
        winner_num = top3[0][0]
        for uid, entry in contest_entries.items():
            if uid in rejected_entries:
                continue
            if entry.get("number") == winner_num:
                winner_entry = entry
                break

    was_published = results_published

    try:
        if winner_entry:
            if winner_entry.get("type") == "document":
                await message.bot.send_document(
                    CHANNEL_ID, document=winner_entry["file_id"],
                    caption=channel_text, parse_mode=ParseMode.HTML
                )
            else:
                await message.bot.send_photo(
                    CHANNEL_ID, photo=winner_entry["file_id"],
                    caption=channel_text, parse_mode=ParseMode.HTML
                )
        else:
            await message.bot.send_message(CHANNEL_ID, channel_text, parse_mode=ParseMode.HTML)

        results_published = True
        await save_contest_data()

        suffix = " (повторно)" if was_published else ""
        await message.answer(f"✅ Результаты опубликованы в канал{suffix}.")
    except Exception as e:
        logging.error(f"Ошибка публикации результатов: {e}")
        await message.answer(f"❌ Ошибка публикации: {e}")


@router.message(F.text.lower().startswith("!конкурс_статус"), F.from_user.id.in_(ADMIN_IDS))
async def contest_status(message: Message):
    if contest_is_active:
        state = "🟢 Приём заявок"
    elif results_published:
        state = "🔵 Результаты опубликованы"
    elif contest_entries:
        state = "🟡 Голосование"
    else:
        state = "⚪ Не запущен"

    lines = [
        f"📊 <b>Статус конкурса:</b> {state}",
        f"👥 Работ: <b>{len([u for u in contest_entries if u not in rejected_entries])}</b>",
        f"❌ Отклонено: <b>{len(rejected_entries)}</b>",
        f"🗳 Голосов: <b>{len(contest_votes)}</b>",
    ]
    if contest_entries:
        nums = sorted(e.get("number", 0) for u, e in contest_entries.items() if u not in rejected_entries and e.get("number", 0) > 0)
        if nums:
            lines.append(f"🔢 Варианты: {', '.join(map(str, nums))}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower().startswith("!конкурс_сброс"), F.from_user.id.in_(ADMIN_IDS))
async def contest_reset(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить всё", callback_data="contest_reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="contest_reset_cancel")],
    ])
    await message.answer(
        "⚠️ <b>Полный сброс конкурса</b>\n\n"
        "Будут удалены: работы, голоса, отклонения, флаги.\n"
        "Посты вариантов в канале <b>останутся</b> (удалите вручную, если нужно).\n\n"
        "Продолжить?",
        parse_mode=ParseMode.HTML, reply_markup=kb
    )


@router.callback_query(F.data == "contest_reset_confirm")
async def contest_reset_confirm(callback: CallbackQuery):
    global contest_is_active, contest_entries, contest_votes, rejected_entries, results_published

    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа", show_alert=True)

    contest_is_active = False
    contest_entries = {}
    contest_votes = {}
    rejected_entries = set()
    results_published = False
    await save_contest_data()

    try:
        await callback.message.edit_text("✅ Конкурс полностью сброшен. Можно запускать заново (!начать_конкурс).")
    except TelegramBadRequest:
        pass
    await callback.answer("Готово")


@router.callback_query(F.data == "contest_reset_cancel")
async def contest_reset_cancel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа", show_alert=True)
    try:
        await callback.message.edit_text("❌ Сброс отменён.")
    except TelegramBadRequest:
        pass
    await callback.answer()


# ==============================================================================
# ================= ПРИЁМ РАБОТ ОТ УЧАСТНИКОВ =================================
# ==============================================================================

@router.message(F.text.lower().startswith("!конкурс"), F.chat.type == "private")
async def contest_help(message: Message):
    if not contest_is_active:
        await message.answer("⚠️ Конкурс сейчас не проводится. Следите за анонсами в канале!")
        return
    await message.answer(
        "📸 Чтобы отправить работу на конкурс, пришли <b>фото</b> с подписью <b>!конкурс</b>.\n"
        "Например: выбери фото → в поле подписи напиши <code>!конкурс</code> → отправь.",
        parse_mode=ParseMode.HTML
    )


@router.message(F.photo & F.caption.lower().startswith("!конкурс"), F.chat.type == "private")
async def handle_contest_photo(message: Message):
    global contest_entries

    if not contest_is_active:
        await message.answer("⚠️ Конкурс сейчас не проводится. Следите за анонсами в канале!")
        return

    user_id = str(message.from_user.id)
    if user_id in contest_entries:
        await message.answer("⚠️ Вы уже отправили свою работу! Ждем результатов.")
        return

    contest_entries[user_id] = {
        "file_id": message.photo[-1].file_id,
        "number": 0,
        "type": "photo",
    }
    await save_contest_data()

    await message.answer("✅ Ваша работа принята на конкурс! Удачи! 🍀")

    try:
        log_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отклонить вариант (нарушение правил)", callback_data=f"reject_{user_id}")]
        ])
        await message.bot.send_photo(
            LOG_CHAT_ID,
            photo=message.photo[-1].file_id,
            caption=f"🎨 <b>Новый участник конкурса!</b>\n👤 {message.from_user.full_name}\n🆔 ID: <code>{message.from_user.id}</code>",
            reply_markup=log_kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Не удалось уведомить лог-группу о конкурсе: {e}")


@router.message(F.document & F.caption.lower().startswith("!конкурс"), F.chat.type == "private")
async def handle_contest_document(message: Message):
    global contest_entries

    if not message.document.mime_type or not message.document.mime_type.startswith("image/"):
        await message.answer("⚠️ Пожалуйста, пришлите картинку (jpg, png и т.д.), а не этот файл.")
        return

    if not contest_is_active:
        await message.answer("⚠️ Конкурс сейчас не проводится.")
        return

    user_id = str(message.from_user.id)
    if user_id in contest_entries:
        await message.answer("⚠️ Вы уже отправили свою работу!")
        return

    contest_entries[user_id] = {
        "file_id": message.document.file_id,
        "number": 0,
        "type": "document",
    }
    await save_contest_data()

    await message.answer("✅ Ваша работа (файл) принята на конкурс! Удачи! 🍀")

    try:
        log_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отклонить вариант", callback_data=f"reject_{user_id}")]
        ])
        await message.bot.send_document(
            LOG_CHAT_ID,
            document=message.document.file_id,
            caption=f"🎨 <b>Новый участник конкурса (файл)!</b>\n👤 {message.from_user.full_name}\n🆔 ID: <code>{message.from_user.id}</code>",
            reply_markup=log_kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Ошибка лога (документ): {e}")


# ==============================================================================
# ================= ОТКЛОНЕНИЕ РАБОТЫ =========================================
# ==============================================================================

@router.callback_query(F.data.startswith("reject_"))
async def handle_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа")
        return

    user_id = callback.data.replace("reject_", "")
    if user_id not in contest_entries:
        await callback.answer("⚠️ Этой работы уже нет в базе.", show_alert=True)
        return

    rejected_entries.add(user_id)

    entry = contest_entries.get(user_id, {})
    variant_num = entry.get("number", 0)
    if variant_num:
        to_delete = [k for k, v in contest_votes.items() if v == variant_num]
        for k in to_delete:
            del contest_votes[k]

    await save_contest_data()

    try:
        await callback.message.edit_caption(
            caption=f"❌ <b>РАБОТА ОТКЛОНЕНА</b>\n🆔 ID участника: <code>{user_id}</code>",
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest:
        pass

    await callback.answer("✅ Работа отклонена, голоса за неё аннулированы.")


# ==============================================================================
# ================= ГОЛОСОВАНИЕ И СМЕНА ГОЛОСА =================================
# ==============================================================================

@router.callback_query(F.data.startswith("vote_"))
async def handle_vote(callback: CallbackQuery):
    try:
        variant_num = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Некорректный вариант", show_alert=True)
        return

    if results_published:
        await callback.answer("❌ Голосование завершено, результаты опубликованы.", show_alert=True)
        return
    if not _variant_exists(variant_num):
        await callback.answer("❌ Этот вариант больше не участвует в голосовании.", show_alert=True)
        return

    user_id = str(callback.from_user.id)
    current = contest_votes.get(user_id)

    if current == variant_num:
        await callback.answer(f"ℹ️ Вы уже голосуете за вариант {variant_num}.", show_alert=True)
        return

    if current is not None:
        # Смена голоса через повторное нажатие — подтверждение не нужно, просто меняем
        contest_votes[user_id] = variant_num
        await save_contest_data()
        await callback.answer(f"🔁 Голос изменён: вариант {current} → {variant_num}.", show_alert=True)
        return

    contest_votes[user_id] = variant_num
    await save_contest_data()
    await callback.answer(f"✅ Ваш голос за вариант {variant_num} принят!", show_alert=True)


@router.callback_query(F.data == "change_vote")
async def handle_change_vote(callback: CallbackQuery):
    if results_published:
        return await callback.answer("❌ Голосование завершено.", show_alert=True)
    if not contest_entries:
        return await callback.answer("❌ Нет активного голосования.", show_alert=True)

    user_id = str(callback.from_user.id)
    current = contest_votes.get(user_id)
    nums = sorted({e.get("number", 0) for u, e in contest_entries.items() if u not in rejected_entries and e.get("number", 0) > 0})

    if not nums:
        return await callback.answer("❌ Нет доступных вариантов.", show_alert=True)

    rows = []
    for n in nums:
        mark = " ✅" if current == n else ""
        rows.append([InlineKeyboardButton(text=f"Вариант {n}{mark}", callback_data=f"vote_{n}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="change_vote_back")])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    text = "🔁 <b>Смена голоса</b>\n\nТекущий голос: " + (f"вариант {current}" if current else "нет") + "\nВыбери новый вариант:"
    try:
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "change_vote_back")
async def handle_change_vote_back(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
