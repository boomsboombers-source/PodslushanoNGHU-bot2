import aiosqlite
import logging
import os
from config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "bot.db")
db = None

async def init_db():
    global db
    db = await aiosqlite.connect(DB_PATH)
    # Включаем WAL режим для быстрой работы при частых записях
    await db.execute("PRAGMA journal_mode=WAL;")
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS usernames (
            user_id INTEGER PRIMARY KEY, 
            username TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS log_ids (
            channel_msg_id INTEGER PRIMARY KEY, 
            log_msg_id INTEGER
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            type TEXT,
            text TEXT
        )
    """)
    await db.commit()
    logging.info("✅ База данных инициализирована")

async def close_db():
    global db
    if db:
        await db.close()
        logging.info("❌ База данных закрыта")

# --- Функции для работы с БД ---

async def save_username_db(user_id: int, username: str):
    if not username: return
    await db.execute(
        "INSERT OR REPLACE INTO usernames (user_id, username) VALUES (?, ?)", 
        (user_id, username.lower().lstrip('@'))
    )
    await db.commit()

async def get_username_by_id_db(user_id: int) -> str:
    async with db.execute("SELECT username FROM usernames WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        return f"@{row[0]}" if row else "нет username"

async def save_log_id_db(channel_msg_id: int, log_msg_id: int):
    await db.execute(
        "INSERT OR REPLACE INTO log_ids (channel_msg_id, log_msg_id) VALUES (?, ?)",
        (channel_msg_id, log_msg_id)
    )
    await db.commit()

async def get_log_msg_id_db(channel_msg_id: int):
    async with db.execute("SELECT log_msg_id FROM log_ids WHERE channel_msg_id = ?", (channel_msg_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None

async def log_message_db(user_id: int, date: str, msg_type: str, text: str):
    await db.execute(
        "INSERT INTO messages (user_id, date, type, text) VALUES (?, ?, ?, ?)",
        (user_id, date, msg_type, text)
    )
    await db.commit()

async def get_user_info_db(user_id: int) -> dict:
    """Возвращает инфу о юзере (юзернейм и кол-во сообщений)."""
    # 1. Ищем юзернейм
    async with db.execute("SELECT username FROM usernames WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        username = f"@{row[0]}" if row else "нет username"
    
    # 2. Считаем сообщения
    async with db.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)) as cursor:
        msg_count = (await cursor.fetchone())[0]
        
    return {"username": username, "messages": msg_count}

async def get_top_users_db(limit: int = 10) -> list[dict]:
    """Возвращает топ юзеров по кол-ву сообщений."""
    top = []
    async with db.execute(
        "SELECT user_id, COUNT(*) as cnt FROM messages WHERE user_id != 0 GROUP BY user_id ORDER BY cnt DESC LIMIT ?", 
        (limit,)
    ) as cursor:
        async for row in cursor:
            top.append({"user_id": row[0], "count": row[1]})
    return top

async def get_user_id_by_username_db(username: str):
    """Ищет user_id по username в базе."""
    username = username.lower().lstrip('@')
    async with db.execute("SELECT user_id FROM usernames WHERE username = ?", (username,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None
