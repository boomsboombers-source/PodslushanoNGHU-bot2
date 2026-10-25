import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен из переменных окружения
CHANNEL_ID = -1002304148771         # ID канала "Подслушано НГХУ"
LOG_CHAT_ID = -1004306176378        # ID группы для логов
ADMIN_IDS = [1088467220, 1690346204]            # Список ID админов
WELCOME_IMAGE = "pictures/Podslushano.png"
LOG_FILE = "data/messages.txt"
USERS_FILE = "data/users.txt"
SCHEDULE_FILE = "data/schedule.txt"      # Файл, где хранится ID картинки расписания

# ================= ИНИЦИАЛИЗАЦИЯ =================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= ФУНКЦИИ =================
def save_user(user_id):
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            f.write(str(user_id) + "\n")
        return
    with open(USERS_FILE, "r") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(USERS_FILE, "a") as f:
            f.write(str(user_id) + "\n")

def ensure_data_dir():
    if not os.path.exists("data"):
        os.makedirs("data")

def get_all_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return f.read().splitlines()

# Клавиатура с постоянной кнопкой расписания внизу
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание репетиций")]
        ],
        resize_keyboard=True,        # Аккуратный размер кнопки
        is_persistent=True,          # Кнопка всегда висит внизу
        input_field_placeholder="Напиши сообщение для канала..."
    )

# ================= ОБРАБОТЧИКИ =================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    save_user(message.from_user.id)
    try:
        photo = FSInputFile(WELCOME_IMAGE)
        await message.answer_photo(
            photo=photo,
            caption=(
                "👋 <b>Привет!</b>\n\n"
                "Этот бот отправляет анонимные сообщения в канал <b>Подслушано НГХУ</b>.\n\n"
                "Просто напиши сюда текст или прикрепи фото/видео/стикер — оно будет опубликовано анонимно.\n\n"
                "📅 Чтобы узнать расписание репетиций, нажми на кнопку ниже или введи /schedule.\n\n"
                "⚠️ <i><b>За оскорбления, травлю и другие ситуации администрация ответсвенности не несет! Пожалуйста, соблюдай правила приличия и не спамь. </b></i>"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке картинки: {e}")
        await message.answer(
            "Привет! Бот работает. Напиши сообщение, и я его отправлю.",
            reply_markup=get_main_keyboard()
        )

# --- ОТПРАВКА РАСПИСАНИЯ (Кнопка и команда /schedule) ---
@dp.message(F.text == "📅 Расписание репетиций")
@dp.message(Command("schedule"))
async def show_schedule(message: Message):
    if not os.path.exists(SCHEDULE_FILE):
        await message.answer("❌ Расписание пока не загружено. Попробуй позже.")
        return
    
    with open(SCHEDULE_FILE, "r") as f:
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

# --- ЗАГРУЗКА РАСПИСАНИЯ АДМИНОМ (!расписание) ---
@dp.message(F.photo, F.caption == "!расписание")
async def set_schedule(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return  # Игнорируем, если это не админ
    
    photo_id = message.photo[-1].file_id
    
    with open(SCHEDULE_FILE, "w") as f:
        f.write(photo_id)
    
    await message.answer("✅ Расписание успешно обновлено! Теперь ученики будут получать эту картинку.")

# --- ЕДИНЫЙ ОБРАБОТЧИК ДЛЯ ВСЕХ ТИПОВ СООБЩЕНИЙ ---
@dp.message(F.text | F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.sticker)
async def handle_all_messages(message: Message):
    user = message.from_user
    text = message.text or message.caption or ""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # Пропускаем служебные команды
    if text in ["📅 Расписание репетиций", "/schedule", "!расписание"]:
        return

    # --- ЛОГИКА РАССЫЛКИ ---
    if user.id in ADMIN_IDS and text.startswith("!рассылка"):
        
        clean_text = text.replace("!рассылка", "").strip()
        
        if not clean_text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            await message.answer("❌ Текст рассылки пустой. Напиши: !рассылка Твой текст")
            return
        
        users = get_all_users()
        await message.answer(f"🚀 Начинаю рассылку для {len(users)} пользователей...")
        
        success = 0
        for uid in users:
            try:
                if message.photo or message.video or message.document or message.audio or message.voice or message.video_note or message.sticker:
                    if message.photo:
                        await bot.send_photo(int(uid), photo=message.photo[-1].file_id, caption=clean_text)
                    elif message.video:
                        await bot.send_video(int(uid), video=message.video.file_id, caption=clean_text)
                    elif message.document:
                        await bot.send_document(int(uid), document=message.document.file_id, caption=clean_text)
                    elif message.audio:
                        await bot.send_audio(int(uid), audio=message.audio.file_id, caption=clean_text)
                    elif message.voice:
                        await bot.send_voice(int(uid), voice=message.voice.file_id, caption=clean_text)
                    elif message.video_note:
                        await bot.send_video_note(int(uid), video_note=message.video_note.file_id)
                    elif message.sticker:
                        await bot.send_sticker(int(uid), sticker=message.sticker.file_id)
                else:
                    await bot.send_message(int(uid), clean_text, parse_mode=ParseMode.HTML)
                
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logging.error(f"Не удалось отправить {uid}: {e}")
        
        await message.answer(f"✅ Рассылка завершена. Успешно: {success} из {len(users)}.")
        return
    # -----------------------

    # Публикация в канал
    save_user(user.id)
    
    signature = "\n\n📬 @PodslushanoNGHU_bot"

    try:
        if message.photo:
            await bot.send_photo(chat_id=CHANNEL_ID, photo=message.photo[-1].file_id, caption=(message.caption or "") + signature)
        elif message.video:
            await bot.send_video(chat_id=CHANNEL_ID, video=message.video.file_id, caption=(message.caption or "") + signature)
        elif message.document:
            await bot.send_document(chat_id=CHANNEL_ID, document=message.document.file_id, caption=(message.caption or "") + signature)
        elif message.audio:
            await bot.send_audio(chat_id=CHANNEL_ID, audio=message.audio.file_id, caption=(message.caption or "") + signature)
        elif message.voice:
            await bot.send_voice(chat_id=CHANNEL_ID, voice=message.voice.file_id, caption=(message.caption or "") + signature)
        elif message.video_note:
            await bot.send_video_note(chat_id=CHANNEL_ID, video_note=message.video_note.file_id)
        elif message.sticker:
            await bot.send_sticker(chat_id=CHANNEL_ID, sticker=message.sticker.file_id)
        else:
            await bot.send_message(chat_id=CHANNEL_ID, text=text + signature)
    except Exception as e:
        logging.error(f"Не удалось отправить в канал: {e}")
        await message.answer("❌ Ошибка: не удалось отправить сообщение в канал. Проверь права бота.")
        return

    # Логи
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
        await bot.send_message(LOG_CHAT_ID, log_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Не удалось отправить лог в чат: {e}")

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {user.full_name} ({username}, ID: {user.id})\n")
            f.write(f"Тип: {message.content_type}. Текст: {text}\n")
            f.write("-" * 40 + "\n")
    except Exception as e:
        logging.error(f"Ошибка записи в файл: {e}")

    await message.answer("✅ Сообщение отправлено в канал анонимно.")

@dp.message()
async def handle_other_messages(message: Message):
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио или стикеры.")

# ================= ЗАПУСК =================
async def main():
    ensure_data_dir()
    print("Бот запущен. Ожидание сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
