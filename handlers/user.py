import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode, ContentType
from config import CHANNEL_ID, LOG_CHAT_ID, WELCOME_IMAGE, SCHEDULE_FILE, SCHEDULE2_FILE, ADMIN_IDS, MODERATOR_IDS, STAFF_IDS
from services.storage import (
    save_user, save_username, active_replies, mark_replies_dirty, check_mute,
    active_replies_lock, save_log_msg_id, get_log_msg_id
)
from services.media import _send_media_with_caption, esc
from services.database import log_message_db, get_username_by_id_db

user_router = Router()

def get_main_keyboard(user_id: int = None, mode: str = "default"):
    # Базовые ряды (всегда на месте)
    rows = [
        [KeyboardButton(text="📅 События"), KeyboardButton(text="📋 Команды")],
        [KeyboardButton(text="📌 Замены"), KeyboardButton(text="📅 Репетиции")],
    ]
    
    # Добавляем новый ряд СВЕРХУ в зависимости от режима
    if mode == "admin" and user_id in ADMIN_IDS:
        rows.insert(0, [
            KeyboardButton(text="🛡 Модер-панель"), 
            KeyboardButton(text="🛠 Админ-панель")
        ])
    elif mode == "moder" and user_id in STAFF_IDS:
        rows.insert(0, [
            KeyboardButton(text="🛡 Модер-панель")
        ])
        
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Напиши сообщение для канала..."
    )

async def get_signed_signature(user) -> str:
    """Формирует подпись автора для неанонимных сообщений."""
    username = await get_username_by_id_db(user.id)
    signature = f"\n\n👤 <b>Автор:</b> {esc(user.full_name)}"
    if username and username != "нет username":
        # get_username_by_id_db возвращает "@name" или "нет username"
        signature += f" ({esc(username)})"
    return signature + "\n"

@user_router.message(CommandStart())
async def cmd_start(message: Message):
    await save_user(message.from_user.id)
    await save_username(message.from_user.username, message.from_user.id)

    # 1. Определяем режим клавиатуры на основе /start xxx
    text_lower = (message.text or "").lower()
    args = text_lower.split(maxsplit=1)
    start_arg = args[1] if len(args) > 1 else ""
    mode = "default"

    if start_arg == "admin":
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("⛔ У вас нет доступа к админ-панели.")
            return
        mode = "admin"
    elif start_arg == "moder":
        if message.from_user.id not in STAFF_IDS:
            await message.answer("⛔ У вас нет доступа к панели модератора.")
            return
        mode = "moder"

    # 2. Обработка reply и new
    if start_arg == "reply":
        await message.answer("✍️ <b>Отлично!</b> Напиши или прикрепи то, что хочешь отправить в ответ на пост:", parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard(message.from_user.id, mode=mode))
        return
    if start_arg == "new":
        await message.answer("📩 <b>Напиши или прикрепи сообщение, которое хочешь отправить в канал анонимно:</b>", parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard(message.from_user.id, mode=mode))
        return

    # 3. Отправка приветствия
    if not os.path.exists(WELCOME_IMAGE):
        await message.answer("👋 Привет! Бот работает.", reply_markup=get_main_keyboard(message.from_user.id, mode=mode))
    else:
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
                    "⚙️ <b>Основные команды вы можете посмотреть нажав кнопку внизу экрана</b>\n\n"
                    "💬 <b>Анонимные ответы</b>\n"
                    "Под каждым постом в канале есть кнопка <b>«Ответить»</b>. Нажми, чтобы написать анонимный ответ (можно с фото или стикерами).\n\n"
                    "⚠️ <i><b>За оскорбления, травлю и любые другие конфликтные ситуации администрация ответственности не несет! Пожалуйста, соблюдай правила приличия и не спамь.</b></i>"
                ),
                parse_mode=ParseMode.HTML, 
                reply_markup=get_main_keyboard(message.from_user.id, mode=mode)
            )
        except Exception as e:
            logging.error(f"Ошибка /start: {e}")
            await message.answer("👋 Привет! Бот работает.", reply_markup=get_main_keyboard(message.from_user.id, mode=mode))

    # 4. Показываем панели, если это /start admin или /start moder
    if mode == "admin":
        from handlers.admin import admin_panel
        await admin_panel(message)
    elif mode == "moder":
        from handlers.admin import moderator_panel
        await moderator_panel(message)


@user_router.message(F.text.in_(["📅 Репетиции", "📅 Расписание репетиций"]))
async def show_schedule(message: Message):
    if not os.path.exists(SCHEDULE_FILE):
        await message.answer("❌ Расписание репетиций не загружено.")
        return
    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        photo_id = f.read().strip()
    if not photo_id:
        await message.answer("❌ Расписание репетиций не загружено.")
        return
    try:
        await message.bot.send_photo(
            message.from_user.id, 
            photo=photo_id, 
            caption="📅 <b>Расписание репетиций</b>", 
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Ошибка расписания: {e}")
        await message.answer("❌ Не удалось загрузить расписание.")


@user_router.message(F.text == "📌 Замены")
async def show_schedule2(message: Message):
    if not os.path.exists(SCHEDULE2_FILE):
        await message.answer("❌ Изменения в расписании не загружены.")
        return
    with open(SCHEDULE2_FILE, "r", encoding="utf-8") as f:
        photo_id = f.read().strip()
    if not photo_id:
        await message.answer("❌ Изменения в расписании не загружены.")
        return
    try:
        await message.bot.send_photo(message.from_user.id, photo=photo_id, caption="📅 <b>Изменения в расписании</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка расписания изменений: {e}")
        await message.answer("❌ Не удалось загрузить изменения в расписании.")


@user_router.message(F.text == "📋 Команды")
async def show_commands(message: Message):
    await message.answer(
        "📋 <b>Команды бота</b>\n\n"
        "⚙️ <b>Основное</b>\n"
        "• <code>/start</code> — перезапустить бота и вызвать меню.\n"
        "• <b>Кнопки внизу</b> — расписание, замены, команды.\n\n"
        "🎂 <b>Дни рождения (поздравляем вас в канале)</b>\n"
        "• <code>!др ДД.ММ</code> — сохранить свой ДР (например, <code>!др 07.05</code>).\n"
        "• <code>!мой_др</code> — посмотреть сохранённый ДР.\n"
        "• <code>!удалить_др</code> — удалить свой ДР.\n\n"
        "📊 <b>Опросы</b>\n"
        "• <code>!опрос</code> — предложить опрос (уйдёт на модерацию).\n"
        "  <i>Отправь команду с новой строки, затем вопрос и варианты с маркером <code>-</code>, <code>•</code> или <code>*</code>.</i>\n"
        "• <code>!мои_опросы</code> — статус твоих опросов.\n\n"
        "📅 <b>События</b>\n"
        "• <code>!события</code> — список ближайших событий и напоминаний.\n\n"
        "🏅 <b>Конкурс (если в данный момент идет)</b>\n"
        "• <code>!конкурс (в описании к фотографии)</code> — отправить свою фотографию на конкурс аватарок канала или бота.\n\n"
        "👤 <b>Неанонимный пост</b>\n"
        "• <code>!неанон [текст]</code> — отправить пост с указанием вашего имени.\n\n"
        "💬 <b>Анонимные ответы</b>\n"
        "Под каждым постом в канале есть кнопка <b>«Ответить»</b>. Нажми, чтобы написать анонимный ответ (можно с фото или стикерами).\n\n"
        "⚠️ <i>Соблюдай правила приличия и не спамь.</i>",
        parse_mode=ParseMode.HTML
    )


@user_router.message(F.text == "🛠 Админ-панель")
async def open_admin_panel_kb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    from handlers.admin import admin_panel
    await admin_panel(message)


@user_router.message(F.text == "🛡 Модер-панель")
async def open_moder_panel_kb(message: Message):
    if message.from_user.id not in STAFF_IDS:
        return
    from handlers.admin import moderator_panel
    await moderator_panel(message)


@user_router.callback_query(F.data == "reply_to_post")
async def ask_for_reply(callback: CallbackQuery):
    async with active_replies_lock:
        active_replies[callback.from_user.id] = callback.message.message_id
    mark_replies_dirty()
    try:
        await callback.answer(url=f"https://t.me/PodslushanoNGHU_bot?start=reply")
    except Exception:
        await callback.answer("Открой бота в личных сообщениях!", show_alert=True)


@user_router.message(F.content_type.in_([
    ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO, ContentType.AUDIO,
    ContentType.DOCUMENT, ContentType.VOICE, ContentType.VIDEO_NOTE, ContentType.STICKER,
    ContentType.CONTACT, ContentType.LOCATION
]))
async def handle_all_messages(message: Message):
    if message.chat.type != "private": return

    user = message.from_user
    text = message.text or message.caption or ""
    now = datetime.now(ZoneInfo("Asia/Novosibirsk")).strftime("%d.%m.%Y %H:%M:%S")

    # --- ПРОВЕРКА НА НЕАНОНИМНОЕ СООБЩЕНИЕ ---
    is_signed = False
    # ВАЖНО: Сначала проверяем длинное слово "!неаноним", чтобы оно не перехватывалось коротким "!неанон"
    if text.lower().startswith("!неаноним"):
        is_signed = True
        text = text[len("!неаноним"):].strip()
    elif text.lower().startswith("!неанон"):
        is_signed = True
        text = text[len("!неанон"):].strip()

    # Проверка на пустоту после команды !неанон
    if is_signed and not text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
        await message.answer(
            "❌ Вы написали команду <code>!неанон</code>, но не прикрепили ни текста, ни медиа.\n"
            "Напишите текст после команды (например: <code>!неанон Привет</code>) или прикрепите фото с этой командой в подписи.",
            parse_mode=ParseMode.HTML
        )
        return

    # Админские !команды не публикуем в канал (но разрешаем !неанон)
    if user.id in ADMIN_IDS and text.startswith("!") and not is_signed:
        return

    await save_user(user.id)
    await save_username(user.username, user.id)

    mute_remaining = await check_mute(user.id)
    if mute_remaining is not None:
        minutes = mute_remaining // 60
        await message.answer(f"⛔ Вы временно не можете отправлять сообщения. Осталось: <b>{minutes} мин.</b>", parse_mode=ParseMode.HTML)
        return

    # Проверяем и атомарно забираем original_msg_id из active_replies
    async with active_replies_lock:
        original_msg_id = active_replies.pop(user.id, None)
    if original_msg_id is not None:
        mark_replies_dirty()

        base_caption = esc(text) if text else ""
        if is_signed:
            base_caption += await get_signed_signature(user)
            reply_caption = base_caption + "📬 @PodslushanoNGHU_bot"
        else:
            reply_caption = (base_caption + "\n\n📬 @PodslushanoNGHU_bot") if base_caption else "📬 @PodslushanoNGHU_bot"

        answer_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data="reply_to_post"), InlineKeyboardButton(text="📩 Новое сообщение", url="https://t.me/PodslushanoNGHU_bot?start=new")]])

        try:
            sent_reply = await _send_media_with_caption(message.bot, CHANNEL_ID, message, caption=reply_caption, parse_mode=ParseMode.HTML, reply_to_message_id=original_msg_id)
            await asyncio.sleep(1.5)
            try: await message.bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=sent_reply.message_id, reply_markup=answer_kb)
            except Exception as e: logging.error(f"Кнопка к ответу: {e}")

            chat_id_str = str(CHANNEL_ID).replace("-100", "")
            reply_link = f"https://t.me/c/{chat_id_str}/{sent_reply.message_id}"

            log_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Перейти", url=reply_link)], [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_msg_{sent_reply.message_id}")], [InlineKeyboardButton(text="⚠️ Мут", callback_data=f"mute_menu_{user.id}")]])
            
            sign_mark = " 👤" if is_signed else ""
            log_text = f"💬 <b>Ответ</b>{sign_mark}\n👤 <b>Автор:</b> {esc(user.full_name)}\n🔗 Username: @{esc(user.username) if user.username else 'нет'}\n🆔 ID: <code>{user.id}</code>\n🕒 Время: {now}\n📝 <b>Текст/Подпись:</b> {esc(text)}"

            # Лог ответа — реплай на лог исходного сообщения (если известен)
            reply_to_log_id = await get_log_msg_id(original_msg_id)
            try:
                log_msg = await message.bot.send_message(
                    LOG_CHAT_ID, log_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=log_kb,
                    reply_to_message_id=reply_to_log_id
                )
                # Связываем новый ответ в канале с его лог-сообщением
                await save_log_msg_id(sent_reply.message_id, log_msg.message_id)
            except Exception as e:
                logging.error(f"Лог ответа: {e}")

            await log_message_db(user.id, now, "reply", text)

            channel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Перейти к сообщению", url=reply_link)]])
            await message.answer("✅ Твой ответ опубликован в канале!", reply_markup=channel_kb)
        except Exception as e:
            logging.error(f"Ошибка ответа: {e}")
            await message.answer("❌ Не удалось отправить ответ. Возможно, пост удален.")
        finally:
            async with active_replies_lock:
                active_replies.pop(user.id, None)
            mark_replies_dirty()
        return

    # Публикация в канал
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data="reply_to_post"), InlineKeyboardButton(text="📩 Новое сообщение", url="https://t.me/PodslushanoNGHU_bot?start=new")]])
    
    base_caption = esc(text) if text else ""
    if is_signed:
        base_caption += await get_signed_signature(user)
        caption_out = base_caption + "📬 @PodslushanoNGHU_bot"
    else:
        caption_out = (base_caption + "\n\n📬 @PodslushanoNGHU_bot") if base_caption else "📬 @PodslushanoNGHU_bot"

    try:
        sent_msg = await _send_media_with_caption(message.bot, CHANNEL_ID, message, caption=caption_out, parse_mode=ParseMode.HTML)
        await asyncio.sleep(1.5)
        try: await message.bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=sent_msg.message_id, reply_markup=reply_kb)
        except Exception as e: logging.error(f"Кнопка к посту: {e}")
    except Exception as e:
        logging.error(f"Ошибка канала: {e}")
        await message.answer("❌ Ошибка отправки в канал.")
        return

    chat_id_str = str(CHANNEL_ID).replace("-100", "")
    msg_link = f"https://t.me/c/{chat_id_str}/{sent_msg.message_id}"
    log_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Перейти к сообщению", url=msg_link)], [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_msg_{sent_msg.message_id}")], [InlineKeyboardButton(text="⚠️ Мут", callback_data=f"mute_menu_{user.id}")]])

    username = f"@{user.username}" if user.username else "нет username"
    sign_mark = " 👤" if is_signed else ""
    log_text = f"👤 <b>Автор:</b> {esc(user.full_name)}{sign_mark}\n🔗 Username: {esc(username)}\n🆔 ID: <code>{user.id}</code>\n🕒 Время: {now}\n💬 <b>Тип:</b> {message.content_type}\n📝 <b>Текст/Подпись:</b> {esc(text)}"

    # Новый пост — лог без реплая, но сохраняем связь для будущих ответов
    try:
        log_msg = await message.bot.send_message(LOG_CHAT_ID, log_text, parse_mode=ParseMode.HTML, reply_markup=log_kb)
        await save_log_msg_id(sent_msg.message_id, log_msg.message_id)
    except Exception as e:
        logging.error(f"Лог чат: {e}")

    await log_message_db(user.id, now, message.content_type, text)

    channel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Перейти к сообщению", url=msg_link)]])
    answer_text = "✅ Неанонимное сообщение отправлено в канал." if is_signed else "✅ Сообщение отправлено в канал анонимно."
    await message.answer(answer_text, reply_markup=channel_kb)


@user_router.message()
async def handle_other_messages(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return
    await save_user(message.from_user.id)
    await save_username(message.from_user.username, message.from_user.id)
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио, стикеры или геолокацию.")
