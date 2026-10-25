import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен берётся из переменных окружения
CHANNEL_ID = -1002304148771
LOG_CHAT_ID = -1004306176378
ADMIN_IDS = [1088467220]  # Список ID админов
WELCOME_IMAGE = "pictures/Podslushano.png"
LOG_FILE = "messages.txt"
USERS_FILE = "users.txt"

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

def get_all_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return f.read().splitlines()

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
                "⚠️ <i>Пожалуйста, соблюдай правила приличия и не спамь.</i>"
            ),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке картинки: {e}")
        await message.answer("Привет! Бот работает. Напиши сообщение, и я его отправлю.")

# --- ЕДИНЫЙ ОБРАБОТЧИК ДЛЯ ВСЕХ ТИПОВ СООБЩЕНИЙ ---
@dp.message(F.text | F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.sticker)
async def handle_all_messages(message: Message):
    user = message.from_user
    text = message.text or message.caption or ""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # --- ЛОГИКА РАССЫЛКИ ---
    if user.id in ADMIN_IDS and text.startswith("!рассылка"):
        
        clean_text = text.replace("!рассылка", "").strip()
        
        # Проверка: если пусто и нет вложений — отмена
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

    # Если это обычное сообщение от пользователя - публикуем в канал
    save_user(user.id)
    
    # Подпись с юзернеймом бота
    signature = "\n\n📬 @PodslushanoNGHU_bot"

    try:
        if message.photo:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=message.photo[-1].file_id,
                caption=(message.caption or "") + signature
            )
        elif message.video:
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=message.video.file_id,
                caption=(message.caption or "") + signature
            )
        elif message.document:
            await bot.send_document(
                chat_id=CHANNEL_ID,
                document=message.document.file_id,
                caption=(message.caption or "") + signature
            )
        elif message.audio:
            await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=message.audio.file_id,
                caption=(message.caption or "") + signature
            )
        elif message.voice:
            await bot.send_voice(
                chat_id=CHANNEL_ID,
                voice=message.voice.file_id,
                caption=(message.caption or "") + signature
            )
        elif message.video_note:
            # У кружочков нет подписи
            await bot.send_video_note(
                chat_id=CHANNEL_ID,
                video_note=message.video_note.file_id
            )
        elif message.sticker:
            # У стикеров нет подписи
            await bot.send_sticker(
                chat_id=CHANNEL_ID,
                sticker=message.sticker.file_id
            )
        else:
            # Если это просто текст
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=text + signature
            )
    except Exception as e:
        logging.error(f"Не удалось отправить в канал: {e}")
        await message.answer("❌ Ошибка: не удалось отправить сообщение в канал. Проверь права бота.")
        return

    # Формируем лог
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

    # Дублируем в файл
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
    # Ловит всё остальное (локации, контакты и т.д.)
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио или стикеры.")

# ================= ЗАПУСК =================
async def main():
    print("Бот запущен. Ожидание сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
