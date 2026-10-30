import os
import json
import logging
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from config import CHANNEL_ID, LOG_CHAT_ID, ADMIN_IDS, LOG_FILE, SCHEDULE_FILE, SCHEDULE2_FILE, DELAYED_FILE
from services.storage import (
    cached_users, active_replies, mark_replies_dirty, save_user, save_username,
    serialize_message, delayed_posts, get_all_users, get_id_by_username,
    get_username_by_id, muted_users
)
from services.media import _send_media_with_caption, esc
from services.text import strip_command_prefix, strip_command_and_target

admin_router = Router()

# ==============================================================================
# ================= АДМИН-ПАНЕЛЬ ===============================================
# ==============================================================================

@admin_router.message(Command("admin", "админ"))
@admin_router.message(F.text.lower().in_(["!admin", "!админ"]))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🧹 Очистить ответы", callback_data="admin_clear_replies")],
        [InlineKeyboardButton(text="📚 Команды", callback_data="admin_settings")]
    ])
    await message.answer("🛠 <b>Админ-панель</b>\nВыбери действие:", reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_router.callback_query(F.data.startswith("admin_"))
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    if callback.message is None:
        return await callback.answer("Сообщение недоступно", show_alert=True)

    action = callback.data.replace("admin_", "")

    if action == "stats":
        total_msgs = 0
        today_msgs = 0
        today_str = datetime.now().strftime("%d.%m.%Y")

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("["):
                            total_msgs += 1
                            if line.startswith(f"[{today_str}"):
                                today_msgs += 1
            except Exception as e:
                logging.error(f"Ошибка чтения лог-файла: {e}")

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
            f"💬 В ожидании: <b>{len(active_replies)}</b>\n"
            f"📨 Сообщений всего: <b>{total_msgs}</b>\n"
            f"📅 Сообщений сегодня: <b>{today_msgs}</b>"
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
            "• <code>!расписание</code> — <i>прикрепи фото расписания репетиций, в подписи напиши эту команду.</i>\n"
            "• <code>!замены</code> — <i>то же для изменений в расписании.</i>\n\n"
            "📢 <b>Рассылка</b>\n"
            "• <code>!рассылка [текст]</code> — разошлет текст всем.\n"
            "• <code>!рассылка</code> + фото/видео — разошлет медиа.\n\n"
            "✉️ <b>Личное сообщение</b>\n"
            "• <code>!лс [ID|@username] [текст]</code> — отправит сообщение конкретному человеку.\n\n"
            "🤖 <b>Сообщение от админа</b>\n"
            "• <code>!адс [текст]</code> — опубликует сообщение с пометкой «Сообщение от админа».\n"
            "• Можно прикрепить фото/видео.\n"
            "• Работает как ответ на пост.\n\n"
            "⏰ <b>Отложенный пост</b>\n"
            "• <code>!отложка [ЧЧ:ММ] [текст]</code> — отложенная публикация.\n\n"
            "🔘 <b>Кнопка к старому посту</b>\n"
            "• <code>!кнопка [ID]</code> — добавит кнопки к старому посту.\n\n"
            "📊 <b>Статистика и очистка</b>\n"
            "• <code>!статистика</code> — общая статистика.\n"
            "• <code>!очистить_ответы</code> — сброс ожиданий.",
            parse_mode=ParseMode.HTML
        )
    await callback.answer()

# ==============================================================================
# ================= АДМИНСКИЕ КОМАНДЫ (ТЕКСТОВЫЕ) ==============================
# ==============================================================================

@admin_router.message((F.text | F.caption).startswith("!расписание"), F.from_user.id.in_(ADMIN_IDS))
async def set_schedule(message: Message):
    if not message.photo:
        await message.answer("❌ Пришлите команду вместе с картинкой расписания.")
        return
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            f.write(message.photo[-1].file_id)
        await message.answer("✅ Расписание успешно обновлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")

@admin_router.message((F.text | F.caption).startswith("!замены"), F.from_user.id.in_(ADMIN_IDS))
async def set_schedule2(message: Message):
    if not message.photo:
        await message.answer("❌ Пришлите команду вместе с картинкой изменений.")
        return
    try:
        with open(SCHEDULE2_FILE, "w", encoding="utf-8") as f:
            f.write(message.photo[-1].file_id)
        await message.answer("✅ Изменения в расписании обновлены!")
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")

@admin_router.message(F.text.startswith("!статистика"), F.from_user.id.in_(ADMIN_IDS))
async def admin_stats_text(message: Message):
    total_msgs = 0
    today_msgs = 0
    today_str = datetime.now().strftime("%d.%m.%Y")

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("["):
                        total_msgs += 1
                        if line.startswith(f"[{today_str}"):
                            today_msgs += 1
        except Exception as e:
            logging.error(f"Ошибка чтения лог-файла: {e}")

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

    await message.answer(
        f"📊 <b>Статистика:</b>\n"
        f"👥 Пользователей: <b>{len(cached_users)}</b>\n"
        f"💬 В ожидании: <b>{len(active_replies)}</b>\n"
        f"📨 Сообщений всего: <b>{total_msgs}</b>\n"
        f"📅 Сообщений сегодня: <b>{today_msgs}</b>"
        f"{muted_list}",
        parse_mode=ParseMode.HTML
    )

@admin_router.message(F.text.startswith("!очистить_ответы"), F.from_user.id.in_(ADMIN_IDS))
async def admin_clear_replies_text(message: Message):
    active_replies.clear()
    mark_replies_dirty()
    await message.answer("✅ Очищено.")

@admin_router.message((F.text | F.caption).startswith("!адс"), F.from_user.id.in_(ADMIN_IDS))
async def admin_message(message: Message):
    source = message.text or message.caption or ""
    clean_text = strip_command_prefix(source, "!адс")

    if not clean_text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
        await message.answer("❌ Текст сообщения пуст.")
        return

    admin_text = f"<b>Сообщение от админа:</b>\n\n\n{esc(clean_text)}"
    reply_to = message.reply_to_message.message_id if message.reply_to_message else None

    try:
        if reply_to and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            await message.bot.send_message(CHANNEL_ID, admin_text, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
        else:
            await _send_media_with_caption(message.bot, CHANNEL_ID, message, caption=admin_text, parse_mode=ParseMode.HTML, reply_to_message_id=reply_to)
        await message.answer("✅ Сообщение от админа опубликовано в канале.")
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")

@admin_router.message((F.text | F.caption).startswith("!отложка"), F.from_user.id.in_(ADMIN_IDS))
async def set_delayed(message: Message):
    source = message.text or message.caption or ""
    parts = source.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("❌ Формат: !отложка ЧЧ:ММ Текст")
        return
    try:
        h, m = map(int, parts[1].split(":"))
        now_dt = datetime.now()
        target_dt = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if target_dt < now_dt:
            target_dt += timedelta(days=1)

        post_data = serialize_message(message)
        clean_text = parts[2].strip()

        if not clean_text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            await message.answer("❌ Текст сообщения пуст.")
            return

        if message.caption:
            original_caption = message.caption.replace(f"!отложка {parts[1]}", "").strip()
            if original_caption and clean_text:
                post_data["text"] = f"{original_caption}\n\n{clean_text}"
            elif original_caption:
                post_data["text"] = original_caption
            else:
                post_data["text"] = clean_text
        else:
            post_data["text"] = clean_text

        if post_data["type"] in ("video_note", "sticker") and post_data["text"]:
            await message.answer("⚠️ У кружочков и стикеров нет подписи — текст не будет опубликован.")

        post_data["time"] = target_dt.timestamp()
        delayed_posts.append(post_data)
        with open(DELAYED_FILE, "w", encoding="utf-8") as f:
            json.dump(delayed_posts, f)

        await message.answer(f"⏰ Пост будет опубликован в {target_dt.strftime('%H:%M')}.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@admin_router.message((F.text | F.caption).startswith("!кнопка"), F.from_user.id.in_(ADMIN_IDS))
async def add_button(message: Message):
    if message.text is None:
        await message.answer("❌ Команда !кнопка работает только с текстом.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: !кнопка ID")
        return
    try:
        msg_id = int(parts[1])
        reply_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Ответить", callback_data="reply_to_post"), InlineKeyboardButton(text="📩 Новое сообщение", url="https://t.me/PodslushanoNGHU_bot?start=new")]
        ])
        await message.bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=msg_id, reply_markup=reply_kb)
        await message.answer(f"✅ Кнопки добавлены к {msg_id}.")
    except TelegramBadRequest as e:
        if "message can't be edited" in str(e):
            await message.answer("❌ Нельзя редактировать: сообщение принадлежит не боту или слишком старое.")
        else:
            await message.answer(f"❌ Ошибка: {e}")

@admin_router.message((F.text | F.caption).startswith("!рассылка"), F.from_user.id.in_(ADMIN_IDS))
async def broadcast(message: Message):
    source = message.text or message.caption or ""
    clean_text = strip_command_prefix(source, "!рассылка")

    if not clean_text and not message.photo and not message.video:
        await message.answer("❌ Текст пуст.")
        return

    users = get_all_users()
    await message.answer(f"🚀 Рассылка для {len(users)}...")
    success = 0
    for uid_str in users:
        try:
            await _send_media_with_caption(message.bot, int(uid_str), message, caption=clean_text, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.warning(f"Не отправлено {uid_str}: {e}")
    await message.answer(f"✅ Отправлено: {success} из {len(users)}.")

@admin_router.message((F.text | F.caption).startswith("!лс"), F.from_user.id.in_(ADMIN_IDS))
async def private_message(message: Message):
    source = message.text or message.caption or ""
    parts = source.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("❌ Формат: !лс ID|@username Текст")
        return
    target = parts[1]

    if message.caption:
        dm_text = strip_command_and_target(message.caption, "!лс", target)
    else:
        dm_text = parts[2] if len(parts) > 2 else ""

    if not dm_text.strip() and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
        await message.answer("❌ Текст сообщения пуст.")
        return

    try:
        if target.startswith("@") or not target.isdigit():
            target_id = get_id_by_username(target.lstrip('@'))
            if not target_id:
                chat = await message.bot.get_chat(target)
                target_id = chat.id
                await save_username(target, target_id)
        else:
            target_id = int(target)
    except Exception:
        await message.answer("❌ Пользователь не найден.")
        return

    try:
        await _send_media_with_caption(message.bot, target_id, message, caption=dm_text, parse_mode=ParseMode.HTML)
        await message.answer("✅ Отправлено.")
    except Exception:
        await message.answer("❌ Ошибка отправки.")
