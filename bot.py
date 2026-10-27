import asyncio
import logging
import os
import json
import html
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode, ContentType
from aiogram.exceptions import TelegramBadRequest

# ==============================================================================
# ================= НАСТРОЙКИ БОТА =============================================
# ==============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = -1002304148771
LOG_CHAT_ID = -1004306176378
ADMIN_IDS = [1088467220, 1690346204]

WELCOME_IMAGE = "pictures/Podslushano.png"

LOG_FILE = "data/messages.txt"
USERS_FILE = "data/users.txt"
SCHEDULE_FILE = "data/schedule.txt"
USERNAMES_FILE = "data/usernames.txt"
REPLIES_FILE = "data/replies.json"
MUTED_FILE = "data/muted.json"
DELAYED_FILE = "data/delayed.json"

# ==============================================================================
# ================= ИНИЦИАЛИЗАЦИЯ ==============================================
# ==============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not os.path.exists("data"):
    os.makedirs("data")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

active_replies = {}
cached_users = set()
muted_users = {}
delayed_posts = []

replies_dirty = False
user_file_lock = asyncio.Lock()
usernames_file_lock = asyncio.Lock()

# ==============================================================================
# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================================
# ==============================================================================

def esc(s) -> str:
    return html.escape(s or "", quote=False)

def load_users_cache():
    global cached_users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                cached_users = set(f.read().splitlines())
        except Exception as e:
            logging.error(f"Ошибка загрузки users.txt: {e}")
            cached_users = set()

async def save_user(user_id: int):
    global cached_users
    user_id_str = str(user_id)
    async with user_file_lock:
        if user_id_str in cached_users:
            return
        cached_users.add(user_id_str)
        try:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(user_id_str + "\n")
        except Exception as e:
            logging.error(f"Ошибка сохранения пользователя {user_id}: {e}")
            cached_users.discard(user_id_str)

def get_all_users() -> list[str]:
    return list(cached_users)

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📅 Расписание репетиций")]],
        resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Напиши сообщение для канала..."
    )

async def save_username(username, user_id: int):
    if not username: return
    username = username.lower().lstrip('@')
    async with usernames_file_lock:
        temp_file = USERNAMES_FILE + ".tmp"
        lines = []
        if os.path.exists(USERNAMES_FILE):
            with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(f"{username}:"):
                lines[i] = f"{username}:{user_id}"
                updated = True
                break
        if not updated:
            lines.append(f"{username}:{user_id}")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(temp_file, USERNAMES_FILE)

def get_id_by_username(username: str):
    username = username.lower().lstrip('@')
    if not os.path.exists(USERNAMES_FILE): return None
    with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(f"{username}:"):
                try:
                    return int(line.split(":")[1])
                except (IndexError, ValueError):
                    return None
    return None

def get_username_by_id(user_id: int) -> str:
    if not os.path.exists(USERNAMES_FILE): return "нет username"
    with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().endswith(f":{user_id}"):
                return f"@{line.split(':')[0]}"
    return "нет username"

def load_replies():
    global active_replies
    if os.path.exists(REPLIES_FILE):
        try:
            with open(REPLIES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                active_replies = {int(k): v for k, v in data.items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки replies.json: {e}")

def mark_replies_dirty():
    global replies_dirty
    replies_dirty = True

async def auto_save_replies():
    global replies_dirty
    while True:
        if replies_dirty:
            try:
                temp_file = REPLIES_FILE + ".tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(active_replies, f)
                os.replace(temp_file, REPLIES_FILE)
            except Exception as e:
                logging.error(f"Ошибка сохранения replies.json: {e}")
            finally:
                replies_dirty = False
        await asyncio.sleep(5)

def load_muted():
    global muted_users
    if os.path.exists(MUTED_FILE):
        try:
            with open(MUTED_FILE, "r", encoding="utf-8") as f:
                muted_users = {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки muted.json: {e}")
            muted_users = {}

def save_muted():
    temp_file = MUTED_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(muted_users, f)
    os.replace(temp_file, MUTED_FILE)

def check_mute(user_id: int):
    if user_id in muted_users:
        remaining = muted_users[user_id] - datetime.now().timestamp()
        if remaining > 0:
            return int(remaining)
        else:
            del muted_users[user_id]
            save_muted()
    return None

def serialize_message(message: Message) -> dict:
    data = {
        "type": message.content_type,
        "text": message.text or message.caption or ""
    }
    if message.photo: data["file_id"] = message.photo[-1].file_id
    elif message.video: data["file_id"] = message.video.file_id
    elif message.document: data["file_id"] = message.document.file_id
    elif message.audio: data["file_id"] = message.audio.file_id
    elif message.voice: data["file_id"] = message.voice.file_id
    elif message.video_note: data["file_id"] = message.video_note.file_id
    elif message.sticker: data["file_id"] = message.sticker.file_id
    elif message.contact:
        data["contact"] = {
            "phone_number": message.contact.phone_number,
            "first_name": message.contact.first_name,
            "last_name": message.contact.last_name,
        }
        data["text"] = ""
    elif message.location:
        data["location"] = {
            "latitude": message.location.latitude,
            "longitude": message.location.longitude,
        }
        data["text"] = ""
    return data

async def send_delayed_post(post: dict):
    try:
        ptype = post.get("type")
        text = post.get("text", "")
        file_id = post.get("file_id")

        if ptype == "text":
            await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        elif ptype == "photo":
            await bot.send_photo(CHANNEL_ID, photo=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "video":
            await bot.send_video(CHANNEL_ID, video=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "document":
            await bot.send_document(CHANNEL_ID, document=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "audio":
            await bot.send_audio(CHANNEL_ID, audio=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "voice":
            await bot.send_voice(CHANNEL_ID, voice=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "video_note":
            await bot.send_video_note(CHANNEL_ID, video_note=file_id)
        elif ptype == "sticker":
            await bot.send_sticker(CHANNEL_ID, sticker=file_id)
        elif ptype == "contact":
            c = post.get("contact", {})
            await bot.send_contact(CHANNEL_ID, phone_number=c.get("phone_number", ""), first_name=c.get("first_name", ""), last_name=c.get("last_name"))
            if text: await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        elif ptype == "location":
            loc = post.get("location", {})
            await bot.send_location(CHANNEL_ID, latitude=loc.get("latitude", 0), longitude=loc.get("longitude", 0))
            if text: await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(CHANNEL_ID, text)
    except Exception as e:
        logging.error(f"Ошибка отправки отложенного поста: {e}")

def load_delayed():
    global delayed_posts
    if not os.path.exists(DELAYED_FILE): return
    try:
        with open(DELAYED_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("delayed.json: ожидался список")
        valid = []
        for i, post in enumerate(raw):
            if isinstance(post, dict) and "time" in post and "type" in post:
                valid.append(post)
        delayed_posts = valid
    except Exception as e:
            logging.error(f"Ошибка загрузки delayed.json: {e}")
            os.replace(DELAYED_FILE, DELAYED_FILE + ".bak")
            delayed_posts = []

async def _send_media_with_caption(target_id: int, message: Message, caption: str = "", parse_mode=None, reply_to_message_id: int = None) -> Message:
    if message.photo: return await bot.send_photo(target_id, photo=message.photo[-1].file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.video: return await bot.send_video(target_id, video=message.video.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.document: return await bot.send_document(target_id, document=message.document.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.audio: return await bot.send_audio(target_id, audio=message.audio.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.voice: return await bot.send_voice(target_id, voice=message.voice.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.video_note: return await bot.send_video_note(target_id, video_note=message.video_note.file_id, reply_to_message_id=reply_to_message_id)
    elif message.sticker: return await bot.send_sticker(target_id, sticker=message.sticker.file_id, reply_to_message_id=reply_to_message_id)
    elif message.contact:
        sent = await bot.send_contact(target_id, phone_number=message.contact.phone_number, first_name=message.contact.first_name, last_name=message.contact.last_name, reply_to_message_id=reply_to_message_id)
        if caption: await bot.send_message(target_id, caption, parse_mode=parse_mode)
        return sent
    elif message.location:
        sent = await bot.send_location(target_id, latitude=message.location.latitude, longitude=message.location.longitude, reply_to_message_id=reply_to_message_id)
        if caption: await bot.send_message(target_id, caption, parse_mode=parse_mode)
        return sent
    else: return await bot.send_message(target_id, caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)

# ==============================================================================
# ================= АДМИН-ПАНЕЛЬ ===============================================
# ==============================================================================

@dp.message(Command("admin", "админ"))
@dp.message(F.text.lower().in_(["!admin", "!админ"]))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🧹 Очистить ответы", callback_data="admin_clear_replies")],
        [InlineKeyboardButton(text="📚 Команды", callback_data="admin_settings")]
    ])
    await message.answer("🛠 <b>Админ-панель</b>\nВыбери действие:", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("admin_"))
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    action = callback.data.replace("admin_", "")
    
    if action == "stats":
        muted_list = ""
        if muted_users:
            muted_list = "\n\n🔇 <b>Замученные:</b>\n"
            for uid, until_ts in muted_users.items():
                username = get_username_by_id(uid)
                remaining = int(until_ts - datetime.now().timestamp())
                if remaining > 0:
                    minutes = remaining // 60
                    muted_list += f"• {username} (<code>{uid}</code>) — {minutes} мин.\n"
                else:
                    muted_list += f"• {username} (<code>{uid}</code>) — истек\n"
        else:
            muted_list = "\n\n🔇 <b>Замученных нет.</b>"

        await callback.message.answer(
            f"📊 <b>Статистика:</b>\n"
            f"👥 Пользователей: <b>{len(cached_users)}</b>\n"
            f"💬 В ожидании: <b>{len(active_replies)}</b>"
            f"{muted_list}",
            parse_mode=ParseMode.HTML
        )
        
    elif action == "clear_replies":
        active_replies.clear()
        mark_replies_dirty()
        await callback.message.answer("✅ Все ожидания ответов очищены.")
        
    elif action == "settings":
        await callback.message.answer(
            "📚 <b>Полная шпаргалка по командам</b>\n\n"
            "📅 <b>Расписание</b>\n"
            "• <code>!расписание</code> — <i>прикрепи фото расписания, в подписи напиши эту команду.</i>\n\n"
            "📢 <b>Рассылка (всем пользователям)</b>\n"
            "• <code>!рассылка [текст]</code> — разошлет текст всем, кто запускал бота.\n"
            "• <code>!рассылка</code> + фото/видео — разошлет медиа с подписью.\n"
            "<i>Пример:</i> <code>!рассылка Привет! Завтра репетиция в 15:00.</code>\n\n"
            "✉️ <b>Личное сообщение</b>\n"
            "• <code>!лс [ID|@username] [текст]</code> — отправит сообщение конкретному человеку.\n"
            "<i>Пример:</i> <code>!лс @rudenkov Привет!</code>\n\n"
            "⏰ <b>Отложенный пост</b>\n"
            "• <code>!отложка [ЧЧ:ММ] [текст]</code> — опубликует текст в канал в указанное время (по Москве).\n"
            "• Можно прикрепить фото/видео к команде.\n"
            "<i>Пример:</i> <code>!отложка 18:00 Смотрите новый пост!</code>\n\n"
            "🔘 <b>Кнопка к старому посту</b>\n"
            "• <code>!кнопка [ID_сообщения]</code> — добавит кнопки «Ответить» и «Новое сообщение» к уже опубликованному посту.\n"
            "<i>Пример:</i> <code>!кнопка 42</code>\n\n"
            "📊 <b>Статистика и очистка</b>\n"
            "• <code>!статистика</code> — покажет пользователей, ожидания и список замученных.\n"
            "• <code>!очистить_ответы</code> — сбросит все зависшие ожидания ответов.\n\n"
            "🛡 <b>Модерация (кнопки в лог-группе)</b>\n"
            "Под каждым логом есть кнопки:\n"
            "• <b>🗑 Удалить</b> — удаляет пост из канала.\n"
            "• <b>⚠️ Мут</b> — открывает меню выбора времени (от 15 мин до 24 ч).\n"
            "• <b>✅ Размутить</b> — снимает мут.",
            parse_mode=ParseMode.HTML
        )
    await callback.answer()

@dp.callback_query(F.data == "reply_to_post")
async def ask_for_reply(callback: CallbackQuery):
    active_replies[callback.from_user.id] = callback.message.message_id
    mark_replies_dirty()
    try:
        await callback.answer(url=f"https://t.me/PodslushanoNGHU_bot?start=reply")
    except Exception:
        await callback.answer("Открой бота в личных сообщениях!", show_alert=True)

# ==============================================================================
# ================= ОБРАБОТЧИКИ КОМАНД =========================================
# ==============================================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await save_user(message.from_user.id)
    await save_username(message.from_user.username, message.from_user.id)

    if message.text and "reply" in message.text:
        await message.answer("✍️ <b>Отлично!</b> Напиши или прикрепи то, что хочешь отправить в ответ на пост:", parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
        return
    if message.text and "new" in message.text:
        await message.answer("📩 <b>Напиши или прикрепи сообщение, которое хочешь отправить в канал анонимно:</b>", parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
        return

    if not os.path.exists(WELCOME_IMAGE):
        await message.answer("👋 Привет! Бот работает.", reply_markup=get_main_keyboard())
        return

    try:
        photo = FSInputFile(WELCOME_IMAGE)
        await message.answer_photo(
            photo=photo,
            caption=(
                "👋 <b>Привет!</b>\n\n"
                "Этот бот — официальный анонимный канал связи с <b>Подслушано НГХУ</b>.\n"
                "Мы публикуем твои мысли, новости и приколы без указания авторства.\n\n"
                "📎 <b>Что можно отправить?</b>\n"
                "Текст, фото, видео, музыку, голосовые, кружочки, стикеры и файлы.\n\n"
                "💬 <b>Анонимные ответы</b>\n"
                "Под каждым постом есть кнопка <b>«Ответить»</b>.\n\n"
                "⚠️ <i><b>За оскорбления и травлю администрация ответственности не несет!</b></i>"
            ),
            parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка /start: {e}")
        await message.answer("👋 Привет! Бот работает.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📅 Расписание репетиций")
@dp.message(Command("schedule"))
async def show_schedule(message: Message):
    if not os.path.exists(SCHEDULE_FILE):
        await message.answer("❌ Расписание не загружено.")
        return
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        photo_id = f.read().strip()
    if not photo_id:
        await message.answer("❌ Расписание не загружено.")
        return
    try:
        await bot.send_photo(message.from_user.id, photo=photo_id, caption="📅 <b>Расписание репетиций</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка расписания: {e}")
        await message.answer("❌ Не удалось загрузить расписание.")

# ==============================================================================
# ================= ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ==============================
# ==============================================================================

@dp.message(F.content_type.in_([
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.AUDIO,
    ContentType.DOCUMENT, ContentType.VOICE, ContentType.VIDEO
