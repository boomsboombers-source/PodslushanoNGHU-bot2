# plugins/contest.py
"""
Плагин «Конкурс аватарок ТГК».
Команды:
  !начать_конкурс    — запустить конкурс (админ)
  !завершить_конкурс — завершить приём и опубликовать работы (админ)
  !результаты        — опубликовать результаты в канал (админ)
  !конкурс           — отправить фото на конкурс (все)
"""

import os
import json
import logging
import asyncio
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from config import CHANNEL_ID, LOG_CHAT_ID, ADMIN_IDS

# ==============================================================================
# ================= МЕТАДАННЫЕ ДЛЯ МЕНЮ «🔌 ПЛАГИНЫ» ===========================
# ==============================================================================

PLUGIN_INFO = {
    "name": "Конкурс аватарок ТГК",
    "description": "Конкурс на новую аватарку канала с голосованием",
    "commands": [
        ("!начать_конкурс", "запустить конкурс (админ)"),
        ("!завершить_конкурс", "завершить приём и опубликовать работы (админ)"),
        ("!результаты", "опубликовать результаты в канал (админ)"),
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

CONTEST_DIR = "data/contest"
CONTEST_VOTES_FILE = os.path.join(CONTEST_DIR, "votes.json")
CONTEST_ACTIVE_FILE = os.path.join(CONTEST_DIR, "active.json")
CONTEST_REJECTED_FILE = os.path.join(CONTEST_DIR, "rejected.json")

if not os.path.exists(CONTEST_DIR):
    os.makedirs(CONTEST_DIR)

contest_entries = {}      # {user_id_str: {"file_id": str, "number": int}}
contest_votes = {}        # {voter_id_str: variant_number}
contest_is_active = False
rejected_entries = set()  # {user_id_str, ...}
results_published = False

contest_file_lock = asyncio.Lock()


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
# ================= КОМАНДЫ АДМИНА =============================================
# ==============================================================================

@router.message(F.text.lower().startswith("!начать_конкурс"), F.from_user.id.in_(ADMIN_IDS))
async def start_contest(message: Message):
    global contest_is_active, contest_entries, contest_votes, rejected_entries, results_published

    if contest_is_active:
        await message.answer("⚠️ Конкурс уже запущен! Сначала завершите текущий (!завершить_конкурс).")
        return

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
        published_count += 1

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗳 Голосовать за вариант {variant_num}", callback_data=f"vote_{variant_num}")]
        ])
        try:
            await message.bot.send_photo(
                CHANNEL_ID,
                photo=entry["file_id"],
                caption=f"🎨 <b>Вариант {variant_num}</b>\nГолосуйте за эту работу!",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(1.0)
        except Exception as e:
            logging.error(f"Ошибка публикации работы {variant_num}: {e}")
            await message.answer(f"⚠️ Не удалось опубликовать вариант {variant_num}: {e}")

    await save_contest_data()

    if published_count == 0:
        await message.answer("⚠️ Все работы были отклонены. Публиковать нечего.")
    else:
        await message.answer(f"✅ Опубликовано {published_count} работ. Теперь участники могут голосовать!")


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
    total_participants = len(contest_entries)

    medals = ["🥇", "🥈", "🥉"]
    lines = ["📊 <b>Результаты конкурса аватарок!</b>\n"]
    for i, (variant, count) in enumerate(top3):
        medal = medals[i] if i < len(medals) else "•"
        lines.append(f"{medal} Вариант {variant} — <b>{count}</b> голосов")
    lines.append(f"\n🗳 Всего голосов: <b>{total_votes}</b>")
    lines.append(f"👥 Участников: <b>{total_participants}</b>")
    lines.append("\n🏆 Победитель станет новой аватаркой канала!")
    channel_text = "\n".join(lines)

    winner_file_id = None
    if top3:
        winner_num = top3[0][0]
        for user_id, entry in contest_entries.items():
            if entry.get("number") == winner_num:
                winner_file_id = entry.get("file_id")
                break

    was_published = results_published

    try:
        if winner_file_id:
            await message.bot.send_photo(
                CHANNEL_ID, photo=winner_file_id,
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


@router.message(F.photo & F.caption.startswith("!конкурс"), F.chat.type == "private")
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


@router.message(F.document & F.caption.startswith("!конкурс"), F.chat.type == "private")
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
    }
    await save_contest_data()

    await message.answer("✅ Ваша работа (файл) принята на конкурс! Удачи! 🍀")

    try:
        log_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отклонить вариант", callback_data=f"reject_{user_id}")]
        ])
        await message.bot.send_photo(
            LOG_CHAT_ID,
            photo=message.document.file_id,
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
# ================= ГОЛОСОВАНИЕ ================================================
# ==============================================================================

@router.callback_query(F.data.startswith("vote_"))
async def handle_vote(callback: CallbackQuery):
    try:
        variant_num = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Некорректный вариант", show_alert=True)
        return

    user_id = str(callback.from_user.id)

    if user_id in contest_votes:
        await callback.answer("❌ Вы уже проголосовали! Один голос на человека.", show_alert=True)
        return

    contest_votes[user_id] = variant_num
    await save_contest_data()

    await callback.answer(f"✅ Ваш голос за вариант {variant_num} принят!", show_alert=True)