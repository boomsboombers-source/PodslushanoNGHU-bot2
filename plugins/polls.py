# plugins/polls.py
"""
Плагин «Опросы от пользователей».

Формат создания (многострочный):
  !опрос
  Вопрос: Какой фильм лучше?
  -Интерстеллар
  •Начало
  * Матрица

Команды:
  !опрос — предложить опрос (все, с превью и модерацией)
  !мои_опросы — список своих опросов (все)
  !опросы — список активных опросов (админ)
"""

import os
import json
import logging
import asyncio
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from config import CHANNEL_ID, LOG_CHAT_ID, ADMIN_IDS, DATA_DIR

PLUGIN_INFO = {
    "name": "Опросы от пользователей",
    "icon": "📊",
    "description": "Пользователи предлагают опросы, админ модерирует, бот публикует в канал",
    "commands": [
        ("!опрос", "предложить опрос (все)"),
        ("!мои_опросы", "список своих опросов (все)"),
        ("!опросы", "список активных опросов (админ)"),
    ],
    "commands_moder": [],
}

router = Router(name="polls")

POLLS_FILE = os.path.join(DATA_DIR, "polls.json")
os.makedirs(DATA_DIR, exist_ok=True)

polls = {}  # {"poll_id": {...}}
polls_lock = asyncio.Lock()
_poll_counter = 0

# Черновики: {user_id: {"question": str, "options": [...]}}
pending_polls = {}

_VARIANT_MARKERS = ("-", "•", "*")


def load_polls():
    global polls, _poll_counter
    if os.path.exists(POLLS_FILE):
        try:
            with open(POLLS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                polls = data.get("polls", {})
                _poll_counter = data.get("counter", 0)
        except Exception as e:
            logging.error(f"Ошибка загрузки polls.json: {e}")


async def save_polls():
    async with polls_lock:
        try:
            tmp = POLLS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"polls": polls, "counter": _poll_counter}, f, ensure_ascii=False)
            os.replace(tmp, POLLS_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения polls.json: {e}")


load_polls()


def parse_poll_multiline(body: str):
    """
    body — текст после '!опрос'.
    Возвращает (question, options) или None.
    """
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if len(lines) < 3:
        return None

    question = lines[0].strip()
    if question.lower().startswith("вопрос:"):
        question = question[len("вопрос:"):].strip()
    if not question or len(question) > 255:
        return None

    options = []
    for ln in lines[1:]:
        s = ln.strip()
        if not s:
            continue
        if s[0] not in _VARIANT_MARKERS:
            continue  # строки без маркера игнорируем
        opt = s[1:].strip()
        if not opt:
            continue
        if len(opt) > 100:
            return None
        options.append(opt)

    if len(options) < 2 or len(options) > 10:
        return None
    return question, options


@router.message(F.text.lower() == "!опросы", F.from_user.id.in_(ADMIN_IDS))
async def list_polls(message: Message):
    if not polls:
        await message.answer("ℹ️ Опросов нет.")
        return
    status_map = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    lines = ["📊 <b>Все опросы:</b>"]
    for pid, p in polls.items():
        st = status_map.get(p.get("status"), "?")
        lines.append(f"{st} <code>{pid}</code> — {p.get('question')}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower() == "!опрос", F.chat.type == "private")
async def suggest_poll(message: Message):
    await message.answer(
        "📊 <b>Создание опроса</b>\n\n"
        "Отправь команду и данные так:\n\n"
        "<code>!опрос\n"
        "Вопрос: Какой фильм лучше?\n"
        "-Интерстеллар\n"
        "-Начало\n"
        "-Матрица</code>\n\n"
        "• <code>Вопрос:</code> — необязательно\n"
        "• Варианты — с маркером <code>-</code>, <code>•</code> или <code>*</code>\n"
        "• От 2 до 10 вариантов\n"
        "• Вопрос до 255 символов, вариант до 100",
        parse_mode=ParseMode.HTML
    )


@router.message(F.text.lower().startswith("!опрос\n"), F.chat.type == "private")
async def suggest_poll_multiline(message: Message):
    body = message.text[len("!опрос"):]
    parsed = parse_poll_multiline(body)
    if not parsed:
        await message.answer(
            "❌ Не удалось разобрать опрос.\n"
            "Формат: <code>!опрос</code> с новой строки, затем вопрос и варианты с <code>-</code>/<code>•</code>/<code>*</code>.\n"
            "От 2 до 10 вариантов.",
            parse_mode=ParseMode.HTML
        )
        return

    question, options = parsed
    pending_polls[message.from_user.id] = {"question": question, "options": options}

    preview_lines = [f"❓ <b>{question}</b>"]
    for i, o in enumerate(options, 1):
        preview_lines.append(f"{i}. {o}")
    preview = "📊 <b>Проверь свой опрос:</b>\n\n" + "\n".join(preview_lines) + "\n\nОтправить на модерацию?"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data=f"poll_confirm_{message.from_user.id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"poll_cancel_{message.from_user.id}")],
    ])
    await message.answer(preview, parse_mode=ParseMode.HTML, reply_markup=kb)


@router.callback_query(F.data.startswith("poll_confirm_"))
async def confirm_poll(callback: CallbackQuery):
    global _poll_counter
    uid = int(callback.data.replace("poll_confirm_", ""))
    if callback.from_user.id != uid:
        return await callback.answer("⛔ Это не твой опрос", show_alert=True)

    draft = pending_polls.pop(uid, None)
    if not draft:
        return await callback.answer("⚠️ Черновик уже обработан", show_alert=True)

    _poll_counter += 1
    poll_id = f"p{_poll_counter}"
    polls[poll_id] = {
        "author": str(uid),
        "question": draft["question"],
        "options": draft["options"],
        "status": "pending",
        "channel_msg_id": None,
        "created": datetime.now().isoformat(),
    }
    await save_polls()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"poll_approve_{poll_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"poll_reject_{poll_id}")],
    ])
    text = (
        f"📊 <b>Новый опрос на модерации</b>\n\n"
        f"👤 Автор: <code>{uid}</code>\n"
        f"❓ <b>{draft['question']}</b>\n\n" +
        "\n".join(f"• {o}" for o in draft["options"])
    )
    try:
        await callback.bot.send_message(LOG_CHAT_ID, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        logging.error(f"Не удалось отправить опрос на модерацию: {e}")

    try:
        await callback.message.edit_text(
            f"✅ Опрос отправлен на модерацию. ID: <code>{poll_id}</code>",
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest:
        pass
    await callback.answer("Отправлено")


@router.callback_query(F.data.startswith("poll_cancel_"))
async def cancel_poll(callback: CallbackQuery):
    uid = int(callback.data.replace("poll_cancel_", ""))
    if callback.from_user.id != uid:
        return await callback.answer("⛔ Это не твой опрос", show_alert=True)
    pending_polls.pop(uid, None)
    try:
        await callback.message.edit_text("❌ Отправка опроса отменена.")
    except TelegramBadRequest:
        pass
    await callback.answer("Отменено")


@router.message(F.text.lower() == "!мои_опросы", F.chat.type == "private")
async def my_polls(message: Message):
    uid = str(message.from_user.id)
    mine = [(pid, p) for pid, p in polls.items() if p.get("author") == uid]
    if not mine:
        await message.answer("ℹ️ У тебя нет опросов.")
        return
    status_map = {"pending": "⏳ На модерации", "approved": "✅ Опубликован", "rejected": "❌ Отклонён"}
    lines = ["📊 <b>Твои опросы:</b>"]
    for pid, p in mine:
        st = status_map.get(p.get("status"), p.get("status"))
        lines.append(f"• <code>{pid}</code> — {st} — {p.get('question')}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("poll_approve_"))
async def approve_poll(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа", show_alert=True)

    poll_id = callback.data.replace("poll_approve_", "")
    p = polls.get(poll_id)
    if not p:
        return await callback.answer("⚠️ Опрос не найден", show_alert=True)
    if p["status"] != "pending":
        return await callback.answer(f"⚠️ Уже обработан ({p['status']})", show_alert=True)

    try:
        sent = await callback.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=p["question"],
            options=p["options"],
            is_anonymous=True,
            allows_multiple_answers=False,
        )
        p["status"] = "approved"
        p["channel_msg_id"] = sent.message_id
        await save_polls()
        try:
            await callback.message.edit_text(
                f"✅ <b>Опрос опубликован</b>\n❓ {p['question']}\nID: <code>{poll_id}</code>",
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass
        await callback.answer("Опубликован")
    except Exception as e:
        logging.error(f"Ошибка публикации опроса: {e}")
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("poll_reject_"))
async def reject_poll(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа", show_alert=True)

    poll_id = callback.data.replace("poll_reject_", "")
    p = polls.get(poll_id)
    if not p:
        return await callback.answer("⚠️ Опрос не найден", show_alert=True)
    if p["status"] != "pending":
        return await callback.answer(f"⚠️ Уже обработан ({p['status']})", show_alert=True)

    p["status"] = "rejected"
    await save_polls()
    try:
        await callback.message.edit_text(
            f"❌ <b>Опрос отклонён</b>\n❓ {p['question']}\nID: <code>{poll_id}</code>",
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest:
        pass
    await callback.answer("Отклонён")
