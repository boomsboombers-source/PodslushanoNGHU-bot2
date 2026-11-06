import asyncio
import logging
import os
import importlib
import pkgutil

from aiogram import Bot, Dispatcher
from config import BOT_TOKEN, DATA_DIR
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.moderation import moderation_router
from services.storage import (
    load_users_cache, load_replies, load_muted, load_delayed,
    auto_save_replies
)
from services.scheduler import delayed_poster, cleanup_muted
from services.database import init_db, close_db
from services import plugin_registry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(DATA_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def load_plugins(dp: Dispatcher) -> None:
    plugins_dir = "plugins"
    if not os.path.exists(plugins_dir):
        os.makedirs(plugins_dir)
        with open(os.path.join(plugins_dir, "__init__.py"), "w", encoding="utf-8"):
            pass
        logging.info("Создана папка plugins/ с пустым __init__.py")
        return

    init_path = os.path.join(plugins_dir, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8"):
            pass
        logging.info("Создан plugins/__init__.py")

    try:
        import plugins as plugins_pkg
    except Exception as e:
        logging.error(f"Не удалось импортировать пакет plugins: {e}")
        return

    for _, name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
        if name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"plugins.{name}")
        except Exception as e:
            logging.error(f"❌ Ошибка импорта плагина {name}: {e}")
            continue

        router = getattr(mod, "router", None)
        if router is None:
            logging.warning(f"⚠️ Плагин {name}: нет атрибута 'router' — пропущен")
            continue

        dp.include_router(router)

        info = getattr(mod, "PLUGIN_INFO", None)
        if info:
            plugin_registry.register(info)
        else:
            plugin_registry.register({
                "name": name,
                "description": "описание не указано",
                "commands": [],
            })

        logging.info(f"✅ Плагин загружен: {name}")

# Порядок: плагины → admin → moderation → user (самый широкий последним)
load_plugins(dp)
dp.include_router(admin_router)
dp.include_router(moderation_router)
dp.include_router(user_router)


async def main():
    await init_db()
    
    load_users_cache()
    load_replies()
    load_muted()
    load_delayed()

    logging.info("Бот запущен. Ожидание сообщений...")

    from plugins.birthdays import auto_congratulate
    from datetime import datetime
    from zoneinfo import ZoneInfo

    async def _birthday_loop():
        NSK_TZ = ZoneInfo("Asia/Novosibirsk")
        while True:
            now = datetime.now(NSK_TZ)
            if now.hour == 8 and now.minute < 5:
                try:
                    await auto_congratulate(bot)
                except Exception as e:
                    logging.error(f"birthdays loop: {e}")
                await asyncio.sleep(600)
            else:
                await asyncio.sleep(60)

    background_tasks = [
        asyncio.create_task(auto_save_replies()),
        asyncio.create_task(delayed_poster(bot)),
        asyncio.create_task(cleanup_muted()),
        asyncio.create_task(_birthday_loop()),
    ]

    try:
        await dp.start_polling(bot, skip_updates=True, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logging.error(f"Ошибка поллинга: {e}")
    finally:
        for t in background_tasks:
            t.cancel()
        await close_db()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
