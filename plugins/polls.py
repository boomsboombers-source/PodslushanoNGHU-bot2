# plugins/polls.py
"""
Плагин «Опросы от пользователей».
Команды:
  !опрос Вопрос | Вариант1 | Вариант2 | ... — предложить опрос (все, с модерацией)
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
    "description": "Пользователи предлагают опросы, админ модерирует, бот публикует в канал",
    "commands": [
        ("!опрос Вопрос | В1 | В2 | ...", "предложить опрос (все)"),
        ("!мои_опросы", "список своих опросов (все)"),
        ("!опросы", "список активных опросов (админ)"),
    ],
}

router = Router(name="polls")

POLLS_FILE = os.path.join(DATA_DIR, "polls.json")
os.makedirs(DATA_DIR, exist_ok=True)

polls = {}  # {"poll_id": {"author": str, "question": str, "options": [...], "status": "pending"|"approved"|"rejected", "channel_msg_id": int|None}}
polls_lock = asyncio.Lock()
_poll_counter = 0


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


def parse_poll(text: str):
    """'!опрос Вопрос | В1 | В2' -> (question, [options]) или None."""
    body = text[len("!опрос"):].strip()
    parts = [p.strip() for p in body.split("|")]
    if len(parts) < 3:
        return None
    question = parts[0]
    options = [p for p in parts[1:] if p]
    if len(options) < 2 or len(options) > 10:
        return None
    if len(question) > 255 or any(len(o) > 100 for o in options):
        return None
    return question, options


@router.message(F.text.lower().startswith("!опрос"), F.chat.type == "private")
async def suggest_poll(message: Message):
    global _poll_counter

    parsed = parse_poll(message.text)
    if not parsed:
        await message.answer(
            "❌ Формат: <code>!опрос Вопрос | Вариант1 | Вариант2</code>\n"
            "• от 2 до 10 вариантов\n"
            "• вопрос до 255 символов, вариант до 100",
            parse_mode=ParseMode.HTML
        )
        return

    question, options = parsed
    _poll_counter += 1
    poll_id = f"p{_poll_counter}"

    polls[poll_id] = {
        "author": str(message.from_user.id),
        "question": question,
        "options": options,
        "status": "pending",
        "channel_msg_id": None,
        "created": datetime.now().isoformat(),
    }
    await save_polls()

    # Отправляем в лог-группу на модерацию
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"poll_approve_{poll_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"poll_reject_{poll_id}")],
    ])
    text = (
        f"📊 <b>Новый опрос на модерации</b>\n\n"
        f"👤 Автор: <code>{message.from_user.id}</code>\n"
        f"❓ <b>{question}</b>\n\n" +
        "\n".join(f"• {o}" for o in options)
    )
    try:
        await message.bot.send_message(LOG_CHAT_ID, text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        logging.error(f"Не удалось отправить опрос на модерацию: {e}")

    await message.answer(f"✅ Опрос отправлен на модерацию. ID: <code>{poll_id}</code>", parse_mode=ParseMode.HTML)


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

    # Публикуем нативный опрос в канал
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