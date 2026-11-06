import asyncio
import json
import os
import aiosqlite
from config import DATA_DIR
from services.database import init_db, close_db, db

USERNAMES_FILE = os.path.join(DATA_DIR, "usernames.txt")
LOG_IDS_FILE = os.path.join(DATA_DIR, "log_ids.json")
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.txt")

async def migrate():
    print("🚀 Начинаем миграцию...")
    await init_db()
    
    # 1. Перенос Usernames
    if os.path.exists(USERNAMES_FILE):
        print("📦 Переносим usernames.txt...")
        with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if ":" in line:
                    username, user_id = line.rsplit(":", 1)
                    try:
                        await db.execute(
                            "INSERT OR REPLACE INTO usernames (user_id, username) VALUES (?, ?)",
                            (int(user_id), username)
                        )
                    except ValueError:
                        pass
        await db.commit()
        print("✅ Usernames перенесены")

    # 2. Перенос Log IDs
    if os.path.exists(LOG_IDS_FILE):
        print("📦 Переносим log_ids.json...")
        with open(LOG_IDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for channel_id, log_id in data.items():
                await db.execute(
                    "INSERT OR REPLACE INTO log_ids (channel_msg_id, log_msg_id) VALUES (?, ?)",
                    (int(channel_id), int(log_id))
                )
        await db.commit()
        print("✅ Log IDs перенесены")

    # 3. Перенос Messages
    if os.path.exists(MESSAGES_FILE):
        print("📦 Переносим messages.txt (это может занять минуту)...")
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("-"):
                    await db.execute(
                        "INSERT INTO messages (user_id, date, type, text) VALUES (?, ?, ?, ?)",
                        (0, "old", "unknown", line)
                    )
        await db.commit()
        print("✅ Messages перенесены")

    await close_db()
    print("🎉 Миграция завершена! Теперь можно переименовать старые файлы в .bak")

if __name__ == "__main__":
    asyncio.run(migrate())