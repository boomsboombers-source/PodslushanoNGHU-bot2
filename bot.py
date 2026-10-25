import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode, ContentType

# ==============================================================================
# ================= НАСТРОЙКИ БОТА (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ) =======================
# ==============================================================================

# Токен берется из переменных окружения (на Bothost он задается в панели управления)
BOT_TOKEN = "8916405519:AAEvdXI81-_La8J4M3LNG0K8kJA5tHdsAzo"#os.getenv("BOT_TOKEN")

# ID канала, куда бот будет публиковать анонимные сообщения
CHANNEL_ID = -1002304148771

# ID группы, куда бот будет присылать логи (кто, что и когда написал)
LOG_CHAT_ID = -1004306176378

# Список ID пользователей, которые имеют права администратора
ADMIN_IDS = [1088467220, 1690346204]

# Путь к картинке, которая отправляется при команде /start
WELCOME_IMAGE = "pictures/Podslushano.png"

# Пути к файлам для хранения данных (в папке data, чтобы не сбрасывались при деплое)
LOG_FILE = "data/messages.txt"        # Файл с текстовыми логами
USERS_FILE = "data/users.txt"         # Файл со списком ID пользователей (для рассылки)
SCHEDULE_FILE = "data/schedule.txt"   # Файл с ID картинки расписания
USERNAMES_FILE = "data/usernames.txt" # Файл со связками @username -> ID

# ==============================================================================
# ================= ИНИЦИАЛИЗАЦИЯ ==============================================
# ==============================================================================

# Настройка логирования (вывод в консоль с датой и временем)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Создаем папку data ДО запуска бота, чтобы файлы могли сохраняться
if not os.path.exists("data"):
    os.makedirs("data")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==============================================================================
# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================================
# ==============================================================================

def save_user(user_id: int):
    """Сохраняет ID пользователя в файл, если его там еще нет."""
    user_id_str = str(user_id)
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                f.write(user_id_str + "\n")
            return
        
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = set(f.read().splitlines())
        
        if user_id_str not in users:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(user_id_str + "\n")
    except Exception as e:
        logging.error(f"Ошибка сохранения пользователя {user_id}: {e}")

def get_all_users() -> list[str]:
    """Возвращает список всех сохраненных ID пользователей."""
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return f.read().splitlines()

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создает и возвращает нижнюю клавиатуру с кнопкой расписания."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📅 Расписание репетиций")]],
        resize_keyboard=True,
        is_persistent=True, # Кнопка всегда висит внизу экрана
        input_field_placeholder="Напиши сообщение для канала..."
    )

def save_username(username: str, user_id: int):
    """Сохраняет связку @username -> ID в файл (атомарно, через временный файл)."""
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
        os.replace(temp_file, USERNAMES_FILE) # Заменяем файл атомарно
    except Exception as e:
        logging.error(f"Ошибка сохранения юзернейма {username}: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)

def get_id_by_username(username: str) -> int | None:
    """Ищет ID по юзернейму в локальном файле (если пользователь скрыт от Telegram)."""
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

async def _send_media_with_caption(target_id: int, message: Message, caption: str = "", parse_mode=None):
    """
    Универсальная функция для отправки любого типа вложения (или текста) с подписью.
    Используется и для рассылки, и для личных сообщений (!лс), и для публикации в канал.
    """
    try:
        if message.photo:
            await bot.send_photo(target_id, photo=message.photo[-1].file_id, caption=caption, parse_mode=parse_mode)
        elif message.video:
            await bot.send_video(target_id, video=message.video.file_id, caption=caption, parse_mode=parse_mode)
        elif message.document:
            await bot.send_document(target_id, document=message.document.file_id, caption=caption, parse_mode=parse_mode)
        elif message.audio:
            await bot.send_audio(target_id, audio=message.audio.file_id, caption=caption, parse_mode=parse_mode)
        elif message.voice:
            await bot.send_voice(target_id, voice=message.voice.file_id, caption=caption, parse_mode=parse_mode)
        elif message.video_note:
            await bot.send_video_note(target_id, video_note=message.video_note.file_id)
        elif message.sticker:
            await bot.send_sticker(target_id, sticker=message.sticker.file_id)
        else:
            await bot.send_message(target_id, caption, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"Не удалось отправить медиа {message.content_type} пользователю {target_id}: {e}")
        raise

# ==============================================================================
# ================= ОБРАБОТЧИКИ КОМАНД =========================================
# ==============================================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start. Отправляет приветствие и клавиатуру."""
    save_user(message.from_user.id)
    save_username(message.from_user.username, message.from_user.id) # Запоминаем ник
    
    # Проверяем наличие картинки перед отправкой
    if not os.path.exists(WELCOME_IMAGE):
        await message.answer(
            "👋 <b>Привет!</b>\n\nЭтот бот отправляет анонимные сообщения в канал.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
        return

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
        logging.error(f"Ошибка при отправке картинки /start: {e}")
        await message.answer(
            "👋 <b>Привет!</b>\n\nЭтот бот отправляет анонимные сообщения в канал.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )

@dp.message(F.text == "📅 Расписание репетиций")
@dp.message(Command("schedule"))
async def show_schedule(message: Message):
    """Обработчик кнопки и команды /schedule. Отправляет картинку расписания."""
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
        logging.error(f"Ошибка отправки расписания пользователю {message.from_user.id}: {e}")
        await message.answer("❌ Не удалось загрузить расписание. Попробуй позже.")

@dp.message((F.text | F.caption).startswith("!расписание"), F.from_user.id.in_(ADMIN_IDS))
async def set_schedule(message: Message):
    """Обработчик команды !расписание (только для админов). Сохраняет ID картинки."""
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

# ==============================================================================
# ================= ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ==============================
# ==============================================================================

@dp.message(F.content_type.in_([
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.AUDIO,
    ContentType.DOCUMENT, ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.STICKER
]))
async def handle_all_messages(message: Message):
    """Главный обработчик. Принимает все типы сообщений и распределяет их."""
    user = message.from_user
    text = message.text or message.caption or ""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # Сохраняем пользователя и его ник при любом действии
    save_user(user.id)
    save_username(user.username, user.id)

    # Пропускаем служебные команды, чтобы они не улетели в канал
    if text in ["📅 Расписание репетиций", "/schedule"] or text.lower().startswith("!расписание"):
        return

    # --- ЛОГИКА РАССЫЛКИ (только для админов) ---
    if user.id in ADMIN_IDS and text.lower().startswith("!рассылка"):
        clean_text = text.partition("!рассылка")[2].strip()
        
        if not clean_text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            await message.answer("❌ Текст рассылки пустой. Напиши: !рассылка Твой текст")
            return
        
        users = get_all_users()
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
                await asyncio.sleep(0.05) # Задержка, чтобы Telegram не забанил за спам
            except Exception:
                continue
        
        await message.answer(f"✅ Рассылка завершена. Успешно: {success} из {len(users)}.")
        return

    # --- ЛОГИКА ЛИЧНОГО СООБЩЕНИЯ (только для админов) ---
    if user.id in ADMIN_IDS and text.lower().startswith("!лс"):
        parts = text.split(maxsplit=2)
        
        if len(parts) < 2:
            await message.answer("❌ Формат: !лс ID_пользователя или @username Текст сообщения")
            return
        
        target = parts[1]
        
        try:
            if target.startswith("@"):
                # Сначала ищем в локальной базе (на случай, если юзер скрыт от ТГ)
                target_id = get_id_by_username(target)
                if not target_id:
                    # Если в базе нет, спрашиваем у Telegram
                    chat = await bot.get_chat(target)
                    target_id = chat.id
                    save_username(target, target_id) # Сохраняем на будущее
            else:
                target_id = int(target)
                
            # Проверка на попытку написать в канал/группу (у групп ID отрицательный)
            if target_id < 0:
                await message.answer("❌ Нельзя отправлять личные сообщения в группы или каналы.")
                return

        except Exception:
            await message.answer(f"❌ Не удалось найти пользователя {target}. Убедись, что он существует и запускал бота.")
            return
        
        # Берем текст из третьей части (чтобы не вырезать ID из подписи)
        dm_text = parts[2] if len(parts) > 2 else ""
        
        try:
            await _send_media_with_caption(target_id, message, caption=dm_text, parse_mode=ParseMode.HTML)
            await message.answer(f"✅ Сообщение успешно отправлено пользователю {target}.")
        except Exception:
            await message.answer("❌ Не удалось отправить. Возможно, пользователь заблокировал бота.")
        return

    # --- ПУБЛИКАЦИЯ В КАНАЛ (для обычных пользователей) ---
    signature = "\n\n📬 @PodslushanoNGHU_bot"

    try:
        await _send_media_with_caption(CHANNEL_ID, message, caption=(text + signature), parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Не удалось отправить в канал: {e}")
        await message.answer("❌ Ошибка: не удалось отправить сообщение в канал. Проверь права бота.")
        return

    # --- ЛОГИРОВАНИЕ В АДМИН-ЧАТ (защищено от падения) ---
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
        logging.error(f"Не удалось отправить лог в чат {LOG_CHAT_ID}: {e}")

    # --- ЛОГИРОВАНИЕ В ФАЙЛ ---
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {user.full_name} ({username}, ID: {user.id})\n")
            f.write(f"Тип: {message.content_type}. Текст: {text}\n")
            f.write("-" * 40 + "\n")
    except Exception as e:
        logging.error(f"Ошибка записи в файл лога: {e}")

    await message.answer("✅ Сообщение отправлено в канал анонимно.")

@dp.message()
async def handle_other_messages(message: Message):
    """Ловит всё остальное (геолокации, контакты и т.д.)."""
    save_user(message.from_user.id)
    save_username(message.from_user.username, message.from_user.id)
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио или стикеры.")

# ==============================================================================
# ================= ЗАПУСК БОТА ================================================
# ==============================================================================

async def main():
    print("Бот запущен. Ожидание сообщений...")
    # skip_updates=True означает, что бот не будет обрабатывать старые сообщения, пришедшие пока он лежал
    await dp.start_polling(bot, skip_updates=True, allowed_updates=["message"])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
