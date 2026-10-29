import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from config import CHANNEL_ID, ADMIN_IDS
from services.storage import muted_users, save_muted
from services.media import esc

moderation_router = Router()

class MuteStates(StatesGroup):
    waiting_for_reason = State()

@moderation_router.callback_query(F.data.startswith("delete_msg_"))
async def delete_message_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа")
    if callback.message is None:
        return await callback.answer("Сообщение недоступно", show_alert=True)
    try:
        msg_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        return await callback.answer("❌ Некорректный ID", show_alert=True)
    try:
        await callback.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer("✅ Удалено!", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

@moderation_router.callback_query(F.data.startswith("mute_menu_"))
async def mute_menu_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа")
    if callback.message is None:
        return await callback.answer("Сообщение недоступно", show_alert=True)
    try:
        target_user_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        return await callback.answer("❌ Некорректный ID", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ 15 минут", callback_data=f"mute_set_{target_user_id}_15")],
        [InlineKeyboardButton(text="⚠️ 30 минут", callback_data=f"mute_set_{target_user_id}_30")],
        [InlineKeyboardButton(text="⚠️ 1 час", callback_data=f"mute_set_{target_user_id}_60")],
        [InlineKeyboardButton(text="⚠️ 2 часа", callback_data=f"mute_set_{target_user_id}_120")],
        [InlineKeyboardButton(text="⚠️ 5 часов", callback_data=f"mute_set_{target_user_id}_300")],
        [InlineKeyboardButton(text="⚠️ 24 часа", callback_data=f"mute_set_{target_user_id}_1440")],
        [InlineKeyboardButton(text="✅ Размутить", callback_data=f"unmute_{target_user_id}")]
    ])
    await callback.message.answer(f"Выбери время мута или размуть <code>{target_user_id}</code>:", reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@moderation_router.callback_query(F.data.startswith("mute_set_"))
async def mute_set_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа")
    if callback.message is None:
        return await callback.answer("Сообщение недоступно", show_alert=True)
    try:
        parts = callback.data.split("_")
        target_user_id = int(parts[2])
        minutes = int(parts[3])
    except (IndexError, ValueError):
        return await callback.answer("❌ Некорректные данные", show_alert=True)

    await state.update_data(target_user_id=target_user_id, minutes=minutes)
    await callback.message.edit_text(
        f"✍️ Напиши причину мута для <code>{target_user_id}</code> на {minutes} мин.\n"
        f"Или отправь <code>/skip</code>, если причина не нужна.\n"
        f"Или <code>/cancel</code>, чтобы отменить.",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(MuteStates.waiting_for_reason)
    await callback.answer()

@moderation_router.message(MuteStates.waiting_for_reason, F.text == "/cancel")
async def cancel_mute_reason(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Мут отменён.")

@moderation_router.message(MuteStates.waiting_for_reason)
async def process_mute_reason(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    if message.text is None:
        await message.answer("❌ Пришли причину текстом или /cancel для отмены.")
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    minutes = data.get("minutes")
    if not target_user_id or not minutes:
        await message.answer("❌ Ошибка: данные мута потеряны.")
        await state.clear()
        return

    reason = message.text.strip()
    if reason.lower() == "/skip":
        reason = ""

    mute_until = (datetime.now() + timedelta(minutes=minutes)).timestamp()
    muted_users[target_user_id] = mute_until
    await save_muted()

    notification = f"⚠️ <b>Внимание!</b>\n\nАдминистрация ограничила вашу возможность отправлять сообщения на <b>{minutes} минут</b>."
    if reason:
        notification += f"\n<b>Причина:</b> {esc(reason)}"

    try:
        await message.bot.send_message(target_user_id, notification, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Не удалось уведомить о муте {target_user_id}: {e}")

    await message.answer(
        f"✅ Пользователь <code>{target_user_id}</code> замучен на {minutes} мин.\n"
        f"<b>Причина:</b> {esc(reason) if reason else 'не указана'}",
        parse_mode=ParseMode.HTML
    )
    await state.clear()

@moderation_router.callback_query(F.data.startswith("unmute_"))
async def unmute_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет доступа")
    if callback.message is None:
        return await callback.answer("Сообщение недоступно", show_alert=True)
    try:
        target_user_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        return await callback.answer("❌ Некорректный ID", show_alert=True)

    if target_user_id in muted_users:
        muted_users.pop(target_user_id, None)
        await save_muted()
        try:
            await callback.bot.send_message(
                target_user_id,
                "✅ <b>Хорошие новости!</b>\n\nОграничение на отправку сообщений снято. Вы снова можете писать.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logging.error(f"Не удалось уведомить о размуте {target_user_id}: {e}")
        try:
            await callback.message.edit_text(f"✅ Пользователь <code>{target_user_id}</code> размучен.", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    else:
        try:
            await callback.message.edit_text("ℹ️ Пользователь не в муте.", parse_mode=ParseMode.HTML)
        except Exception:
            pass
    await callback.answer("Готово")