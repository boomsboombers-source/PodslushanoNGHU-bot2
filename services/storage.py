import os
import json
import logging
import asyncio
from datetime import datetime
from config import USERS_FILE, REPLIES_FILE, MUTED_FILE, DELAYED_FILE
from services.database import (
    save_username_db, get_username_by_id_db, 
    save_log_id_db, get_log_msg_id_db, get_user_id_by_username_db
)

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ (ХРАНИЛИЩА) ---
active_replies = {}
cached_users = set()
muted_users = {}
delayed_posts = []
log_msg_ids = {}          # Оставляем для обратной совместимости, но используем БД

replies_dirty = False
log_ids_dirty = False
user_file_lock = asyncio.Lock()
usernames_file_lock = asyncio.Lock()
muted_lock = asyncio.Lock()
active_replies_lock = asyncio.Lock()

# ==============================================================================
# ================= ПОЛЬЗОВАТЕЛИ ===============================================
# ==============================================================================

def load_users_cache():
    global cached_users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                cached_users.clear()
                cached_users.update(f.read().splitlines())
        except Exception as e:
            logging.error(f"Ошибка загрузки users.txt: {e}")
            cached_users.clear()
    else:
        logging.warning(f"users.txt не найден по пути: {USERS_FILE}")

async def save_user(user_id: int):
    global cached_users
    user_id_str = str(user_id)
    async with user_file_lock:
        if user_id_str in cached_users:
            return
        cached_users.add(user_id_str)
        try:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(user_id_str + "\n")
        except Exception as e:
            logging.error(f"Ошибка сохранения пользователя {user_id}: {e}")
            cached_users.discard(user_id_str)

def get_all_users() -> list[str]:
    return list(cached_users.copy())

# ==============================================================================
# ================= ЮЗЕРНЕЙМЫ ==================================================
# ==============================================================================

async def save_username(username, user_id: int):
    await save_username_db(user_id, username)

async def get_id_by_username(username: str):
    return await get_user_id_by_username_db(username)

async def get_username_by_id(user_id: int) -> str:
    return await get_username_by_id_db(user_id)

# ==============================================================================
# ================= ОТВЕТЫ =====================================================
# ==============================================================================

def load_replies():
    global active_replies
    if os.path.exists(REPLIES_FILE):
        try:
            with open(REPLIES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            active_replies.clear()
            active_replies.update({int(k): v for k, v in data.items()})
        except Exception as e:
            logging.error(f"Ошибка загрузки replies.json: {e}")

def mark_replies_dirty():
    global replies_dirty
    replies_dirty = True

async def auto_save_replies():
    global replies_dirty
    while True:
        if replies_dirty:
            try:
                temp_file = REPLIES_FILE + ".tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(active_replies, f)
                os.replace(temp_file, REPLIES_FILE)
                replies_dirty = False
            except Exception as e:
                logging.error(f"Ошибка сохранения replies.json: {e}")
        await asyncio.sleep(5)

# ==============================================================================
# ================= ЛОГ-СООБЩЕНИЯ (channel_msg_id -> log_msg_id) ===============
# ==============================================================================

def load_log_ids():
    pass # Теперь данные в БД

def mark_log_ids_dirty():
    pass

async def save_log_msg_id(channel_msg_id: int, log_msg_id: int):
    await save_log_id_db(channel_msg_id, log_msg_id)

async def get_log_msg_id(channel_msg_id: int):
    return await get_log_msg_id_db(channel_msg_id)

async def auto_save_log_ids():
    pass # Теперь данные в БД

# ==============================================================================
# ================= МУТЫ =======================================================
# ==============================================================================

def load_muted():
    global muted_users
    if os.path.exists(MUTED_FILE):
        try:
            with open(MUTED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            muted_users.clear()
            muted_users.update({int(k): v for k, v in data.items()})
        except Exception as e:
            logging.error(f"Ошибка загрузки muted.json: {e}")
            muted_users.clear()

async def save_muted():
    async with muted_lock:
        try:
            temp_file = MUTED_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(muted_users, f)
            os.replace(temp_file, MUTED_FILE)
        except Exception as e:
            logging.error(f"Ошибка сохранения muted.json: {e}")

async def check_mute(user_id: int):
    if user_id in muted_users:
        remaining = muted_users[user_id] - datetime.now().timestamp()
        if remaining > 0:
            return int(remaining)
        else:
            async with muted_lock:
                muted_users.pop(user_id, None)
            await save_muted()
    return None

# ==============================================================================
# ================= ОТЛОЖЕННЫЕ ПОСТЫ ===========================================
# ==============================================================================

def serialize_message(message) -> dict:
    data = {"type": message.content_type, "text": message.text or message.caption or ""}
    if message.photo: data["file_id"] = message.photo[-1].file_id
    elif message.video: data["file_id"] = message.video.file_id
    elif message.document: data["file_id"] = message.document.file_id
    elif message.audio: data["file_id"] = message.audio.file_id
    elif message.voice: data["file_id"] = message.voice.file_id
    elif message.video_note: data["file_id"] = message.video_note.file_id
    elif message.sticker: data["file_id"] = message.sticker.file_id
    elif message.contact:
        data["contact"] = {"phone_number": message.contact.phone_number, "first_name": message.contact.first_name, "last_name": message.contact.last_name}
        data["text"] = ""
    elif message.location:
        data["location"] = {"latitude": message.location.latitude, "longitude": message.location.longitude}
        data["text"] = ""
    return data

def load_delayed():
    global delayed_posts
    if not os.path.exists(DELAYED_FILE):
        return
    try:
        with open(DELAYED_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("delayed.json: ожидался список")
        valid = [p for p in raw if isinstance(p, dict) and "time" in p and "type" in p]
        delayed_posts.clear()
        delayed_posts.extend(valid)
    except Exception as e:
        logging.error(f"Ошибка загрузки delayed.json: {e}")
        os.replace(DELAYED_FILE, DELAYED_FILE + ".bak")
        delayed_posts.clear()
