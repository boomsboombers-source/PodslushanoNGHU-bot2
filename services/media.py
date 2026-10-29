# services/media.py
from aiogram import Bot
from aiogram.types import Message
from services.text import esc  # реэкспорт для совместимости

__all__ = ["esc", "_send_media_with_caption"]


async def _send_media_with_caption(bot: Bot, target_id: int, message: Message, caption: str = "", parse_mode=None, reply_to_message_id: int = None) -> Message:
    """Универсальная функция отправки любого контента."""
    if message.photo: return await bot.send_photo(target_id, photo=message.photo[-1].file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.video: return await bot.send_video(target_id, video=message.video.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.document: return await bot.send_document(target_id, document=message.document.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.audio: return await bot.send_audio(target_id, audio=message.audio.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.voice: return await bot.send_voice(target_id, voice=message.voice.file_id, caption=caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)
    elif message.video_note: return await bot.send_video_note(target_id, video_note=message.video_note.file_id, reply_to_message_id=reply_to_message_id)
    elif message.sticker: return await bot.send_sticker(target_id, sticker=message.sticker.file_id, reply_to_message_id=reply_to_message_id)
    elif message.contact:
        sent = await bot.send_contact(target_id, phone_number=message.contact.phone_number, first_name=message.contact.first_name, last_name=message.contact.last_name, reply_to_message_id=reply_to_message_id)
        if caption:
            await bot.send_message(target_id, caption, parse_mode=parse_mode, reply_to_message_id=sent.message_id)
        return sent
    elif message.location:
        sent = await bot.send_location(target_id, latitude=message.location.latitude, longitude=message.location.longitude, reply_to_message_id=reply_to_message_id)
        if caption:
            await bot.send_message(target_id, caption, parse_mode=parse_mode, reply_to_message_id=sent.message_id)
        return sent
    else:
        return await bot.send_message(target_id, caption, parse_mode=parse_mode, reply_to_message_id=reply_to_message_id)