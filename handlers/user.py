import asyncio
import logging
import os
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode, ContentType
from config import CHANNEL_ID, LOG_CHAT_ID, WELCOME_IMAGE, SCHEDULE_FILE, SCHEDULE2_FILE, LOG_FILE, ADMIN_IDS
from services.storage import (
    save_user, save_username, active_replies, mark_replies_dirty, check_mute,
    active_replies_lock
)
from services.media import _send_media_with_caption, esc

user_router = Router()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание репетиций")],
            [KeyboardButton(text="📅 Замены")],
        ],
        resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Напиши сообщение для канала..."
    )

@user_router.message(CommandStart())
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
            parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка /start: {e}")
        await message.answer("👋 Привет! Бот работает.", reply_markup=get_main_keyboard())

@user_router.message(F.text == "📅 Расписание репетиций")
@user_router.message(Command("schedule"))
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
        await message.bot.send_photo(message.from_user.id, photo=photo_id, caption="📅 <b>Расписание репетиций</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Ошибка расписания: {e}")
        await message.answer("❌ Не удалось загрузить расписание.")

@user_router.message(F.text == "📅 Замены")
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
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    # Админские !команды не публикуем в канал (их уже обработал admin_router или они неизвестны)
    if user.id in ADMIN_IDS and text.startswith("!"):
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

        reply_caption = f"{esc(text)}\n\n📬 @PodslushanoNGHU_bot" if text else "📬 @PodslushanoNGHU_bot"
        answer_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data="reply_to_post"), InlineKeyboardButton(text="📩 Новое сообщение", url="https://t.me/PodslushanoNGHU_bot?start=new")]])

        try:
            sent_reply = await _send_media_with_caption(message.bot, CHANNEL_ID, message, caption=reply_caption, parse_mode=ParseMode.HTML, reply_to_message_id=original_msg_id)
            await asyncio.sleep(1.5)
            try: await message.bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=sent_reply.message_id, reply_markup=answer_kb)
            except Exception as e: logging.error(f"Кнопка к ответу: {e}")

            chat_id_str = str(CHANNEL_ID).replace("-100", "")
            reply_link = f"https://t.me/c/{chat_id_str}/{sent_reply.message_id}"

            log_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Перейти", url=reply_link)], [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_msg_{sent_reply.message_id}")], [InlineKeyboardButton(text="⚠️ Мут", callback_data=f"mute_menu_{user.id}")]])
            log_text = f"💬 <b>Ответ</b>\n👤 <b>Автор:</b> {esc(user.full_name)}\n🔗 Username: @{esc(user.username) if user.username else 'нет'}\n🆔 ID: <code>{user.id}</code>\n🕒 Время: {now}\n📝 <b>Текст/Подпись:</b> {esc(text)}"
            await message.bot.send_message(LOG_CHAT_ID, log_text, parse_mode=ParseMode.HTML, reply_markup=log_kb)

            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{now}] {user.full_name} ({user.username}, ID: {user.id}) - ОТВЕТ\n")
                f.write(f"Текст: {text}\n" + "-" * 40 + "\n")

            channel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Перейти к сообщению", url=reply_link)]])
            await message.answer("✅ Твой анонимный ответ опубликован в канале!", reply_markup=channel_kb)
        except Exception as e:
            logging.error(f"Ошибка ответа: {e}")
            await message.answer("❌ Не удалось отправить ответ. Возможно, пост удален.")
        finally:
            async with active_replies_lock:
                active_replies.pop(user.id, None)
            mark_replies_dirty()
        return

    # Публикация в канал
    signature = "\n\n📬 @PodslushanoNGHU_bot"
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data="reply_to_post"), InlineKeyboardButton(text="📩 Новое сообщение", url="https://t.me/PodslushanoNGHU_bot?start=new")]])
    caption_out = (esc(text) + signature) if text else ""

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
    log_text = f"👤 <b>Автор:</b> {esc(user.full_name)}\n🔗 Username: {esc(username)}\n🆔 ID: <code>{user.id}</code>\n🕒 Время: {now}\n💬 <b>Тип:</b> {message.content_type}\n📝 <b>Текст/Подпись:</b> {esc(text)}"

    try: await message.bot.send_message(LOG_CHAT_ID, log_text, parse_mode=ParseMode.HTML, reply_markup=log_kb)
    except Exception as e: logging.error(f"Лог чат: {e}")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {user.full_name} ({username}, ID: {user.id})\n")
        f.write(f"Тип: {message.content_type}. Текст: {text}\n" + "-" * 40 + "\n")

    channel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📢 Перейти к сообщению", url=msg_link)]])
    await message.answer("✅ Сообщение отправлено в канал анонимно.", reply_markup=channel_kb)

@user_router.message()
async def handle_other_messages(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return
    await save_user(message.from_user.id)
    await save_username(message.from_user.username, message.from_user.id)
    await message.answer("⚠️ Пожалуйста, отправляй текст, фото, видео, аудио, стикеры или геолокацию.")
