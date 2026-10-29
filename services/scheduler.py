import asyncio
import json
import logging
from datetime import datetime
from config import CHANNEL_ID, LOG_CHAT_ID, DELAYED_FILE
from services.storage import delayed_posts, muted_users, save_muted
from aiogram.enums import ParseMode

async def send_delayed_post(bot, post: dict):
    try:
        ptype = post.get("type")
        text = post.get("text", "")
        file_id = post.get("file_id")

        if ptype == "text": await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        elif ptype == "photo": await bot.send_photo(CHANNEL_ID, photo=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "video": await bot.send_video(CHANNEL_ID, video=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "document": await bot.send_document(CHANNEL_ID, document=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "audio": await bot.send_audio(CHANNEL_ID, audio=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "voice": await bot.send_voice(CHANNEL_ID, voice=file_id, caption=text, parse_mode=ParseMode.HTML)
        elif ptype == "video_note": await bot.send_video_note(CHANNEL_ID, video_note=file_id)
        elif ptype == "sticker": await bot.send_sticker(CHANNEL_ID, sticker=file_id)
        elif ptype == "contact":
            c = post.get("contact", {})
            await bot.send_contact(CHANNEL_ID, phone_number=c.get("phone_number", ""), first_name=c.get("first_name", ""), last_name=c.get("last_name"))
            if text: await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        elif ptype == "location":
            loc = post.get("location", {})
            await bot.send_location(CHANNEL_ID, latitude=loc.get("latitude", 0), longitude=loc.get("longitude", 0))
            if text: await bot.send_message(CHANNEL_ID, text, parse_mode=ParseMode.HTML)
        else: await bot.send_message(CHANNEL_ID, text)
    except Exception as e:
        logging.error(f"Ошибка отправки отложенного поста: {e}")

async def delayed_poster(bot):
    while True:
        try:
            now_ts = datetime.now().timestamp()
            to_remove = []
            for post in list(delayed_posts):
                try:
                    if post.get("time", float("inf")) <= now_ts:
                        await send_delayed_post(bot, post)
                        to_remove.append(post)
                except Exception as e:
                    logging.error(f"Ошибка при отправке отложенного поста: {e}")
                    try:
                        await bot.send_message(LOG_CHAT_ID, f"⚠️ <b>Ошибка отложенного поста!</b>\nТип: {post.get('type')}\nОшибка: {e}\nПост удален из очереди.", parse_mode=ParseMode.HTML)
                    except Exception: pass
                    to_remove.append(post)

            if to_remove:
                for post in to_remove:
                    try: delayed_posts.remove(post)
                    except ValueError: pass
                with open(DELAYED_FILE, "w", encoding="utf-8") as f:
                    json.dump(delayed_posts, f)
        except Exception as e:
            logging.error(f"Критическая ошибка в delayed_poster: {e}")
        await asyncio.sleep(30)

async def cleanup_muted():
    while True:
        try:
            now_ts = datetime.now().timestamp()
            expired = [uid for uid, until in muted_users.items() if until < now_ts]
            if expired:
                for uid in expired:
                    del muted_users[uid]
                save_muted()
                logging.info(f"Очищено {len(expired)} истекших мутов.")
        except Exception as e:
            logging.error(f"Ошибка в cleanup_muted: {e}")
        await asyncio.sleep(3600)