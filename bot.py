import asyncio
import logging
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode, ContentType

# ==============================================================================
# ================= НАСТРОЙКИ БОТА (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ) =======================
# ==============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = -1002304148771       # ID канала
LOG_CHAT_ID = -1004306176378      # ID группы логов
ADMIN_IDS = [1088467220, 1690346204] # ID админов

WELCOME_IMAGE = "pictures/Podslushano.png"

LOG_FILE = "data/messages.txt"
USERS_FILE = "data/users.txt"
SCHEDULE_FILE = "data/schedule.txt"
USERNAMES_FILE = "data/usernames.txt"
REPLIES_FILE = "data/replies.json"

# ==============================================================================
# ================= ИНИЦИАЛИЗАЦИЯ ==============================================
# ==============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not os.path.exists("data"):
    os.makedirs("data")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище: {user_id: message_id_в_канале}
active_replies = {}
# Кэш всех пользователей в памяти (для быстрой рассылки)
cached_users = set()

# ==============================================================================
# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================================
# ==============================================================================

def load_users_cache():
    """Загружает ID всех пользователей в память при старте."""
    global cached_users
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            cached_users = set(f.read().splitlines())
    else:
        cached_users = set()

def save_user(user_id: int):
    """Добавляет ID в память и файл, если его там еще нет."""
    global cached_users
    user_id_str = str(user_id)
    if user_id_str not in cached_users:
        cached_users.add(user_id_str)
        try:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(user_id_str + "\n")
        except Exception as e:
            logging.error(f"Ошибка сохранения пользователя {user_id}: {e}")

def get_all_users() -> list[str]:
    """Возвращает кэшированный список пользователей (мгновенно)."""
    return list(cached_users)

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📅 Расписание репетиций")]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напиши сообщение для канала..."
    )

def save_username(username: str, user_id: int):
    if not username:
        return
    username = username.lower().lstrip('@')
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
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(temp_file, USERNAMES_FILE)
    except Exception as e:
        logging.error(f"Ошибка сохранения юзернейма {username}: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)

def get_id_by_username(username: str) -> int | None:
    username = username.lower().lstrip('@')
    if not os.path.exists(USERNAMES_FILE):
        return None
    with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(f"{username}:"):
                try:
                    return int(line.split(":")[1])
                except (IndexError, ValueError):
                    continue
    return None

# --- ФУНКЦИИ ДЛЯ СОХРАНЕНИЯ ОТВЕТОВ (АТОМАРНО) ---
def load_replies():
    global active_replies
    if os.path.exists(REPLIES_FILE):
        try:
            with open(REPLIES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                active_replies = {int(k): v for k, v in data.items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки replies.json: {e}")

def save_replies():
    try:
        temp_file = REPLIES_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(active_replies, f)
        os.replace(temp_file, REPLIES_FILE) # Атомарная замена
    except Exception as e:
        logging.error(f"Ошибка сохранения replies.json: {e}")

# --- УНИВЕРСАЛЬНАЯ ОТПРАВКА ---
async def _send_media_with_caption(target_id: int, message: Message, caption: str = "", parse_mode=None, reply_to_message_id: int = None) -> Message:
    try:
        if message.photo:
            return await bot.send_photo(target_id, photo=message.photo[-1].file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
        elif message.video:
            return await bot.send_video(target_id, video=message.video.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
        elif message.document:
            return await bot.send_document(target_id, document=message.document.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
        elif message.audio:
            return await bot.send_audio(target_id, audio=message.audio.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
        elif message.voice:
            return await bot.send_voice(target_id, voice=message.voice.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
        elif message.video_note:
            return await bot.send_video_note(target_id, video_note=message.video_note.file_id, reply_to_message_id=reply_to_message_id)
        elif message.sticker:
            return await bot.send_sticker(target_id, sticker=message.sticker.file_id, reply_to_message_id=reply_to_message_id)
        elif message.contact:
            return await bot.send_contact(target_id, phone_number=message.contact.phone_number, first_name=message.contact.first_name, reply_to_message_id=reply_to_message_id)
        elif message.location:
            return await bot.send_location(target_id, latitude=message.location.latitude, longitude=message.location.longitude, reply_to_message_id=reply_to_message_id)
        else:
            return await bot.send_message(target_id, caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        logging.error(f"Не удалось отправить {message.content_type} в {target_id}: {e}")
        raise

# ==============================================================================
# ================= ОБРАБОТЧИКИ КОМАНД =========================================
# ==============================================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    save_user(message.from_user.id)
    save_username(message.from_user.username, message.from_user.id)
    
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
                "Бот принимает <b>абсолютно любой контент</b>:\n"
                "• 📝 Текстовые сообщения\n"
                "• 📸 Фотографии (можно с подписями)\n"
                "• 🎥 Видео и гифки\n"
                "• 🎵 Аудио (музыка) и 🎙 голосовые (ГС)\n"
                "• 🟢 Видео-кружочки\n"
                "• 🖼 Стикеры и документы (файлы)\n\n"

                "⚙️ <b>Доступные команды:</b>\n"
                "• <code>/start</code> — перезапустить бота и вызвать это меню.\n"
                "• <code>/schedule</code> — получить актуальное расписание репетиций в ЛС.\n"
                "• <b>Кнопка внизу</b> — быстрое расписание (всегда под рукой).\n\n"

                "💬 <b>Анонимные ответы</b>\n"
                "Под каждым постом в канале есть кнопка <b>«Ответить»</b>. Нажми на неё, чтобы написать анонимный ответ на любое сообщение (можно тоже прикреплять фото или стикеры!).\n\n"

                "⚠️ <i><b>За оскорбления, травлю и любые другие конфликтные ситуации администрация ответственности не несет! Пожалуйста, соблюдай правила приличия и не спамь.</b></i>"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке картинки /start: {e}")
        await message.answer("👋 Привет! Бот работает.", reply_markup=get_main_keyboard())

@dp.message(F.text == "📅 Расписание репетиций")
@dp.message(Command("schedule"))
async def show_schedule(message: Message):
    if not os.path.exists(SCHEDULE_FILE):
        await message.answer("❌ Расписание пока не загружено. Попробуй позже.")
        return
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        photo_id = f.read().strip()
    if not photo_id:
        await message.answer("❌ Расписание пока не загружено. Попробуй позже.")
        return
    try:
        await bot.send_photo(
            chat_id=message.from_user.id,
            photo=photo_id,
            caption="📅 <b>Актуальное расписание репетиций</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Ошибка отправки расписания: {e}")
        await message.answer("❌ Не удалось загрузить расписание. Попробуй позже.")

@dp.message((F.text | F.caption).startswith("!расписание"), F.from_user.id.in_(ADMIN_IDS))
async def set_schedule(message: Message):
    if not message.photo:
        await message.answer("❌ Пришлите команду вместе с картинкой расписания.")
        return
    photo_id = message.photo[-1].file_id
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            f.write(photo_id)
        await message.answer("✅ Расписание успешно обновлено!")
    except Exception as e:
        logging.error(f"Ошибка записи расписания: {e}")
        await message.answer("❌ Не удалось сохранить файл расписания.")

@dp.callback_query(F.data == "reply_to_post")
async def ask_for_reply(callback: CallbackQuery):
    await callback.answer()
    active_replies[callback.from_user.id] = callback.message.message_id
    save_replies()
    await callback.message.answer("✍️ Напиши или прикрепи то, что хочешь отправить в ответ на это сообщение (это будет анонимно):")

@dp.callback_query()
async def handle_unknown_callback(callback: CallbackQuery):
    await callback.answer("Кнопка устарела или недействительна.", show_alert=True)

# ==============================================================================
# ================= ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ==============================
# ==============================================================================

@dp.message(F.content_type.in_([
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.AUDIO,
    ContentType.DOCUMENT, ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.STICKER,
    ContentType.CONTACT, ContentType.LOCATION
]))
async def handle_all_messages(message: Message):
    user = message.from_user
    text = message.text or message.caption or ""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    save_user(user.id)
    save_username(user.username, user.id)

    # Если пользователь в режиме ответа, но прислал служебную команду — сбрасываем
    if user.id in active_replies and (text in ["📅 Расписание репетиций", "/schedule"] or text.lower().startswith("!")):
        del active_replies[user.id]
        save_replies()

    if text in ["📅 Расписание репетиций", "/schedule"] or text.lower().startswith("!расписание"):
        return

    # --- АДМИНСКАЯ СТАТИСТИКА ---
    if user.id in ADMIN_IDS and text.lower().startswith("!статистика"):
        await message.answer(
            f"📊 <b>Статистика бота:</b>\n"
            f"👥 Пользователей в базе: <b>{len(cached_users)}</b>\n"
            f"💬 Активных ожиданий ответа: <b>{len(active_replies)}</b>",
            parse_mode=ParseMode.HTML
        )
        return

    # --- АДМИНСКАЯ ОЧИСТКА ОТВЕТОВ ---
    if user.id in ADMIN_IDS and text.lower().startswith("!очистить_ответы"):
        active_replies.clear()
        save_replies()
        await message.answer("✅ Все ожидания ответов сброшены (кнопки очищены).")
        return

    # --- ЛОГИКА ОТВЕТА НА СООБЩЕНИЕ ---
    if user.id in active_replies:
        original_msg_id = active_replies.pop(user.id)
        save_replies()
        
        # Формируем текст с обычной подписью (без плашки "Ответ на пост")
        reply_caption = f"{text}\n\n📬 @PodslushanoNGHU_bot" if text else "📬 @PodslushanoNGHU_bot"
        
        try:
            sent_reply = await _send_media_with_caption(
                CHANNEL_ID, 
                message, 
                caption=reply_caption, 
                parse_mode=ParseMode.HTML,
                reply_to_message_id=original_msg_id
            )
            
            chat_id_str = str(CHANNEL_ID).replace("-100", "") 
            reply_link = f"https://t.me/c/{chat_id_str}/{sent_reply.message_id}"
            reply_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔗 Перейти к ответу", url=reply_link)]]
            )

            log_text = (
                f"💬 <b>Ответ</b>\n"
                f"👤 <b>Автор:</b> {user.full_name}\n"
                f"🔗 Username: @{user.username if user.username else 'нет'}\n"
                f"🆔 ID: <code>{user.id}</code>\n"
                f"🕒 Время: {now}\n"
                f"📝 <b>Тип:</b> {message.content_type}\n"
                f"📝 <b>Текст/Подпись:</b> {text}"
            )
            await bot.send_message(LOG_CHAT_ID, log_text, parse_mode=ParseMode.HTML, reply_markup=reply_kb)
            
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{now}] {user.full_name} ({user.username}, ID: {user.id}) - ОТВЕТ\n")
                f.write(f"Тип: {message.content_type}. Текст: {text}\n")
                f.write("-" * 40 + "\n")
                
            await message.answer("✅ Твой анонимный ответ опубликован в канале!")
        except Exception as e:
            logging.error(f"Ошибка отправки ответа в канал: {e}")
            await message.answer("❌ Не удалось отправить ответ. Возможно, пост был удален.")
        return

    # --- ЛОГИКА РАССЫЛКИ (только для админов) ---
    if user.id in ADMIN_IDS and text.lower().startswith("!рассылка"):
        clean_text = text.partition("!рассылка")[2].strip()
        if not clean_text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            await message.answer("❌ Текст рассылки пустой.")
            return
        
        users = get_all_users() # Берем из кэша (мгновенно)
        if not users:
            await message.answer("❌ База пользователей пуста.")
            return
            
        await message.answer(f"🚀 Начинаю рассылку для {len(users)} пользователей...")
        success = 0
        for uid_str in users:
            try:
                uid = int(uid_str)
                await _send_media_with_caption(uid, message, caption=clean_text, parse_mode=ParseMode.HTML)
                success += 1
                await asyncio.sleep(0.05) # Защита от бана Telegram
            except Exception:
                continue
        await message.answer(f"✅ Рассылка завершена. Успешно: {success} из {len(users)}.")
        return

    # --- ЛОГИКА ЛИЧНОГО СООБЩЕНИЯ (только для админов) ---
    if user.id in ADMIN_IDS and text.lower().startswith("!лс"):
        parts = text.split(maxsplit=2)
        if len(parts) < 2:
            await message.answer("❌ Формат: !лс ID_пользователя или @username Текст")
            return
        target = parts[1]
        try:
            if target.startswith("@"):
                target_id = get_id_by_username(target)
                if not target_id:
                    chat = await bot.get_chat(target)
                    target_id = chat.id
                    save_username(target, target_id)
            else:
                target_id = int(target)
            if target_id < 0:
                await message.answer("❌ Нельзя отправлять личные сообщения в группы/каналы.")
                return
        except Exception:
            await message.answer(f"❌ Не удалось найти пользователя {target}.")
            return
        dm_text = parts[2] if len(parts) > 2 else ""
        try:
            await _send_media_with_caption(target_id, message, caption=dm_text, parse_mode=ParseMode.HTML)
            await message.answer(f"✅ Сообщение успешно отправлено пользователю {target}.")
        except Exception:
            await message.answer("❌ Не удалось отправить. Возможно, пользователь заблокировал бота.")
        return

    # --- ПУБЛИКАЦИЯ В КАНАЛ (для обычных пользователей) ---
    signature = "\n\n📬 @PodslushanoNGHU_bot"
    
    reply_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data="reply_to_post")]]
    )

    try:
        sent_msg = await _send_media_with_caption(
            CHANNEL_ID, 
            message, 
            caption=(text + signature) if text else "", 
            parse_mode=ParseMode.HTML
        )
        
        try:
            await bot.edit_message_reply_markup(
                chat_id=CHANNEL_ID,
                message_id=sent_msg.message_id,
                reply_markup=reply_kb
            )
        except Exception as e:
            logging.error(f"Не удалось прикрепить кнопку к посту: {e}")

    except Exception as e:
        logging.error(f"Не удалось отправить в канал: {e}")
        await message.answer("❌ Ошибка: не удалось отправить сообщение в канал.")
        return

    # --- ЛОГИРОВАНИЕ В АДМИН-ЧАТ ---
    chat_id_str = str(CHANNEL_ID).replace("-100", "") 
    msg_link = f"https://t.me/c/{chat_id_str}/{sent_msg.message_id}"
    log_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔗 Перейти к сообщению", url=msg_link)]]
    )

    username = f"@{user.username}" if user.username else "нет username"
    log_text = (
        f"👤 <b>Автор:</b> {user.full_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🕒 Время: {now}\n"
        f"💬 <b>Тип:</b> {message.content_type}\n"
        f"📝 <b>Текст/Подпись:</b> {text}"
    )
    try:
        await bot.send_message(LOG_CHAT_ID, log_text, parse_mode=ParseMode.HTML, reply_markup=log_kb)
    except Exception as e:
        logging.error(f"Не удалось отправить лог в чат: {e}")

    # --- ЛОГИРОВАНИЕ В ФАЙЛ ---
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {user.full_name} ({username}, ID: {user.id})\n")
            f.write(f"Тип: {message.content_type}. Текст: {text}\n")
            f.write("-" * 40 + "\n")
    except Exception as e:
        logging.error(f"Ошибка записи в файл лога: {e}")

    channel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📢 Перейти в канал", url="https://t.me/+rgCZ7wpZaIE0YmZi")]]
    )
    await message.answer("✅ Сообщение отправлено в канал анонимно.", reply_markup=channel_kb)

@dp.message()
async def handle_other_messages(message: Message):
    save_user(message.from_user.id)
    save_username(message.from_user.username, message.from_user.id)
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио, стикеры или геолокацию.")

# ==============================================================================
# ================= ЗАПУСК БОТА ================================================
# ==============================================================================

async def main():
    load_users_cache() # Загружаем пользователей в память
    load_replies()     # Загружаем активные ответы
    print("Бот запущен. Ожидание сообщений...")
    await dp.start_polling(bot, skip_updates=True, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
