# plugins/birthdays.py
"""
Плагин «Дни рождения».
Команды:
  !др ДД.ММ — сохранить свой ДР (все)
  !мой_др — показать свой ДР (все)
  !удалить_др — удалить свой ДР (все)
  !др_сегодня — кто празднует сегодня (админ, модер)
  !др_список — все ДР (админ, модер)
  !др_добавить ID ДД.ММ — добавить/изменить ДР пользователя (админ, модер)
  !др_удалить ID — удалить ДР пользователя (только админ)
  !др_поиск ДД.ММ (или ММ) — поиск по дате/месяцу (админ, модер)
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ParseMode

from config import CHANNEL_ID, ADMIN_IDS, MODERATOR_IDS, DATA_DIR
from services.media import esc

PLUGIN_INFO = {
    "name": "Дни рождения",
    "description": "Сохранение ДР и автопоздравление в канал",
    "commands": [
        ("!др ДД.ММ", "сохранить свой ДР (все)"),
        ("!мой_др", "показать свой ДР (все)"),
        ("!удалить_др", "удалить свой ДР (все)"),
        ("!др_сегодня", "кто празднует сегодня (админ, модер)"),
        ("!др_список", "все ДР (админ, модер)"),
        ("!др_добавить ID ДД.ММ", "добавить/изменить ДР (админ, модер)"),
        ("!др_удалить ID", "удалить ДР пользователя (админ)"),
        ("!др_поиск ДД.ММ", "поиск по дате/месяцу (админ, модер)"),
    ],
}

router = Router(name="birthdays")

BIRTHDAYS_FILE = os.path.join(DATA_DIR, "birthdays.json")
PUBLISHED_FILE = os.path.join(DATA_DIR, "birthdays_published.json")
os.makedirs(DATA_DIR, exist_ok=True)

birthdays = {}         # {"user_id": "ДД.ММ"}
published_today = set()  # {"ДД.ММ.ГГГГ", ...} — даты, когда уже поздравляли
bday_lock = asyncio.Lock()


def load_birthdays():
    global birthdays, published_today
    if os.path.exists(BIRTHDAYS_FILE):
        try:
            with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
                birthdays = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки birthdays.json: {e}")
            birthdays = {}
    if os.path.exists(PUBLISHED_FILE):
        try:
            with open(PUBLISHED_FILE, "r", encoding="utf-8") as f:
                published_today = set(json.load(f))
        except Exception as e:
            logging.error(f"Ошибка загрузки birthdays_published.json: {e}")
            published_today = set()


async def save_birthdays():
    async with bday_lock:
        try:
            tmp = BIRTHDAYS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(birthdays, f, ensure_ascii=False)
            os.replace(tmp, BIRTHDAYS_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения birthdays.json: {e}")


async def save_published():
    async with bday_lock:
        try:
            tmp = PUBLISHED_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sorted(published_today), f, ensure_ascii=False)
            os.replace(tmp, PUBLISHED_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения birthdays_published.json: {e}")


load_birthdays()


def parse_dm(text: str):
    """Парсит 'ДД.ММ' или 'ДД.ММ.ГГГГ'. Возвращает 'ДД.ММ' или None."""
    text = text.strip().replace("-", ".").replace("/", ".")
    parts = text.split(".")
    if len(parts) < 2:
        return None
    try:
        d, m = int(parts[0]), int(parts[1])
        if not (1 <= d <= 31 and 1 <= m <= 12):
            return None
        return f"{d:02d}.{m:02d}"
    except ValueError:
        return None


def _display_name(chat) -> str:
    """Имя + (@username), с экранированием."""
    name = esc(chat.full_name or "участник")
    if getattr(chat, "username", None):
        name += f" (@{esc(chat.username)})"
    return name


# ==============================================================================
# ================= АДМИНСКИЕ / МОДЕРАТОРСКИЕ =================================
# ==============================================================================

@router.message(F.text.lower().startswith("!др_сегодня"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def bday_today(message: Message):
    today = datetime.now(ZoneInfo("Asia/Novosibirsk")).strftime("%d.%m")
    people = [uid for uid, dm in birthdays.items() if dm == today]
    if not people:
        await message.answer(f"📅 Сегодня ({today}) ДР ни у кого нет.")
        return

    lines = [f"🎂 <b>Сегодня ({today}) ДР:</b>"]
    for uid in people:
        try:
            chat = await message.bot.get_chat(int(uid))
            name = _display_name(chat)
        except Exception:
            name = f"<code>{esc(uid)}</code>"
        lines.append(f"• {name}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower().startswith("!др_список"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def bday_list(message: Message):
    if not birthdays:
        await message.answer("ℹ️ Список ДР пуст.")
        return

    items = sorted(birthdays.items(), key=lambda x: (x[1][3:], x[1][:2]))  # по ММ, потом ДД
    lines = ["🎂 <b>Все ДР:</b>"]
    for uid, dm in items:
        try:
            chat = await message.bot.get_chat(int(uid))
            name = _display_name(chat)
        except Exception:
            name = f"<code>{esc(uid)}</code>"
        lines.append(f"• <b>{dm}</b> — {name}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower().startswith("!др_добавить"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def admin_add_birthday(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "❌ Формат: <code>!др_добавить ID ДД.ММ</code>\n"
            "Пример: <code>!др_добавить 123456789 15.03</code>",
            parse_mode=ParseMode.HTML
        )
        return

    target_id = parts[1]
    dm = parse_dm(parts[2])

    if not target_id.isdigit():
        await message.answer("❌ ID должен быть числом.")
        return
    if not dm:
        await message.answer("❌ Неверная дата. Формат: <code>ДД.ММ</code>", parse_mode=ParseMode.HTML)
        return

    birthdays[target_id] = dm
    await save_birthdays()
    
    try:
        chat = await message.bot.get_chat(int(target_id))
        name = chat.full_name or "Участник"
    except Exception:
        name = f"ID {target_id}"

    await message.answer(f"✅ ДР для <b>{esc(name)}</b> сохранен: <b>{dm}</b>", parse_mode=ParseMode.HTML)


@router.message(F.text.lower().startswith("!др_удалить"), F.from_user.id.in_(ADMIN_IDS))
async def admin_del_birthday(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: <code>!др_удалить ID</code>", parse_mode=ParseMode.HTML)
        return

    target_id = parts[1]
    if target_id in birthdays:
        birthdays.pop(target_id, None)
        await save_birthdays()
        await message.answer(f"✅ ДР пользователя <code>{target_id}</code> удален.", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"⚠️ Пользователь <code>{target_id}</code> не найден в базе ДР.", parse_mode=ParseMode.HTML)


@router.message(F.text.lower().startswith("!др_поиск"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def admin_find_birthday(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Формат: <code>!др_поиск ММ</code> (месяц) или <code>!др_поиск ДД.ММ</code> (конкретный день)",
            parse_mode=ParseMode.HTML
        )
        return

    query = parts[1]
    found = []
    
    for uid, dm in birthdays.items():
        if dm.endswith(query) or dm == query:
            found.append((uid, dm))

    if not found:
        await message.answer(f"📅 По запросу <b>{query}</b> никого не найдено.", parse_mode=ParseMode.HTML)
        return

    lines = [f"🎂 <b>Результаты поиска ({query}):</b>"]
    for uid, dm in sorted(found, key=lambda x: x[1]):
        try:
            chat = await message.bot.get_chat(int(uid))
            name = chat.full_name or "Участник"
            username = f" (@{chat.username})" if chat.username else ""
            lines.append(f"• <b>{dm}</b> — {esc(name)}{esc(username)} (<code>{uid}</code>)")
        except Exception:
            lines.append(f"• <b>{dm}</b> — ID: <code>{uid}</code>")
            
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ==============================================================================
# ================= ПОЛЬЗОВАТЕЛЬСКИЕ ==========================================
# ==============================================================================

@router.message(F.text.lower().regexp(r"^!др\s+\d"), F.chat.type == "private")
async def set_birthday(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❌ Формат: <code>!др ДД.ММ</code>\nПример: <code>!др 15.03</code>",
            parse_mode=ParseMode.HTML
        )
        return

    dm = parse_dm(parts[1])
    if not dm:
        await message.answer(
            "❌ Неверная дата. Формат: <code>ДД.ММ</code>, например <code>15.03</code>",
            parse_mode=ParseMode.HTML
        )
        return

    birthdays[str(message.from_user.id)] = dm
    await save_birthdays()
    await message.answer(f"🎂 Твой день рождения сохранён: <b>{dm}</b>", parse_mode=ParseMode.HTML)


@router.message(F.text.lower() == "!мой_др", F.chat.type == "private")
async def my_birthday(message: Message):
    uid = str(message.from_user.id)
    if uid in birthdays:
        await message.answer(f"🎂 Твой ДР: <b>{birthdays[uid]}</b>", parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            "ℹ️ Ты ещё не указал ДР. Напиши: <code>!др ДД.ММ</code>",
            parse_mode=ParseMode.HTML
        )


@router.message(F.text.lower() == "!удалить_др", F.chat.type == "private")
async def del_birthday(message: Message):
    uid = str(message.from_user.id)
    if uid in birthdays:
        birthdays.pop(uid, None)
        await save_birthdays()
        await message.answer("✅ Твой ДР удалён.")
    else:
        await message.answer("ℹ️ У тебя не сохранён ДР.")


# ==============================================================================
# ================= АВТОПОЗДРАВЛЕНИЕ (вызывается из scheduler) =================
# ==============================================================================

async def auto_congratulate(bot):
    """Проверяет, у кого сегодня ДР, и публикует в канал (1 раз в день)."""
    global published_today
    now = datetime.now(ZoneInfo("Asia/Novosibirsk"))
    today_dm = now.strftime("%d.%m")
    today_full = now.strftime("%d.%m.%Y")

    if today_full in published_today:
        return

    people = [uid for uid, dm in birthdays.items() if dm == today_dm]
    if not people:
        published_today.add(today_full)
        await save_published()
        return

    lines = ["🎉 <b>С ДНЁМ РОЖДЕНИЯ!</b>\n"]
    lines.append("Сегодня свой день рождения празднует:")
    for uid in people:
        try:
            chat = await bot.get_chat(int(uid))
            name = _display_name(chat)
        except Exception:
            name = "участник"
        lines.append(f"🎂 <b>{name}</b>")
    lines.append("\n💐 От всей души поздравляем! Здоровья, удачи и творческих успехов!")

    try:
        await bot.send_message(CHANNEL_ID, "\n".join(lines), parse_mode=ParseMode.HTML)
        published_today.add(today_full)
        await save_published()
        logging.info(f"Поздравление опубликовано ({today_dm}, {len(people)} чел.)")
    except Exception as e:
        logging.error(f"Ошибка публикации поздравления: {e}")
