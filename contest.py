import os
import json
import logging
import asyncio
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest


# Создаем роутер
contest_router = Router()

# Настройки (те же ID, что и в bot.py)
CHANNEL_ID = -1002304148771
LOG_CHAT_ID = -1004306176378
ADMIN_IDS = [1088467220, 1690346204]

# Файлы для конкурса (ВСЁ В ПАПКЕ data/contest)
CONTEST_DIR = "data/contest"
CONTEST_VOTES_FILE = os.path.join(CONTEST_DIR, "votes.json")
CONTEST_ACTIVE_FILE = os.path.join(CONTEST_DIR, "active.json")
CONTEST_REJECTED_FILE = os.path.join(CONTEST_DIR, "rejected.json")

if not os.path.exists(CONTEST_DIR):
    os.makedirs(CONTEST_DIR)

# --- ХРАНИЛИЩА ---
contest_entries = {}    # {user_id_str: file_id}
contest_votes = {}      # {user_id_str: variant_number}
contest_is_active = False
rejected_entries = set() # {"user_id_str", ...}

# Блокировка для безопасной записи в JSON (защита от Race Condition)
contest_file_lock = asyncio.Lock()

# --- ЗАГРУЗКА И СОХРАНЕНИЕ ---
def load_contest_data():
    global contest_entries, contest_votes, contest_is_active, rejected_entries
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
    except Exception as e:
        logging.error(f"Ошибка загрузки данных конкурса: {e}")

async def save_contest_data():
    """Атомарно сохраняет данные с использованием блокировки."""
    async with contest_file_lock:
        try:
            # Сохраняем голоса
            with open(CONTEST_VOTES_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(contest_votes, f)
            os.replace(CONTEST_VOTES_FILE + ".tmp", CONTEST_VOTES_FILE)
            
            # Сохраняем активность и работы
            with open(CONTEST_ACTIVE_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"active": contest_is_active, "entries": contest_entries}, f)
            os.replace(CONTEST_ACTIVE_FILE + ".tmp", CONTEST_ACTIVE_FILE)
            
            # Сохраняем отклоненные
            with open(CONTEST_REJECTED_FILE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(list(rejected_entries), f)
            os.replace(CONTEST_REJECTED_FILE + ".tmp", CONTEST_REJECTED_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения данных конкурса: {e}")

# --- КОМАНДЫ АДМИНА ---

@contest_router.message(Command("start_contest", "начать_конкурс"), F.from_user.id.in_(ADMIN_IDS))
@contest_router.message(F.text.lower().in_(["!start_contest", "!начать_конкурс"]), F.from_user.id.in_(ADMIN_IDS))
async def start_contest(message: Message):
    global contest_is_active, contest_entries, contest_votes, rejected_entries
    
    if contest_is_active:
        await message.answer("⚠️ Конкурс уже запущен! Сначала завершите текущий (!завершить_конкурс).")
        return
    
    contest_is_active = True
    contest_entries = {}
    contest_votes = {}
    rejected_entries = set()
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

@contest_router.message(Command("end_contest", "завершить_конкурс"), F.from_user.id.in_(ADMIN_IDS))
@contest_router.message(F.text.lower().in_(["!end_contest", "!завершить_конкурс"]), F.from_user.id.in_(ADMIN_IDS))
async def end_contest(message: Message):
    global contest_is_active
    
    if not contest_is_active:
        await message.answer("⚠️ Конкурс не запущен.")
        return
    if not contest_entries:
        await message.answer("⚠️ Никто не прислал ни одной работы. Конкурс отменен.")
        contest_is_active = False
        await save_contest_data()
        return
    
    contest_is_active = False
    await save_contest_data()
    
    await message.answer(f"🏁 Прием заявок завершен! Найдено работ: {len(contest_entries)}. Начинаю публикацию...")
    
    variant_num = 0
    for user_id, file_id in contest_entries.items():
        if user_id in rejected_entries:
            continue
        
        variant_num += 1
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗳 Голосовать за вариант {variant_num}", callback_data=f"vote_{variant_num}")]
        ])
        try:
            await message.bot.send_photo(
                CHANNEL_ID,
                photo=file_id,
                caption=f"🎨 <b>Вариант {variant_num}</b>\nГолосуйте за эту работу!",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            # Небольшая задержка, чтобы не словить флуд-контроль
            await asyncio.sleep(1.0)
        except Exception as e:
            logging.error(f"Ошибка публикации работы {variant_num}: {e}")
            await message.answer(f"⚠️ Не удалось опубликовать вариант {variant_num}: {e}")
    
    if variant_num == 0:
        await message.answer("⚠️ Все работы были отклонены. Публиковать нечего.")
    else:
        await message.answer(f"✅ Опубликовано {variant_num} работ. Теперь участники могут голосовать!")

@contest_router.message(Command("contest_results", "результаты_конкурса"), F.from_user.id.in_(ADMIN_IDS))
@contest_router.message(F.text.lower().in_(["!contest_results", "!результаты_конкурса"]), F.from_user.id.in_(ADMIN_IDS))
async def contest_results(message: Message):
    if not contest_votes:
        await message.answer("⚠️ Голосов пока нет.")
        return
    
    results = {}
    for variant in contest_votes.values():
        results[variant] = results.get(variant, 0) + 1
    
    text = "📊 <b>Результаты конкурса:</b>\n\n"
    for variant, count in sorted(results.items(), key=lambda x: x[1], reverse=True):
        text += f"Вариант {variant}: <b>{count}</b> голосов\n"
    
    await message.answer(text, parse_mode=ParseMode.HTML)

# --- ПРИЕМ РАБОТ ОТ УЧАСТНИКОВ ---

@contest_router.message(F.photo & F.caption.startswith("!конкурс"))
async def handle_contest_photo(message: Message):
    global contest_entries
    
    if not contest_is_active:
        await message.answer("⚠️ Конкурс сейчас не проводится. Следите за анонсами в канале!")
        return
    
    user_id = str(message.from_user.id) # Приводим к строке
    
    if user_id in contest_entries:
        await message.answer("⚠️ Вы уже отправили свою работу! Ждем результатов.")
        return
    
    contest_entries[user_id] = message.photo[-1].file_id
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

# Обработка картинок, отправленных как файл (документ)
@contest_router.message(F.document & F.caption.startswith("!конкурс"))
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
    
    # Используем file_id документа (он тоже подходит для отправки как фото)
    contest_entries[user_id] = message.document.file_id
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

# --- ОТКЛОНЕНИЕ РАБОТЫ ---

@contest_router.callback_query(F.data.startswith("reject_"))
async def handle_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Нет доступа")
        return
    
    user_id = callback.data.replace("reject_", "")
    
    if user_id not in contest_entries:
        await callback.answer("⚠️ Этой работы уже нет в базе.", show_alert=True)
        return

    rejected_entries.add(user_id)
    await save_contest_data()
    
    # Удаляем голоса, поданные за этого участника (если они были)
    if user_id in contest_entries:
        # Находим номер варианта, под которым была эта работа
        # (так как мы публикуем по порядку, номер = индекс в списке + 1)
        sorted_keys = list(contest_entries.keys())
        variant_num = sorted_keys.index(user_id) + 1
        
        # Удаляем все голоса за этот номер
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
        # Игнорируем, если сообщение уже удалено
        pass
    
    await callback.answer("✅ Работа отклонена, голоса за неё аннулированы.")

# --- ГОЛОСОВАНИЕ ---

@contest_router.callback_query(F.data.startswith("vote_"))
async def handle_vote(callback: CallbackQuery):
    variant_num = int(callback.data.split("_")[1])
    user_id = str(callback.from_user.id) # Приводим к строке
    
    if user_id in contest_votes:
        await callback.answer("❌ Вы уже проголосовали! Один голос на человека.", show_alert=True)
        return
    
    contest_votes[user_id] = variant_num
    await save_contest_data()
    
    await callback.answer(f"✅ Ваш голос за вариант {variant_num} принят!", show_alert=True)

# Функция для подключения при старте
def setup_contest(bot_instance):
    load_contest_data()