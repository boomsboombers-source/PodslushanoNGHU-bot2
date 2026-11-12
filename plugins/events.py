# plugins/events.py
"""
Плагин «События и напоминания».

Типы событий (флаг announce):
  • announce=True  — авто-напоминания идут в канал (CHANNEL_ID).
  • announce=False — «тихое» событие: в канал не напоминаем, но в !события показываем.

Время (флаг has_time):
  • has_time=True  — время указано явно, показываем его, шлём напоминание за час и утром.
  • has_time=False — время не указано, в списке время не показываем, шлём только утреннее.

Команды (все — Админ + Модер):
  !событие ДД.ММ [ЧЧ:ММ] Текст   — добавить событие с уведомлением
  !событие_т ДД.ММ [ЧЧ:ММ] Текст — добавить событие без уведомления
  !событие_режим ID              — переключить режим события (announce toggle)
  !удалить_событие ID            — удалить событие

Команда для всех:
  !события                       — список ближайших событий
"""

import os
import json
import logging
import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ParseMode

from config import CHANNEL_ID, ADMIN_IDS, MODERATOR_IDS, DATA_DIR

PLUGIN_INFO = {
    "name": "События",
    "icon": "📅",
    "description": "Календарь событий с авто-напоминаниями в канал (можно отключать)",
    "commands": [
        ("!событие ДД.ММ ЧЧ:ММ Текст", "добавить событие с уведомлением (админ, модер)"),
        ("!событие_т ДД.ММ ЧЧ:ММ Текст", "добавить событие без уведомления (админ, модер)"),
        ("!событие_режим ID", "переключить режим уведомлений у события (админ, модер)"),
        ("!события", "список ближайших событий (все)"),
        ("!удалить_событие ID", "удалить событие (админ, модер)"),
    ],
}

router = Router(name="events")

EVENTS_DIR = os.path.join(DATA_DIR, "events")
os.makedirs(EVENTS_DIR, exist_ok=True)
EVENTS_FILE = os.path.join(EVENTS_DIR, "events.json")

# {"id": {"text": str, "datetime": ts, "has_time": bool, "notified_day": bool,
#         "notified_hour": bool, "announce": bool}}
events = {}
event_counter = 0
events_lock = asyncio.Lock()

NSK = ZoneInfo("Asia/Novosibirsk")
STAFF = ADMIN_IDS + MODERATOR_IDS

_RE_EVENT = re.compile(r"^!событие(\s|$)", re.IGNORECASE)
_RE_EVENT_T = re.compile(r"^!событие_т(\s|$)", re.IGNORECASE)
_RE_EVENT_MODE = re.compile(r"^!событие_режим(\s|$)", re.IGNORECASE)
_RE_EVENTS_LIST = re.compile(r"^!события$", re.IGNORECASE)
_RE_EVENT_DEL = re.compile(r"^!удалить_событие(\s|$)", re.IGNORECASE)


# ==============================================================================
# ================= ХРАНИЛИЩЕ ==================================================
# ==============================================================================

def load_events():
    global events, event_counter
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                events = data.get("events", {})
                event_counter = data.get("counter", 0)
            for ev in events.values():
                if ev.get("announce") is None:
                    ev["announce"] = True
                if ev.get("has_time") is None:
                    ev["has_time"] = True  # старые записи — как есть
                if ev.get("notified_day") is None:
                    ev["notified_day"] = False
                if ev.get("notified_hour") is None:
                    ev["notified_hour"] = False
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
# ================= ВСПОМОГАТЕЛЬНОЕ ============================================
# ==============================================================================

def _parse_event_args(body: str):
    """
    body — строка после команды.
    Форматы:
      'ДД.ММ Текст'
      'ДД.ММ ЧЧ:ММ Текст'
    Возвращает (target_dt, text, has_time) или (None, None, False).
    """
    parts = body.split(maxsplit=2)
    if len(parts) < 2:
        return None, None, False
    try:
        date_str = parts[0]
        has_time = len(parts) >= 2 and ":" in parts[1]
        if has_time:
            if len(parts) < 3:
                return None, None, False
            time_str = parts[1]
            text = parts[2]
            dt_str = f"{date_str}.{datetime.now(NSK).year} {time_str}"
            target_dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        else:
            text = " ".join(parts[1:])
            dt_str = f"{date_str}.{datetime.now(NSK).year} 08:00"
            target_dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")

        target_dt = target_dt.replace(tzinfo=NSK)
        if target_dt < datetime.now(NSK):
            target_dt = target_dt.replace(year=target_dt.year + 1)
        return target_dt, text.strip(), has_time
    except Exception:
        return None, None, False


async def _add_event(message: Message, body: str, announce: bool):
    global event_counter
    target_dt, text, has_time = _parse_event_args(body)
    if not target_dt or not text:
        example = "!событие_т" if not announce else "!событие"
        await message.answer(
            f"❌ Формат: <code>{example} ДД.ММ [ЧЧ:ММ] Текст</code>\n"
            f"Пример: <code>{example} 20.11 18:00 Концерт</code>",
            parse_mode=ParseMode.HTML
        )
        return

    event_counter += 1
    ev_id = str(event_counter)
    events[ev_id] = {
        "text": text,
        "datetime": target_dt.timestamp(),
        "has_time": has_time,
        "notified_day": False,
        "notified_hour": False,
        "announce": announce,
    }
    await save_events()

    mode = "📢 с уведомлением в канал" if announce else "🔕 без уведомления"
    when = target_dt.strftime("%d.%m.%Y %H:%M") if has_time else target_dt.strftime("%d.%m.%Y") + " (без времени)"
    await message.answer(
        f"✅ Событие добавлено!\n"
        f"ID: <code>{ev_id}</code>\n"
        f"Режим: {mode}\n"
        f"Когда: {when}\n"
        f"Что: {text}",
        parse_mode=ParseMode.HTML
    )


# ==============================================================================
# ================= КОМАНДЫ ====================================================
# ==============================================================================

@router.message(F.text.regexp(_RE_EVENT_T), F.from_user.id.in_(STAFF))
async def add_event_silent(message: Message):
    body = message.text[len("!событие_т"):].strip()
    await _add_event(message, body, announce=False)


@router.message(F.text.regexp(_RE_EVENT_MODE), F.from_user.id.in_(STAFF))
async def toggle_event_mode(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: <code>!событие_режим ID</code>", parse_mode=ParseMode.HTML)
        return
    ev_id = parts[1]
    ev = events.get(ev_id)
    if not ev:
        await message.answer(f"⚠️ Событие с ID <code>{ev_id}</code> не найдено.", parse_mode=ParseMode.HTML)
        return

    was = ev.get("announce", True)
    ev["announce"] = not was

    if ev["announce"] and ev["datetime"] <= datetime.now(NSK).timestamp():
        ev["notified_day"] = True
        ev["notified_hour"] = True

    await save_events()

    def label(v: bool) -> str:
        return "📢 с уведомлением" if v else "🔕 без уведомления"

    await message.answer(
        f"✅ Режим события <code>{ev_id}</code> изменён.\n"
        f"Было: {label(was)}\n"
        f"Стало: {label(ev['announce'])}",
        parse_mode=ParseMode.HTML
    )


@router.message(F.text.regexp(_RE_EVENT), F.from_user.id.in_(STAFF))
async def add_event_public(message: Message):
    body = message.text[len("!событие"):].strip()
    await _add_event(message, body, announce=True)


@router.message(F.text.regexp(_RE_EVENTS_LIST))
async def list_events(message: Message):
    if not events:
        await message.answer("📅 Ближайших событий нет.")
        return

    now_ts = datetime.now(NSK).timestamp()
    actual = [(eid, ev) for eid, ev in events.items() if ev["datetime"] > now_ts - 3600]
    actual.sort(key=lambda x: x[1]["datetime"])

    if not actual:
        await message.answer("📅 Ближайших событий нет.")
        return

    is_staff = message.from_user.id in STAFF
    lines = ["📅 <b>Ближайшие события:</b>\n"]
    for idx, (ev_id, ev) in enumerate(actual, 1):
        dt = datetime.fromtimestamp(ev["datetime"], NSK)
        if ev.get("has_time", True):
            when = dt.strftime("%d.%m %H:%M")
        else:
            when = dt.strftime("%d.%m")
        line = f"{idx}. <b>{when}</b> — {ev['text']}"
        if is_staff:
            tags = []
            if not ev.get("announce", True):
                tags.append("🔕")
            tags.append(f"id:{ev_id}")
            line += " [" + " ".join(tags) + "]"
        lines.append(line)
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(_RE_EVENT_DEL), F.from_user.id.in_(STAFF))
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
            now = datetime.now(NSK)
            now_ts = now.timestamp()
            updated = False

            for ev_id, ev in list(events.items()):
                if not ev.get("announce", True):
                    continue

                target_ts = ev["datetime"]
                diff_hours = (target_ts - now_ts) / 3600
                ev_dt = datetime.fromtimestamp(target_ts, NSK)
                has_time = ev.get("has_time", True)

                # 1. За час — только если время указано явно
                if has_time and 0.9 <= diff_hours <= 1.1 and not ev.get("notified_hour"):
                    try:
                        await bot.send_message(
                            CHANNEL_ID,
                            f"🔔 <b>Напоминание:</b> через час начнется событие!\n\n"
                            f"📌 <b>{ev['text']}</b>\n"
                            f"🕒 В {ev_dt.strftime('%H:%M')}",
                            parse_mode=ParseMode.HTML
                        )
                        ev["notified_hour"] = True
                        updated = True
                    except Exception as e:
                        logging.error(f"Ошибка напоминания за час (id={ev_id}): {e}")

                # 2. Утром в день события
                elif (now.hour >= 8 and not ev.get("notified_day")
                      and ev_dt.date() == now.date() and target_ts > now_ts):
                    time_line = f"\n🕒 В {ev_dt.strftime('%H:%M')}" if has_time else ""
                    try:
                        await bot.send_message(
                            CHANNEL_ID,
                            f"📅 <b>Доброе утро! Сегодня событие:</b>\n\n"
                            f"📌 <b>{ev['text']}</b>{time_line}",
                            parse_mode=ParseMode.HTML
                        )
                        ev["notified_day"] = True
                        updated = True
                    except Exception as e:
                        logging.error(f"Ошибка утреннего напоминания (id={ev_id}): {e}")

            if updated:
                await save_events()

        except Exception as e:
            logging.error(f"Ошибка в цикле событий: {e}")

        await asyncio.sleep(60)
