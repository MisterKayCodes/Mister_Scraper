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

    from services.queue_worker import get_rate_limit_status
    rl_status = get_rate_limit_status()
    if rl_status.get("is_limited") and rl_status.get("free_at"):
        now = now_wat()
        remaining_secs = int((rl_status["free_at"] - now).total_seconds())
        if remaining_secs > 0:
            error_display = f"⚠️ Rate Limited (Free in {remaining_secs // 60}m {remaining_secs % 60}s) ⏳"

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

def format_queue_preview(pending_items: list, target_username: str) -> str:
    """Renders a readable summary of items waiting in queue to be delivered."""
    if not pending_items:
        return ""
    lines = [f"\n\n📬 <b>Delivery Queue ({len(pending_items)} pending):</b>"]
    for i, item in enumerate(pending_items[:5], 1):
        lines.append(f"{i}. <code>x.com/{target_username}/status/{item.content_id}</code>")
    if len(pending_items) > 5:
        lines.append(f"<i>...and {len(pending_items) - 5} more queued</i>")
    return "\n".join(lines)

@router.message(F.text == "📋 Active Sources")
async def btn_active_sources(message: types.Message, state: FSMContext):
    await state.clear()
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
        async with AsyncSessionLocal() as session:
            pending = await Repository.get_pending_items(session, message.from_user.id, "x")
        queue_text = format_queue_preview(pending, src.target)
        await message.answer(
            format_source_diagnostic_card(src) + queue_text,
            reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=len(pending) > 0),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("src_refresh:"))
async def cb_refresh_source(callback: types.CallbackQuery):
    """Instant local refresh: queries DB without network/browser, recalculates stats & queue."""
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()
        pending = await Repository.get_pending_items(session, callback.from_user.id, "x")

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    await callback.answer("🔄 Card refreshed")
    queue_text = format_queue_preview(pending, src.target)
    await callback.message.edit_text(
        format_source_diagnostic_card(src) + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=len(pending) > 0),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("src_toggle:"))
async def cb_toggle_source(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        src = await Repository.toggle_source(session, source_id, callback.from_user.id)
        pending = await Repository.get_pending_items(session, callback.from_user.id, "x")

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    status_label = "Resumed ▶️" if src.is_active else "Paused ⏸️"
    await callback.answer(f"Feed @{src.target} is now {status_label}")
    queue_text = format_queue_preview(pending, src.target)
    await callback.message.edit_text(
        format_source_diagnostic_card(src) + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=len(pending) > 0),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("src_check:"))
async def cb_check_source_now(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    await callback.answer("⏳ Triggered radar scan...")

    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()

    if not src:
        await callback.message.reply("❌ Source not found.")
        return

    # Visual in-message feedback while scanning
    await callback.message.edit_text(
        format_source_diagnostic_card(src) + f"\n\n🔍 <i>Scanning @{src.target} for new posts via stealth radar...</i>",
        parse_mode="HTML"
    )

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

            # Reverse links: deliver oldest to newest so channel narrative is chronological
            chronological_links = list(reversed(links))
            for link in chronological_links:
                tid = link.split("?")[0].rstrip("/").split("/")[-1]
                if not await Repository.is_duplicate(session, src.user_id, "x", tid):
                    await Repository.mark_as_discovered(session, src.user_id, "x", tid)
                    await conveyor_queue.put((link, src.user_id, src.id, src.destination_channel_id, sig, f_mode))
                    new_count += 1

            # Fetch fresh pending items
            pending = await Repository.get_pending_items(session, callback.from_user.id, "x")

        # Reload fresh card after scan
        async with AsyncSessionLocal() as session:
            res = await session.execute(stmt)
            src = res.scalar_one_or_none()
            if src:
                result_note = f"\n\n✅ <b>Radar Scan Complete:</b> Found {len(links)} posts, queued <b>{new_count} new</b> for delivery!"
                queue_text = format_queue_preview(pending, src.target)
                await callback.message.edit_text(
                    format_source_diagnostic_card(src) + result_note + queue_text,
                    reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=len(pending) > 0),
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"[CHECK_NOW] Error scanning @{src.target}: {e}")
        await callback.message.edit_text(
            format_source_diagnostic_card(src) + f"\n\n❌ <b>Scan Error:</b> <code>{str(e)[:100]}</code>",
            reply_markup=get_source_item_kb(src.id, src.is_active),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("src_deep_prompt:"))
async def cb_deep_harvest_prompt(callback: types.CallbackQuery):
    """Prompts user to select post count for Deep Harvest."""
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    from bot.keyboards import get_deep_harvest_limits_kb
    prompt_text = (
        f"🚀 <b>Deep Harvest & Archive: @{src.target}</b>\n\n"
        "How many media posts would you like the <b>Link Hunter</b> to gather?\n\n"
        "<i>The Hunter will scroll continuously, capturing original posts and retweets, and save them into the queue. The browser will then close, and the Delivery Engine will safely post them to your channel!</i>"
    )
    await callback.message.edit_text(prompt_text, reply_markup=get_deep_harvest_limits_kb(source_id), parse_mode="HTML")

@router.callback_query(F.data.startswith("src_deep_run:"))
async def cb_deep_harvest_run(callback: types.CallbackQuery):
    """Executes continuous Link Hunter Playwright session and queues links into seen_items."""
    parts = callback.data.split(":")
    source_id = int(parts[1])
    requested_limit = int(parts[2])

    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    await callback.answer("🚀 Initializing Link Hunter...")
    status_card = await callback.message.edit_text(
        f"🚀 <b>Link Hunter Active: @{src.target}</b>\n\n"
        f"🎯 Target limit: <b>{requested_limit} posts</b>\n"
        "🌐 <i>Launching stealth Chromium...</i>",
        parse_mode="HTML"
    )

    async def hunter_status(status_text: str):
        try:
            await callback.message.edit_text(
                f"🚀 <b>Link Hunter Active: @{src.target}</b>\n\n"
                f"🎯 Target: <b>{requested_limit} posts</b>\n"
                f"{status_text}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    from features.x.scraper import scrape_profile_media
    from services.queue_worker import conveyor_queue

    try:
        # Phase 1: Link Hunter runs Playwright with continuous scroll
        links = await scrape_profile_media(
            username=src.target,
            limit=requested_limit,
            status_callback=hunter_status
        )

        async with AsyncSessionLocal() as session:
            settings = await Repository.get_or_create_settings(session, callback.from_user.id)
            sig = settings.custom_signature or ""
            f_mode = settings.filter_mode if settings.filter_mode is not None else 1

            # Create HarvestTask to track bulk archival run
            task = await Repository.create_harvest_job(
                session=session,
                user_id=callback.from_user.id,
                source_profile=src.target,
                destination_channel_id=src.destination_channel_id
            )

            # Insert discovered items into DB queue
            items_payload = []
            for idx, link in enumerate(reversed(links), start=1):
                tid = link.split("?")[0].rstrip("/").split("/")[-1]
                items_payload.append({
                    "id": tid,
                    "url": link,
                    "is_repost": False,
                    "position": idx
                })

            new_inserted = await Repository.bulk_insert_discovered_links(
                session=session,
                task_id=task.id,
                user_id=callback.from_user.id,
                source_profile=src.target,
                items=items_payload
            )

            # Queue them into conveyor for paced delivery
            for item in items_payload:
                if not await Repository.is_duplicate(session, src.user_id, "x", item["id"]):
                    await conveyor_queue.put((
                        item["url"],
                        src.user_id,
                        src.id,
                        src.destination_channel_id,
                        sig,
                        f_mode
                    ))

            pending = await Repository.get_pending_items(session, callback.from_user.id, "x")

        # Browser closed completely! Delivery engine now takes over
        summary_text = (
            f"✅ <b>Link Hunter Finished! Browser Closed.</b>\n\n"
            f"🎯 Total Captured: <b>{len(links)} posts</b>\n"
            f"📦 Newly Queued: <b>{new_inserted} posts</b>\n"
            f"🚀 Destination: <code>{src.destination_channel_id}</code>\n\n"
            "<i>The pure HTTP Delivery Engine is now drip-feeding these posts to your channel with human anti-ban pacing!</i>"
        )
        queue_text = format_queue_preview(pending, src.target)
        await callback.message.edit_text(
            format_source_diagnostic_card(src) + f"\n\n{summary_text}" + queue_text,
            reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=len(pending) > 0),
            parse_mode="HTML"
        )

    except Exception as hunt_err:
        logger.error(f"[DEEP_HARVEST] Error: {hunt_err}")
        await callback.message.edit_text(
            format_source_diagnostic_card(src) + f"\n\n❌ <b>Harvest Error:</b> <code>{str(hunt_err)[:100]}</code>",
            reply_markup=get_source_item_kb(src.id, src.is_active),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("src_deliver_next:"))
async def cb_deliver_next_now(callback: types.CallbackQuery):
    """Manually triggers delivery of the oldest pending item immediately."""
    source_id = int(callback.data.split(":")[1])
    await callback.answer("🚀 Delivering next queued item...")

    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()
        pending = await Repository.get_pending_items(session, callback.from_user.id, "x", limit=1)

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    if not pending:
        await callback.answer("Queue is empty! All items delivered.", show_alert=True)
        return

    item_to_deliver = pending[0]
    tweet_url = f"https://x.com/{src.target}/status/{item_to_deliver.content_id}"

    # Visual in-message update
    await callback.message.edit_text(
        format_source_diagnostic_card(src) + f"\n\n🚀 <i>Processing & delivering post: {item_to_deliver.content_id}...</i>",
        parse_mode="HTML"
    )

    from services.queue_worker import process_queue_item
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        sig = settings.custom_signature or ""
        f_mode = settings.filter_mode if settings.filter_mode is not None else 1

    queue_tuple = (tweet_url, src.user_id, src.id, src.destination_channel_id, sig, f_mode)
    await process_queue_item(callback.bot, queue_tuple)

    # Reload fresh card and remaining pending queue
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == callback.from_user.id)
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()
        remaining = await Repository.get_pending_items(session, callback.from_user.id, "x")

    queue_text = format_queue_preview(remaining, src.target)
    await callback.message.edit_text(
        format_source_diagnostic_card(src) + f"\n\n✅ <b>Delivered post {item_to_deliver.content_id} to {src.destination_channel_id}!</b>" + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=len(remaining) > 0),
        parse_mode="HTML"
    )

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


