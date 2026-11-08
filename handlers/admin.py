import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from config import (
    CHANNEL_ID, LOG_CHAT_ID, ADMIN_IDS, MODERATOR_IDS,
    SCHEDULE_FILE, SCHEDULE2_FILE, DELAYED_FILE, DATA_DIR
)
from services.storage import (
    cached_users, active_replies, mark_replies_dirty, save_user, save_username,
    serialize_message, delayed_posts, get_all_users, get_id_by_username,
    get_username_by_id, muted_users, active_replies_lock
)
from services.media import _send_media_with_caption, esc
from services.text import strip_command_prefix, strip_command_and_target
from services import plugin_registry
from services.database import get_user_info_db, get_top_users_db

admin_router = Router()

DB_PATH = os.path.join(DATA_DIR, "bot.db")

# ==============================================================================
# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================================
# ==============================================================================

async def _get_stats_from_db() -> tuple[int, int]:
    """Возвращает (всего сообщений, сообщений сегодня)."""
    today_str = datetime.now(ZoneInfo("Asia/Novosibirsk")).strftime("%d.%m.%Y")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM messages") as cur:
                total = (await cur.fetchone())[0]
            
            async with db.execute("SELECT COUNT(*) FROM messages WHERE date LIKE ?", (f"{today_str}%",)) as cur:
                today = (await cur.fetchone())[0]
        return total, today
    except Exception as e:
        logging.error(f"Ошибка чтения статистики из БД: {e}")
        return 0, 0

async def _build_stats_text(is_admin: bool = False) -> str:
    """Собирает текст статистики. Если is_admin=False, скрывает юзернеймы."""
    total_msgs, today_msgs = await _get_stats_from_db()

    muted_list = ""
    if muted_users:
        muted_list = "\n\n🔇 <b>Замученные:</b>\n"
        for uid, until_ts in muted_users.items():
            remaining = int(until_ts - datetime.now().timestamp())
            
            if is_admin:
                username = await get_username_by_id(uid)
                display_name = f"{username} (<code>{uid}</code>)"
            else:
                display_name = f"<code>{uid}</code>"
                
            if remaining > 0:
                minutes = remaining // 60
                muted_list += f"• {display_name} — {minutes} мин.\n"
            else:
                muted_list += f"• {display_name} — истек\n"
    else:
        muted_list = "\n\n🔇 <b>Замученных нет.</b>"

    return (
        f"📊 <b>Статистика:</b>\n"
        f"👥 Пользователей: <b>{len(cached_users)}</b>\n"
        f"💬 В ожидании: <b>{len(active_replies)}</b>\n"
        f"📨 Сообщений всего: <b>{total_msgs}</b>\n"
        f"📅 Сообщений сегодня: <b>{today_msgs}</b>"
        f"{muted_list}"
    )

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
        [InlineKeyboardButton(text="🔌 Плагины", callback_data="admin_plugins")],
        [InlineKeyboardButton(text="📚 Команды", callback_data="admin_settings")],
    ])
    await message.answer("🛠 <b>Админ-панель</b>\nВыбери действие:", reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data.startswith("admin_"))
async def admin_menu_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    if callback.message is None:
        return await callback.answer("Сообщение недоступно", show_alert=True)

    action = callback.data.replace("admin_", "")

    if action == "stats":
        text = await _build_stats_text(is_admin=True)
        await callback.message.answer(text, parse_mode=ParseMode.HTML)

    elif action == "clear_replies":
        active_replies.clear()
        mark_replies_dirty()
        await callback.message.answer("✅ Все ожидания ответов очищены.")

    elif action == "plugins":
        plugins = plugin_registry.get_all()
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ])
        if not plugins:
            await callback.message.answer(
                "🔌 <b>Плагины</b>\n\nПока не подключено ни одного плагина.\n"
                "Положите файл в папку <code>plugins/</code> и перезапустите бота.",
                parse_mode=ParseMode.HTML, reply_markup=back_kb
            )
        else:
            text = "🔌 <b>Подключённые плагины:</b>\n\n"
            for i, p in enumerate(plugins, 1):
                text += f"<b>{i}. {esc(p.get('name', 'Без названия'))}</b>\n"
                desc = p.get("description", "")
                if desc:
                    text += f"<i>{esc(desc)}</i>\n"
                cmds = p.get("commands", [])
                if cmds:
                    for cmd, cmd_desc in cmds:
                        text += f"• <code>{esc(cmd)}</code> — {esc(cmd_desc)}\n"
                else:
                    text += "• <i>команды не указаны</i>\n"
                text += "\n"
            await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)

    elif action == "back":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🧹 Очистить ответы", callback_data="admin_clear_replies")],
            [InlineKeyboardButton(text="🔌 Плагины", callback_data="admin_plugins")],
            [InlineKeyboardButton(text="📚 Команды", callback_data="admin_settings")],
        ])
        try:
            await callback.message.edit_text(
                "🛠 <b>Админ-панель</b>\nВыбери действие:",
                reply_markup=kb, parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "🛠 <b>Админ-панель</b>\nВыбери действие:",
                reply_markup=kb, parse_mode=ParseMode.HTML
            )

    elif action == "settings":
        await callback.message.answer(
            "📚 <b>Полная шпаргалка по командам</b>\n\n"
            "📅 <b>Расписание</b>\n"
            "• <code>!расписание</code> — <i>прикрепи фото расписания репетиций, в подписи напиши эту команду.</i>\n"
            "• <code>!замены</code> — <i>прикрепи фото замен, в подписи напиши эту команду.</i>\n\n"
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
            "• <code>!очистить_ответы</code> — сброс ожиданий.\n\n"
            "🕵️ <b>Аналитика (по базе данных)</b>\n"
            "• <code>!кто [ID|@username]</code> — узнать инфу о пользователе.\n"
            "• <code>!топ</code> — топ-10 самых активных.\n\n"
            "🔌 <b>Плагины</b>\n"
            "• Кнопка «🔌 Плагины» в админ-панели — список подключённых плагинов и их команд.",
            parse_mode=ParseMode.HTML
        )
    await callback.answer()

# ==============================================================================
# ================= АДМИНСКИЕ КОМАНДЫ (ТЕКСТОВЫЕ) ==============================
# ==============================================================================

@admin_router.message((F.text | F.caption).startswith("!расписание"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
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

@admin_router.message((F.text | F.caption).startswith("!замены"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def set_schedule2(message: Message):
    if not message.photo:
        await message.answer("❌ Пришлите команду вместе с картинкой замен.")
        return
    try:
        with open(SCHEDULE2_FILE, "w", encoding="utf-8") as f:
            f.write(message.photo[-1].file_id)
        await message.answer("✅ Замены обновлены!")
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения: {e}")

@admin_router.message(F.text.startswith("!статистика"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def admin_stats_text(message: Message):
    # Проверяем, админ это или модератор
    is_admin = message.from_user.id in ADMIN_IDS
    text = await _build_stats_text(is_admin=is_admin)
    await message.answer(text, parse_mode=ParseMode.HTML)

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
    async with active_replies_lock:
        reply_to = active_replies.pop(message.from_user.id, None)
    if reply_to is not None:
        mark_replies_dirty()
    admin_text = f"<b>⚠️ Сообщение от админа:</b>\n\n{esc(clean_text)}"
    async def _send(reply_id):
        if reply_id and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            return await message.bot.send_message(CHANNEL_ID, admin_text, parse_mode=ParseMode.HTML, reply_to_message_id=reply_id)
        else:
            return await _send_media_with_caption(message.bot, CHANNEL_ID, message, caption=admin_text, parse_mode=ParseMode.HTML, reply_to_message_id=reply_id)
    try:
        try:
            await _send(reply_to)
        except Exception as e:
            if "message to be replied not found" in str(e):
                await _send(None)
            else:
                raise e
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
        now_dt = datetime.now(ZoneInfo("Asia/Novosibirsk"))
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
        await message.answer(f"⏰ Пост будет опубликован в {target_dt.strftime('%H:%M')} (НСК).")
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
            target_id = await get_id_by_username(target.lstrip('@'))
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

@admin_router.message(F.text.lower().startswith("!кто"), F.from_user.id.in_(ADMIN_IDS))
async def admin_who_is(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: <code>!кто ID_или_@username</code>", parse_mode=ParseMode.HTML)
        return
    target = parts[1]
    target_id = None
    if target.startswith("@") or not target.isdigit():
        target_id = await get_id_by_username(target.lstrip("@"))
        if not target_id:
            await message.answer("❌ Пользователь с таким юзернеймом не найден в базе.")
            return
    else:
        target_id = int(target)
    info = await get_user_info_db(target_id)
    try:
        chat = await message.bot.get_chat(target_id)
        name = chat.full_name or "Неизвестно"
    except Exception:
        name = "Не удалось получить имя (не писал боту)"
    text = (
        f"🕵️ <b>Информация о пользователе</b>\n\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"👤 <b>Имя:</b> {esc(name)}\n"
        f"🔗 <b>Юзернейм:</b> {info['username']}\n"
        f"💬 <b>Сообщений в базе:</b> {info['messages']}\n"
        f"🔇 <b>В муте:</b> {'Да' if target_id in muted_users else 'Нет'}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@admin_router.message(F.text.lower() == "!топ", F.from_user.id.in_(ADMIN_IDS))
async def admin_top_users(message: Message):
    top = await get_top_users_db(limit=10)
    if not top:
        await message.answer("📊 В базе пока нет сообщений от пользователей.")
        return
    lines = ["🏆 <b>Топ-10 самых активных анонимщиков:</b>\n"]
    for i, item in enumerate(top, 1):
        uid = item["user_id"]
        count = item["count"]
        try:
            chat = await message.bot.get_chat(uid)
            name = chat.full_name or "Без имени"
        except Exception:
            name = "Скрытый профиль"
        lines.append(f"{i}. {esc(name)} (<code>{uid}</code>) — <b>{count}</b> сообщений")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ==============================================================================
# ================= МОДЕРАТОРСКИЕ КОМАНДЫ ======================================
# ==============================================================================

@admin_router.message(Command("moder", "модер"))
@admin_router.message(F.text.lower().in_(["!moder", "!модер"]))
async def moderator_panel(message: Message):
    if message.from_user.id not in MODERATOR_IDS and message.from_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Команды модератора", callback_data="moder_settings")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="moder_guide")], # <--- Новая кнопка
    ])
    await message.answer("🛠 <b>Панель модератора</b>\nВыбери действие:", reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_router.callback_query(F.data == "moder_settings")
async def moderator_settings(callback: CallbackQuery):
    if callback.from_user.id not in MODERATOR_IDS and callback.from_user.id not in ADMIN_IDS: return
    await callback.message.answer(
        "📚 <b>Команды модератора</b>\n\n"
        "📅 <b>Расписание</b>\n"
        "• <code>!расписание</code> — обновить фото расписания.\n"
        "• <code>!замены</code> — обновить фото замен.\n\n"
        "🛡 <b>Сообщение от модератора</b>\n"
        "• <code>!мдс [текст]</code> — опубликовать сообщение с пометкой «Сообщение от модератора».\n\n"
        "🎂 <b>Дни рождения</b>\n"
        "• <code>!др_добавить ID ДД.ММ</code> — добавить/изменить ДР.\n"
        "• <code>!др_сегодня</code> — кто празднует сегодня.\n"
        "• <code>!др_список</code> — все ДР.\n"
        "• <code>!др_поиск ДД.ММ</code> — поиск по дате/месяцу.",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@admin_router.callback_query(F.data == "moder_guide")
async def moderator_guide(callback: CallbackQuery):
    if callback.from_user.id not in MODERATOR_IDS and callback.from_user.id not in ADMIN_IDS: return
    
    await callback.message.answer(
        "📖 <b>Инструкция для модератора</b>\n\n"
        "Твоя задача — следить за порядком в канале и помогать пользователям, не раскрывая лишних данных. А так же обновлять расписание репетиций и замен!\n\n"
        
        "🔹 <b>Обновление расписания</b>\n"
        "Чтобы обновить расписание или замены, отправь боту <b>фотографию</b> (расписание или замены) и в поле <b>подписи к фото</b> напиши нужную команду:\n"
        "• <code>!расписание</code> — для основного расписания.\n"
        "• <code>!замены</code> — для изменений.\n\n"
        
        "🔹 <b>Как отвечать на посты</b>\n"
        "Ты можешь публиковать сообщения от лица модерации. Для этого нажми кнопку <b>«📩 Новое сообщение»</b> или <b>«💬 Ответить»</b> под нужным постом в канале, а затем в ЛС бота напиши:\n"
        "<code>!мдс Твой текст</code>\n"
        "Бот опубликует ответ с пометкой «🛡 Сообщение от модератора».\n\n"
        
        "🚫 <b>ВАЖНО:</b> Команду <code>!мдс</code> нельзя использовать для отправки обычных анонимных сообщений от своего лица! Для обычных постов и ответов пиши боту <b>без</b> этой команды (просто текст или фото), тогда они уйдут анонимно.\n\n"
        
        "🔹 <b>Жалобы и нарушения</b>\n"
        "Если видишь жесткое нарушение правил (спам, флуд стикерами и т.д), напиши администрации (@Nammely или @rudenkkov).\n\n"
        
        "🔹 <b>Дни рождения</b>\n"
        "Ты можешь добавлять и искать ДР пользователей. Список команд — в меню «📚 Команды модератора».\n\n"
        
        "⚠️ <i>Помни: от тебя много зависит, не заывай обновлять расписание. Будь вежлив и объективен.</i>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@admin_router.message((F.text | F.caption).startswith("!мдс"), F.from_user.id.in_(MODERATOR_IDS + ADMIN_IDS))
async def moderator_message(message: Message):
    source = message.text or message.caption or ""
    clean_text = strip_command_prefix(source, "!мдс")
    if not clean_text and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
        await message.answer("❌ Текст сообщения пуст.")
        return
    async with active_replies_lock:
        reply_to = active_replies.pop(message.from_user.id, None)
    if reply_to is not None:
        mark_replies_dirty()
    moder_text = f"<b>🛡 Сообщение от модератора:</b>\n\n{esc(clean_text)}"
    async def _send(reply_id):
        if reply_id and not message.photo and not message.video and not message.document and not message.audio and not message.voice and not message.video_note and not message.sticker:
            return await message.bot.send_message(CHANNEL_ID, moder_text, parse_mode=ParseMode.HTML, reply_to_message_id=reply_id)
        else:
            return await _send_media_with_caption(message.bot, CHANNEL_ID, message, caption=moder_text, parse_mode=ParseMode.HTML, reply_to_message_id=reply_id)
    try:
        try:
            await _send(reply_to)
        except Exception as e:
            if "message to be replied not found" in str(e):
                await _send(None)
            else:
                raise e
        await message.answer("✅ Сообщение от модератора опубликовано в канале.")
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")
