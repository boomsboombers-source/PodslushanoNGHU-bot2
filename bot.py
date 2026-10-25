import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

# ==============================================================================
# ================= НАСТРОЙКИ БОТА (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ) =======================
# ==============================================================================

# Токен берется из переменных окружения (на Bothost он задается в панели управления)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID канала, куда бот будет публиковать анонимные сообщения
CHANNEL_ID = -1002304148771

# ID группы, куда бот будет присылать логи (кто, что и когда написал)
LOG_CHAT_ID = -1004306176378

# Список ID пользователей, которые имеют права администратора (могут делать рассылку, менять расписание и т.д.)
ADMIN_IDS = [1088467220, 1690346204]

# Путь к картинке, которая отправляется при команде /start
WELCOME_IMAGE = "pictures/Podslushano.png"

# Пути к файлам для хранения данных (лежат в папке data, чтобы не сбрасываться при обновлении кода)
LOG_FILE = "data/messages.txt"      # Файл с текстовыми логами
USERS_FILE = "data/users.txt"       # Файл со списком ID пользователей (для рассылки)
SCHEDULE_FILE = "data/schedule.txt" # Файл с ID картинки расписания
USERNAMES_FILE = "data/usernames.txt" # Файл для хранения связки @username -> ID

# ==============================================================================
# ================= ИНИЦИАЛИЗАЦИЯ ==============================================
# ==============================================================================

logging.basicConfig(level=logging.INFO)

# Создаем папку data ДО запуска бота, чтобы файлы могли сохраняться
if not os.path.exists("data"):
    os.makedirs("data")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==============================================================================
# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================================
# ==============================================================================

def save_user(user_id):
    """Сохраняет ID пользователя в файл, если его там еще нет."""
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
    """Возвращает список всех сохраненных ID пользователей."""
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return f.read().splitlines()

def get_main_keyboard():
    """Создает и возвращает клавиатуру с кнопкой расписания."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание репетиций")]
        ],
        resize_keyboard=True,
        is_persistent=True,  # Кнопка всегда висит внизу экрана
        input_field_placeholder="Напиши сообщение для канала..."
    )

def save_username(username, user_id):
    """Сохраняет связку @username -> ID в файл."""
    if not username:
        return
    username = username.lower() # Приводим к нижнему регистру для надежности
    if not os.path.exists(USERNAMES_FILE):
        with open(USERNAMES_FILE, "w") as f:
            f.write(f"{username}:{user_id}\n")
        return
    
    with open(USERNAMES_FILE, "r") as f:
        lines = f.read().splitlines()
    
    # Проверяем, есть ли уже такой юзернейм
    for i, line in enumerate(lines):
        if line.startswith(f"{username}:"):
            lines[i] = f"{username}:{user_id}" # Обновляем ID, если изменился
            break
    else:
        lines.append(f"{username}:{user_id}") # Добавляем новый
    
    with open(USERNAMES_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")

def get_id_by_username(username):
    """Ищет ID по юзернейму в файле."""
    username = username.lower().replace("@", "") # Убираем @ на всякий случай
    if not os.path.exists(USERNAMES_FILE):
        return None
    with open(USERNAMES_FILE, "r") as f:
        for line in f:
            if line.startswith(f"{username}:"):
                return int(line.split(":")[1])
    return None

# ==============================================================================
# ================= ОБРАБОТЧИКИ КОМАНД =========================================
# ==============================================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start. Отправляет приветствие и клавиатуру."""
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
                "⚠️ <i><b>За оскорбления, травлю и другие ситуации администрация ответственности не несет! Пожалуйста, соблюдай правила приличия и не спамь.</b></i>"
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

@dp.message(F.text == "📅 Расписание репетиций")
@dp.message(Command("schedule"))
async def show_schedule(message: Message):
    """Обработчик кнопки и команды /schedule. Отправляет картинку расписания."""
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

@dp.message(F.photo, F.caption.startswith("!расписание"))
async def set_schedule(message: Message):
    """Обработчик команды !расписание (только для админов). Сохраняет ID картинки."""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    photo_id = message.photo[-1].file_id
    
    with open(SCHEDULE_FILE, "w") as f:
        f.write(photo_id)
    
    await message.answer("✅ Расписание успешно обновлено! Теперь ученики будут получать эту картинку.")

# ==============================================================================
# ================= ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ==============================
# ==============================================================================

@dp.message(F.text | F.photo | F.video | F.audio | F.document | F.voice | F.video_note | F.sticker)
async def handle_all_messages(message: Message):
    """Главный обработчик. Принимает все типы сообщений и распределяет их."""
    user = message.from_user
    text = message.text or message.caption or ""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # Пропускаем служебные команды, чтобы они не улетели в канал
    if text in ["📅 Расписание репетиций", "/schedule"] or text.startswith("!расписание"):
        return

    # --- ЛОГИКА РАССЫЛКИ (только для админов) ---
    if user.id in ADMIN_IDS and text.lower().startswith("!рассылка"):
        
        clean_text = text.replace("!рассылка", "").replace("!Рассылка", "").strip()
        
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
                await asyncio.sleep(0.05) # Задержка, чтобы Telegram не забанил за спам
            except Exception as e:
                logging.error(f"Не удалось отправить {uid}: {e}")
        
        await message.answer(f"✅ Рассылка завершена. Успешно: {success} из {len(users)}.")
        return

    # --- ЛОГИКА ЛИЧНОГО СООБЩЕНИЯ (только для админов) ---
    # Формат: !лс ID_пользователя или @username Текст сообщения
    if user.id in ADMIN_IDS and text.lower().startswith("!лс"):
        
        # Разбиваем текст на части: команда, получатель, текст
        parts = text.split(maxsplit=2)
        
        if len(parts) < 2:
            await message.answer("❌ Формат: !лс ID_пользователя или @username Текст сообщения")
            return
        
        target = parts[1] # Получаем ID или @username
        
        # Пытаемся определить, что нам дали: ID или username
        if target.startswith("@"):
            # Если это username, пробуем получить ID через Telegram
            try:
                chat = await bot.get_chat(target)
                target_id = chat.id
            except Exception as e:
                await message.answer(f"❌ Не удалось найти пользователя {target}. Убедись, что он существует и запускал бота.")
                return
        else:
            # Если это не username, значит, пробуем преобразовать в число
            try:
                target_id = int(target)
            except ValueError:
                await message.answer("❌ ID пользователя должен быть числом, или укажи @username. Пример: !лс 123456789 Привет!")
                return
        
        # Берем текст, если он есть, иначе пустая строка
        dm_text = parts[2] if len(parts) > 2 else ""
        
        # Убираем возможные остатки команды из подписи к медиа
        if message.caption:
            dm_text = message.caption.replace("!лс", "").replace(parts[1], "").strip()
        
        try:
            # Отправляем сообщение с любым вложением (как в рассылке)
            if message.photo:
                await bot.send_photo(target_id, photo=message.photo[-1].file_id, caption=dm_text)
            elif message.video:
                await bot.send_video(target_id, video=message.video.file_id, caption=dm_text)
            elif message.document:
                await bot.send_document(target_id, document=message.document.file_id, caption=dm_text)
            elif message.audio:
                await bot.send_audio(target_id, audio=message.audio.file_id, caption=dm_text)
            elif message.voice:
                await bot.send_voice(target_id, voice=message.voice.file_id, caption=dm_text)
            elif message.video_note:
                await bot.send_video_note(target_id, video_note=message.video_note.file_id)
            elif message.sticker:
                await bot.send_sticker(target_id, sticker=message.sticker.file_id)
            else:
                await bot.send_message(target_id, dm_text, parse_mode=ParseMode.HTML)
            
            await message.answer(f"✅ Сообщение успешно отправлено пользователю {target}.")
        except Exception as e:
            logging.error(f"Не удалось отправить ЛС {target_id}: {e}")
            await message.answer(f"❌ Не удалось отправить. Возможно, пользователь не запускал бота или заблокировал его.")
        return

    
    # --- ПУБЛИКАЦИЯ В КАНАЛ (для обычных пользователей) ---
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

    # --- ЛОГИРОВАНИЕ ---
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
    """Ловит все остальные типы сообщений (геолокации, контакты и т.д.)."""
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио или стикеры.")

# ==============================================================================
# ================= ЗАПУСК БОТА ================================================
# ==============================================================================

async def main():
    print("Бот запущен. Ожидание сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
