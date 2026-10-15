"""
sync_flow.py — FSM wizard for adding a new Auto-Sync source.

Responsibility: ONE thing only — collect username + interval from the user
and persist a new ScheduledSource row. All other source management lives in
source_manager.py and deep_harvest.py.
"""
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from loguru import logger

from data.database import AsyncSessionLocal
from data.repository import Repository
from bot.states import SyncStates
from core.media_resolver import extract_x_username
from bot.keyboards import get_interval_selection_kb

router = Router(name="sync_router")


@router.message(F.text == "🚀 Auto-Sync Channel")
async def btn_auto_sync(message: types.Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)

    if not settings.destination_channel_id:
        await message.answer(
            "⚠️ <b>Setup Required First:</b>\n\n"
            "Please link your destination channel before adding an auto-sync target.\n"
            "Tap <b>'⚙️ Channel &amp; Branding'</b> below to set it up in 10 seconds!",
            parse_mode="HTML"
        )
        return

    await state.set_state(SyncStates.waiting_for_target)
    logger.info(f"[SYNC] User {message.from_user.id} initiated Auto-Sync setup.")
    await message.answer(
        "🚀 <b>Auto-Sync Setup (Link X Profile)</b>\n\n"
        "Send the X (Twitter) profile you want to clone:\n"
        "<i>Accepts: @username, https://x.com/username, or https://x.com/username/media</i>",
        parse_mode="HTML"
    )


@router.message(SyncStates.waiting_for_target)
async def process_target_username(message: types.Message, state: FSMContext):
    raw_input = message.text.strip()
    target = extract_x_username(raw_input)
    logger.info(f"[SYNC] User {message.from_user.id} submitted target raw='{raw_input}' parsed='{target}'")

    if not target:
        await message.answer("❌ Could not parse username. Please send a valid X profile link or @username:")
        return

    await state.update_data(target=target)
    await state.set_state(SyncStates.waiting_for_interval)

    await message.answer(
        f"🎯 Target Profile: <b>@{target}</b>\n\n"
        "How often should we check for new posts?",
        reply_markup=get_interval_selection_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("sync_int:"))
async def cb_select_interval(callback: types.CallbackQuery, state: FSMContext):
    interval_minutes = int(callback.data.split(":")[1])
    data = await state.get_data()
    target = data.get("target")

    if not target:
        await callback.answer("Session expired. Please start over.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        await Repository.add_scheduled_source(
            session=session,
            user_id=callback.from_user.id,
            target=target,
            destination_channel=settings.destination_channel_id,
            interval_minutes=interval_minutes
        )

    await state.clear()
    await callback.message.edit_text(
        "✅ <b>Auto-Sync Activated!</b>\n\n"
        f"🔗 <b>Source:</b> <code>x.com/{target}</code>\n"
        f"📢 <b>Destination:</b> <code>{settings.destination_channel_id}</code>\n"
        f"⏱️ <b>Interval:</b> Every <b>{interval_minutes} minutes</b>\n\n"
        "The background harvester is actively monitoring this profile. "
        "Tap '📋 Active Sources' anytime to view or manage your pairs.",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "sync_cancel")
async def cb_cancel_sync(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Auto-sync setup cancelled.")
    await callback.answer()
