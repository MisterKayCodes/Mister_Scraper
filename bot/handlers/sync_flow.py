from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from loguru import logger

from sqlalchemy import select
from data.database import AsyncSessionLocal
from data.repository import Repository
from data.models import ScheduledSource
from bot.states import SyncStates
from core.media_resolver import extract_x_username
from bot.keyboards import get_interval_selection_kb, get_source_item_kb

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
            "Tap <b>'⚙️ Channel & Branding'</b> below to set it up in 10 seconds!",
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
        "The background harvester is actively monitoring this profile. Tap '📋 Active Sources' anytime to view or manage your pairs.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "sync_cancel")
async def cb_cancel_sync(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Auto-sync setup cancelled.")
    await callback.answer()

# ----------------- Active Sources / Pair Manager -----------------

from datetime import datetime
from core.time_utils import now_wat

def format_source_diagnostic_card(src) -> str:
    """Renders the Mister_Channels gold-standard diagnostic feed card."""
    status = "ACTIVE ✅" if src.is_active else "PAUSED ⏸️"
    
    # Calculate countdown
    countdown_str = "Calculating..."
    if src.next_check:
        now = now_wat()
        if src.next_check > now:
            diff = src.next_check - now
            mins = int(diff.total_seconds() // 60)
            if mins > 60:
                countdown_str = f"In {mins // 60}h {mins % 60}m"
            else:
                countdown_str = f"In {mins} minutes"
        else:
            countdown_str = "Checking soon ⏳"

    # Format interval nicely
    interval_display = f"{src.interval_minutes} mins"
    if src.interval_minutes >= 60:
        hrs = src.interval_minutes / 60
        interval_display = f"{int(hrs) if hrs.is_integer() else hrs} hours"

    error_display = f"<code>{src.last_error}</code>" if src.last_error and src.last_error != "None (Healthy)" else "None (Healthy) 🟢"

    card = (
        f"🔁 <b>Scraper Feed: @{src.target} ➔ {src.destination_channel_id}</b>\n"
        "───────────────────────────\n"
        f"⚡ <b>Status:</b> {status}\n"
        f"🔗 <b>Source:</b> <code>x.com/{src.target}</code>\n"
        f"📢 <b>Destination:</b> <code>{src.destination_channel_id}</code>\n"
        f"⏱️ <b>Interval:</b> Every {interval_display}\n"
        f"⏳ <b>Next Check:</b> {countdown_str}\n"
        f"📦 <b>Delivered:</b> {src.total_delivered or 0} items\n"
        f"⚠️ <b>Last Error:</b> {error_display}\n"
        "───────────────────────────"
    )
    return card

@router.message(F.text == "📋 Active Sources")
async def btn_active_sources(message: types.Message):
    async with AsyncSessionLocal() as session:
        sources = await Repository.get_user_sources(session, message.from_user.id)

    if not sources:
        await message.answer(
            "📋 <b>Active Cloning Pairs</b>\n\n"
            "You have no active X targets linked yet.\n"
            "Tap <b>'🚀 Auto-Sync Channel'</b> to link your first X profile!",
            parse_mode="HTML"
        )
        return

    await message.answer(f"📋 <b>Your Active Sources ({len(sources)}):</b>\nManage your cloning pipelines below:", parse_mode="HTML")

    for src in sources:
        await message.answer(format_source_diagnostic_card(src), reply_markup=get_source_item_kb(src.id, src.is_active), parse_mode="HTML")

@router.callback_query(F.data.startswith("src_toggle:"))
async def cb_toggle_source(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        src = await Repository.toggle_source(session, source_id, callback.from_user.id)

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    status_label = "Resumed ▶️" if src.is_active else "Paused ⏸️"
    await callback.answer(f"Feed @{src.target} is now {status_label}")
    await callback.message.edit_text(format_source_diagnostic_card(src), reply_markup=get_source_item_kb(src.id, src.is_active), parse_mode="HTML")

@router.callback_query(F.data.startswith("src_check:"))
async def cb_check_source_now(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    await callback.answer("⏳ Scanning now...")  # Only ONE answer per callback query

    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()

    if not src:
        await callback.message.reply("❌ Source not found.")
        return

    # Trigger scan immediately
    from features.x.adapter import XAdapter
    from services.queue_worker import conveyor_queue

    try:
        links = await XAdapter.get_profile_posts(src.target, limit=5)
        new_count = 0
        async with AsyncSessionLocal() as session:
            settings = await Repository.get_or_create_settings(session, callback.from_user.id)
            sig = settings.custom_signature or ""
            f_mode = settings.filter_mode if settings.filter_mode is not None else 1

            for link in links:
                tid = link.split("?")[0].rstrip("/").split("/")[-1]
                if not await Repository.is_duplicate(session, src.user_id, "x", tid):
                    await Repository.mark_as_discovered(session, src.user_id, "x", tid)
                    await conveyor_queue.put((link, src.user_id, src.id, src.destination_channel_id, sig, f_mode))
                    new_count += 1

        # Reload fresh card after scan
        async with AsyncSessionLocal() as session:
            res = await session.execute(stmt)
            src = res.scalar_one_or_none()
            if src:
                result_note = f"\n\n✅ <b>Manual check done:</b> {new_count} new post(s) queued."
                await callback.message.edit_text(
                    format_source_diagnostic_card(src) + result_note,
                    reply_markup=get_source_item_kb(src.id, src.is_active),
                    parse_mode="HTML"
                )

    except Exception as e:
        await callback.message.reply(f"❌ Scan failed: {str(e)[:100]}")

@router.callback_query(F.data.startswith("src_del:"))
async def cb_delete_source(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        deleted = await Repository.delete_source(session, source_id, callback.from_user.id)

    if deleted:
        await callback.answer("🗑️ Source unlinked.")
        await callback.message.edit_text("🗑️ <i>This scraper feed was unlinked.</i>", parse_mode="HTML")
    else:
        await callback.answer("Could not delete source.", show_alert=True)

