import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN, DATA_DIR
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.moderation import moderation_router
from services.storage import load_users_cache, load_replies, load_muted, load_delayed, auto_save_replies
from services.scheduler import delayed_poster, cleanup_muted

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

dp.include_router(admin_router)
dp.include_router(moderation_router)
dp.include_router(user_router)

async def main():
    load_users_cache()
    load_replies()
    load_muted()
    load_delayed()

    logging.info("Бот запущен. Ожидание сообщений...")

    background_tasks = [
        asyncio.create_task(auto_save_replies()),
        asyncio.create_task(delayed_poster(bot)),
        asyncio.create_task(cleanup_muted()),
    ]

    try:
        await dp.start_polling(bot, skip_updates=True, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logging.error(f"Ошибка поллинга: {e}")
    finally:
        for t in background_tasks:
            t.cancel()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
