# plugins/events.py
"""
Плагин «События и напоминания».
Команды:
  !событие ДД.ММ [ЧЧ:ММ] Текст — добавить событие (админ, модер)
  !события — список ближайших событий (все)
  !удалить_событие ID — удалить событие (админ)
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ParseMode

from config import CHANNEL_ID, ADMIN_IDS, MODERATOR_IDS, DATA_DIR

PLUGIN_INFO = {
    "name": "События",
    "description": "Календарь событий и авто-напоминания в канал",
    "commands": [
        ("!событие ДД.ММ ЧЧ:ММ Текст", "добавить событие (админ, модер)"),
        ("!события", "список ближайших событий (все)"),
        ("!удалить_событие ID", "удалить событие (админ)"),
    ],
}

router = Router(name="events")

# === НОВЫЙ ПУТЬ К ПАПКЕ ===
EVENTS_DIR = os.path.join(DATA_DIR, "events")
os.makedirs(EVENTS_DIR, exist_ok=True)
EVENTS_FILE = os.path.join(EVENTS_DIR, "events.json")

events = {}  # {"id": {"text": str, "datetime": timestamp, "notified_day": bool, "notified_hour": bool}}
event_counter = 0
events_lock = asyncio.Lock()


def load_events():
    global events, event_counter
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                events = data.get("events", {})
                event_counter = data.get("counter", 0)
        except Exception as e:
            logging.error(f"Ошибка загрузки events.json: {e}")


async def save_events():
    async with events_lock:
        try:
            tmp = EVENTS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"events": events, "counter": event_counter}, f, ensure_ascii=False)
            os.replace(tmp, EVENTS_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения events.json: {e}")


load_events()


# ==============================================================================
# ================= КОМАНДЫ ====================================================
# ==============================================================================

@router.message(F.text.lower().startswith("!событие"), F.from_user.id.in_(ADMIN_IDS + MODERATOR_IDS))
async def add_event(message: Message):
    global event_counter
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer("❌ Формат: <code>!событие ДД.ММ [ЧЧ:ММ] Текст</code>", parse_mode=ParseMode.HTML)
        return

    try:
        date_str = parts[1]
        # Проверяем, есть ли время в строке 2 (если там двоеточие)
        has_time = ":" in parts[2]
        if has_time:
            if len(parts) < 4: raise ValueError
            time_str = parts[2]
            text = parts[3]
            dt_str = f"{date_str}.{datetime.now().year} {time_str}"
            target_dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        else:
            time_str = "08:00"  # По умолчанию утро
            text = " ".join(parts[2:])
            dt_str = f"{date_str}.{datetime.now().year} {time_str}"
            target_dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")

        # Ставим таймзону Новосибирска
        target_dt = target_dt.replace(tzinfo=ZoneInfo("Asia/Novosibirsk"))
        
        # Если дата уже прошла в этом году, ставим на следующий
        if target_dt < datetime.now(ZoneInfo("Asia/Novosibirsk")):
            target_dt = target_dt.replace(year=target_dt.year + 1)

        event_counter += 1
        ev_id = str(event_counter)
        
        events[ev_id] = {
            "text": text,
            "datetime": target_dt.timestamp(),
            "notified_day": False,
            "notified_hour": False
        }
        await save_events()

        await message.answer(f"✅ Событие добавлено!\nID: <code>{ev_id}</code>\nКогда: {target_dt.strftime('%d.%m.%Y %H:%M')}\nЧто: {text}", parse_mode=ParseMode.HTML)
    except Exception:
        await message.answer("❌ Ошибка формата. Пример: <code>!событие 20.11 18:00 Концерт</code>", parse_mode=ParseMode.HTML)


@router.message(F.text.lower() == "!события")
async def list_events(message: Message):
    if not events:
        await message.answer("📅 Ближайших событий нет.")
        return

    now_ts = datetime.now(ZoneInfo("Asia/Novosibirsk")).timestamp()
    # Фильтруем прошедшие и сортируем
    actual_events = []
    for ev_id, ev in events.items():
        if ev["datetime"] > now_ts - 3600:  # Оставляем те, что прошли не более часа назад
            actual_events.append((ev_id, ev))
    
    actual_events.sort(key=lambda x: x[1]["datetime"])

    if not actual_events:
        await message.answer("📅 Ближайших событий нет.")
        return

    lines = ["📅 <b>Ближайшие события:</b>\n"]
    for ev_id, ev in actual_events:
        dt = datetime.fromtimestamp(ev["datetime"], ZoneInfo("Asia/Novosibirsk"))
        lines.append(f"• <code>{ev_id}</code> | <b>{dt.strftime('%d.%m %H:%M')}</b> — {ev['text']}")
    
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.lower().startswith("!удалить_событие"), F.from_user.id.in_(ADMIN_IDS))
async def del_event(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: <code>!удалить_событие ID</code>", parse_mode=ParseMode.HTML)
        return
    
    ev_id = parts[1]
    if ev_id in events:
        events.pop(ev_id)
        await save_events()
        await message.answer(f"✅ Событие {ev_id} удалено.")
    else:
        await message.answer(f"⚠️ Событие с ID {ev_id} не найдено.")


# ==============================================================================
# ================= ФОНОВАЯ ПРОВЕРКА (вызывается из bot.py) ====================
# ==============================================================================

async def check_events_loop(bot):
    """Раз в минуту проверяет, не пора ли отправить напоминание."""
    logging.info("📅 Цикл проверки событий запущен.")
    while True:
        try:
            now = datetime.now(ZoneInfo("Asia/Novosibirsk"))
            now_ts = now.timestamp()
            updated = False

            for ev_id, ev in list(events.items()):
                target_ts = ev["datetime"]
                diff_hours = (target_ts - now_ts) / 3600

                # 1. Напоминание за час (если до события осталось от 0.9 до 1.1 часа)
                if 0.9 <= diff_hours <= 1.1 and not ev.get("notified_hour"):
                    await bot.send_message(
                        CHANNEL_ID,
                        f"🔔 <b>Напоминание:</b> через час начнется событие!\n\n📌 <b>{ev['text']}</b>\n🕒 В {datetime.fromtimestamp(target_ts, ZoneInfo('Asia/Novosibirsk')).strftime('%H:%M')}",
                        parse_mode=ParseMode.HTML
                    )
                    ev["notified_hour"] = True
                    updated = True

                # 2. Напоминание в день события (в 08:00 утра)
                elif now.hour == 8 and now.minute < 5 and not ev.get("notified_day"):
                    # Проверяем, что событие именно сегодня
                    ev_date = datetime.fromtimestamp(target_ts, ZoneInfo("Asia/Novosibirsk")).date()
                    if ev_date == now.date():
                        await bot.send_message(
                            CHANNEL_ID,
                            f"📅 <b>Доброе утро! Сегодня событие:</b>\n\n📌 <b>{ev['text']}</b>\n🕒 В {datetime.fromtimestamp(target_ts, ZoneInfo('Asia/Novosibirsk')).strftime('%H:%M')}",
                            parse_mode=ParseMode.HTML
                        )
                        ev["notified_day"] = True
                        updated = True

            if updated:
                await save_events()

        except Exception as e:
            logging.error(f"Ошибка в цикле событий: {e}")
        
        await asyncio.sleep(60)
