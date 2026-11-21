# plugins/santa.py
"""
Плагин «Тайный Санта».
Команды:
  !санта_старт ДД.ММ ЧЧ:ММ [| ДД.ММ ЧЧ:ММ] — запустить (админ)
  !санта_жеребьёвка — распределить пары (админ)
  !санта_участники — список участников (админ, модер)
  !санта_пары — кто кому выпал (админ)
  !санта_статус — статус конкурса (админ, модер)
  !санта_стоп — сброс (админ)
"""

import os
import json
import logging
import asyncio
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from config import CHANNEL_ID, ADMIN_IDS, MODERATOR_IDS, DATA_DIR

PLUGIN_INFO = {
    "name": "Тайный Санта",
    "icon": "🎅",
    "description": "Новогодняя игра: обмен подарками с анонимным Сантой",
    "commands": [
        ("!санта_старт ДД.ММ ЧЧ:ММ [| ДД.ММ ЧЧ:ММ]", "запустить приём заявок (админ)"),
        ("!санта_жеребьёвка", "распределить пары (админ)"),
        ("!санта_участники", "список участников (админ, модер)"),
        ("!санта_пары", "кто кому выпал (админ)"),
        ("!санта_статус", "статус игры (админ, модер)"),
        ("!санта_стоп", "сброс игры (админ)"),
    ],
    "commands_moder": [
        ("!санта_участники", "список участников (админ, модер)"),
        ("!санта_статус", "статус игры (админ, модер)"),
    ],
}

router = Router(name="santa")

SANTA_FILE = os.path.join(DATA_DIR, "santa.json")
NSK = ZoneInfo("Asia/Novosibirsk")
STAFF = ADMIN_IDS + MODERATOR_IDS

santa_data = {
    "active": False,
    "deadline": None,        # timestamp
    "gift_date": None,       # str или None (для отображения)
    "participants": {},      # {user_id_str: {"name": str, "username": str|None}}
    "pairs": {},             # {user_id_str: user_id_str}
}


def load_santa():
    global santa_data
    if os.path.exists(SANTA_FILE):
        try:
            with open(SANTA_FILE, "r", encoding="utf-8") as f:
                santa_data = json.load(f)
        except Exception as e:
            logging.error(f"Ошибка загрузки santa.json: {e}")


async def save_santa():
    try:
        tmp = SANTA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(santa_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SANTA_FILE)
    except Exception as e:
        logging.error(f"Ошибка сохранения santa.json: {e}")


load_santa()


def _parse_datetime(dt_str: str):
    """Парсит 'ДД.ММ ЧЧ:ММ' в timestamp (НСК)."""
    try:
        dt = datetime.strptime(f"{dt_str}.{datetime.now(NSK).year}", "%d.%m.%H:%M.%Y") if False else None
        # Более надёжно:
        parts = dt_str.split()
        if len(parts) != 2:
            return None
        date_part, time_part = parts
        dt = datetime.strptime(f"{date_part}.{datetime.now(NSK).year} {time_part}", "%d.%m.%Y %H:%M")
        dt = dt.replace(tzinfo=NSK)
        if dt < datetime.now(NSK):
            dt = dt.replace(year=dt.year + 1)
        return dt
    except Exception:
        return None


# ==============================================================================
# ================= КОМАНДЫ ====================================================
# ==============================================================================

@router.message(F.text.lower().startswith("!санта_старт"), F.from_user.id.in_(ADMIN_IDS))
async def santa_start(message: Message):
    if santa_data.get("active"):
        await message.answer("⚠️ Тайный Санта уже запущен! Сначала завершите или сбросьте (!санта_стоп).")
        return

    body = message.text[len("!санта_старт"):].strip()
    if not body:
        await message.answer(
            "❌ Формат: <code>!санта_старт ДД.ММ ЧЧ:ММ [| ДД.ММ ЧЧ:ММ]</code>\n"
            "Пример: <code>!санта_старт 20.12 23:59 | 25.12 12:00</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Разделяем по "|"
    parts = [p.strip() for p in body.split("|")]
    deadline_dt = _parse_datetime(parts[0])
    if not deadline_dt:
        await message.answer("❌ Не удалось разобрать дату дедлайна. Формат: <code>ДД.ММ ЧЧ:ММ</code>", parse_mode=ParseMode.HTML)
        return

    gift_date_str = None
    if len(parts) > 1 and parts[1]:
        gift_dt = _parse_datetime(parts[1])
        if not gift_dt:
            await message.answer("❌ Не удалось разобрать дату вручения. Формат: <code>ДД.ММ ЧЧ:ММ</code>", parse_mode=ParseMode.HTML)
            return
        gift_date_str = gift_dt.strftime("%d.%m в %H:%M")

    santa_data["active"] = True
    santa_data["deadline"] = deadline_dt.timestamp()
    santa_data["gift_date"] = gift_date_str
    santa_data["participants"] = {}
    santa_data["pairs"] = {}
    await save_santa()

    deadline_str = deadline_dt.strftime("%d.%m в %H:%M")

    gift_line = f"\n🎁 <b>Вручение подарков — {gift_date_str}.</b>" if gift_date_str else ""

    text = (
        "🎅 <b>Тайный Санта в «Подслушано НГХУ»!</b>\n\n"
        "Привет, ребята! Новый год уже на пороге, и мы решили устроить для вас небольшой сюрприз.\n\n"
        "🎁 <b>Как это работает?</b>\n"
        "1. Нажми кнопку <b>«Участвовать»</b> под этим постом.\n"
        "2. После окончания приёма заявок бот случайным образом распределит, кому ты будешь Сантой (а кто — твоим).\n"
        "3. Ты получишь имя и контакт своего подопечного в личные сообщения от бота. Сделай ему приятно к празднику — напиши тёплые слова, отправь анонимное пожелание или договорись о маленьком сюрпризе.\n"
        "4. <b>Тайна:</b> твой подопечный не узнает, что Санта — это ты, пока ты сам не решишь раскрыться!\n\n"
        "💰 <b>О подарках:</b>\n"
        "Пожалуйста, не делайте подарки слишком дорогими или слишком дешёвыми. Мы здесь не для того, чтобы соревноваться в бюджетах, а чтобы подарить друг другу немного новогоднего тепла. Маленький приятный сюрприз — то, что нужно! 🎄\n\n"
        f"⏳ <b>Приём заявок открыт до {deadline_str}.</b>{gift_line}\n\n"
        "⚠️ <i>Участвуй только если действительно готов сделать приятно другому человеку. Это не соревнование, а игра на атмосферу!</i>\n\n"
        "Жми кнопку ниже 👇"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Участвовать", callback_data="santa_join", style="success")]
    ])

    try:
        await message.bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        await message.answer("✅ Тайный Санта запущен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")


@router.callback_query(F.data == "santa_join")
async def santa_join(callback: CallbackQuery):
    if not santa_data.get("active"):
        await callback.answer("❌ Приём заявок уже завершён.", show_alert=True)
        return

    uid = str(callback.from_user.id)
    if uid in santa_data["participants"]:
        await callback.answer("✅ Ты уже участвуешь!", show_alert=True)
        return

    # Проверка дедлайна
    deadline = santa_data.get("deadline")
    if deadline and datetime.now(NSK).timestamp() > deadline:
        await callback.answer("⏳ Приём заявок уже завершён.", show_alert=True)
        return

    santa_data["participants"][uid] = {
        "name": callback.from_user.full_name,
        "username": callback.from_user.username,
    }
    await save_santa()
    await callback.answer("🎉 Ты в игре! Жди жеребьёвки.", show_alert=True)


@router.message(F.text.lower() == "!санта_жеребьёвка", F.from_user.id.in_(ADMIN_IDS))
async def santa_draw(message: Message):
    if not santa_data.get("active"):
        await message.answer("⚠️ Сначала запустите игру (!санта_старт).")
        return

    participants = list(santa_data["participants"].keys())
    if len(participants) < 2:
        await message.answer("⚠️ Нужно минимум 2 участника для жеребьёвки.")
        return

    random.shuffle(participants)
    pairs = {}
    for i, uid in enumerate(participants):
        pairs[uid] = participants[(i + 1) % len(participants)]

    santa_data["pairs"] = pairs
    santa_data["active"] = False  # приём закрыт
    await save_santa()

    success = 0
    fail = 0
    for uid_str, target_id in pairs.items():
        target = santa_data["participants"].get(target_id, {})
        target_name = target.get("name", "Участник")
        target_username = target.get("username")
        if target_username:
            target_contact = f"@{target_username}"
        else:
            target_contact = f'<a href="tg://user?id={target_id}">{target_name}</a>'

        text = (
            f"🎅 <b>Твой подопечный:</b> {target_contact}\n\n"
            f"Сделай ему приятно к Новому году! Не забудь сохранить тайну. 😉"
        )
        try:
            await message.bot.send_message(int(uid_str), text, parse_mode=ParseMode.HTML)
            success += 1
        except Exception as e:
            logging.warning(f"Не удалось отправить пару {uid_str}: {e}")
            fail += 1

    await message.answer(f"✅ Жеребьёвка завершена! Отправлено: {success}, ошибок: {fail}.")


@router.message(F.text.lower() == "!санта_участники", F.from_user.id.in_(STAFF))
async def santa_participants(message: Message):
    participants = santa_data.get("participants", {})
    if not participants:
        await message.answer("ℹ️ Пока никто не участвует.")
        return

    lines = [f"🎅 <b>Участники Тайного Санты ({len(participants)}):</b>"]
    for i, (uid, p) in enumerate(participants.items(), 1):
        uname = f"@{p['username']}" if p.get("username") else "без юзернейма"
        lines.append(f"{i}. {p['name']} ({uname})")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower() == "!санта_пары", F.from_user.id.in_(ADMIN_IDS))
async def santa_pairs(message: Message):
    pairs = santa_data.get("pairs", {})
    if not pairs:
        await message.answer("ℹ️ Жеребьёвка ещё не проведена.")
        return

    lines = ["🎅 <b>Пары Тайного Санты:</b>"]
    for uid, target_id in pairs.items():
        santa = santa_data["participants"].get(uid, {})
        target = santa_data["participants"].get(target_id, {})
        lines.append(f"{santa.get('name', uid)} → {target.get('name', target_id)}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower() == "!санта_статус", F.from_user.id.in_(STAFF))
async def santa_status(message: Message):
    if santa_data.get("active"):
        deadline = santa_data.get("deadline")
        deadline_str = datetime.fromtimestamp(deadline, NSK).strftime("%d.%m в %H:%M") if deadline else "не указан"
        state = f"🟢 Приём заявок (до {deadline_str})"
    elif santa_data.get("pairs"):
        state = "🟡 Жеребьёвка проведена"
    else:
        state = "⚪ Не запущен"

    lines = [
        f"🎅 <b>Статус Тайного Санты:</b> {state}",
        f"👥 Участников: <b>{len(santa_data.get('participants', {}))}</b>",
    ]
    if santa_data.get("gift_date"):
        lines.append(f"🎁 Вручение: {santa_data['gift_date']}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower() == "!санта_стоп", F.from_user.id.in_(ADMIN_IDS))
async def santa_stop(message: Message):
    santa_data["active"] = False
    santa_data["deadline"] = None
    santa_data["gift_date"] = None
    santa_data["participants"] = {}
    santa_data["pairs"] = {}
    await save_santa()
    await message.answer("✅ Тайный Санта сброшен.")