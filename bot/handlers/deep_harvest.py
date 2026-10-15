"""
deep_harvest.py — Handlers for the two-phase Deep Harvest (Batch Clone) engine.

Phase 1: Link Hunter — Playwright scrolls the full profile and stores all tweet URLs.
Phase 2: Delivery Engine — conveyor_worker drip-feeds stored links to Telegram.

Also handles the manual Deliver Next Now action.
"""
from aiogram import Router, types, F
from loguru import logger

from sqlalchemy import select
from data.database import AsyncSessionLocal
from data.repository import Repository
from data.models import ScheduledSource
from bot.keyboards import get_source_item_kb, get_deep_harvest_limits_kb
from bot.helpers.card_formatters import format_source_diagnostic_card, format_queue_preview

router = Router(name="deep_harvest_router")


@router.callback_query(F.data.startswith("src_deep_prompt:"))
async def cb_deep_harvest_prompt(callback: types.CallbackQuery):
    """Prompts user to select post count for Deep Harvest."""
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    prompt_text = (
        f"🚀 <b>Deep Harvest &amp; Archive: @{src.target}</b>\n\n"
        "How many media posts would you like the <b>Link Hunter</b> to gather?\n\n"
        "<i>The Hunter will scroll continuously, capturing original posts and retweets, "
        "and save them into the queue. The browser will then close, and the Delivery Engine "
        "will safely post them to your channel!</i>"
    )
    await callback.message.edit_text(
        prompt_text,
        reply_markup=get_deep_harvest_limits_kb(source_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("src_deep_run:"))
async def cb_deep_harvest_run(callback: types.CallbackQuery):
    """Executes continuous Link Hunter Playwright session and queues links into seen_items."""
    parts = callback.data.split(":")
    source_id = int(parts[1])
    requested_limit = int(parts[2])

    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    await callback.answer("🚀 Initializing Link Hunter...")
    await callback.message.edit_text(
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
        # Phase 1: Link Hunter — Playwright continuous scroll
        links = await scrape_profile_media(
            username=src.target,
            limit=requested_limit,
            status_callback=hunter_status
        )

        async with AsyncSessionLocal() as session:
            settings = await Repository.get_or_create_settings(session, callback.from_user.id)
            sig = settings.custom_signature or ""
            f_mode = settings.filter_mode if settings.filter_mode is not None else 1

            task = await Repository.create_harvest_job(
                session=session,
                user_id=callback.from_user.id,
                source_profile=src.target,
                destination_channel_id=src.destination_channel_id
            )

            # Build payload: oldest first (reversed = ascending Snowflake)
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

            # Phase 2: Hand-off to Delivery Engine — queue non-duplicates
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
            total_pending = await Repository.get_pending_count(session, callback.from_user.id, "x")
            total_failed = await Repository.get_failed_count(session, callback.from_user.id, "x")

        summary_text = (
            f"✅ <b>Link Hunter Finished! Browser Closed.</b>\n\n"
            f"🎯 Total Captured: <b>{len(links)} posts</b>\n"
            f"📦 Newly Queued: <b>{new_inserted} posts</b>\n"
            f"🚀 Destination: <code>{src.destination_channel_id}</code>\n\n"
            "<i>The pure HTTP Delivery Engine is now drip-feeding these posts to your channel with human anti-ban pacing!</i>"
        )
        queue_text = format_queue_preview(pending, src.target, total_count=total_pending)
        await callback.message.edit_text(
            format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_pending) + f"\n\n{summary_text}" + queue_text,
            reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_pending > 0),
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
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
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

    await callback.message.edit_text(
        format_source_diagnostic_card(src) + f"\n\n🚀 <i>Processing &amp; delivering post: {item_to_deliver.content_id}...</i>",
        parse_mode="HTML"
    )

    from services.queue_worker import process_queue_item
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        sig = settings.custom_signature or ""
        f_mode = settings.filter_mode if settings.filter_mode is not None else 1

    queue_tuple = (tweet_url, src.user_id, src.id, src.destination_channel_id, sig, f_mode)
    await process_queue_item(callback.bot, queue_tuple)

    # Reload fresh card
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()
        remaining = await Repository.get_pending_items(session, callback.from_user.id, "x")
        total_remaining = await Repository.get_pending_count(session, callback.from_user.id, "x")
        total_failed = await Repository.get_failed_count(session, callback.from_user.id, "x")

    queue_text = format_queue_preview(remaining, src.target, total_count=total_remaining)
    await callback.message.edit_text(
        format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_remaining) + f"\n\n✅ <b>Delivered post {item_to_deliver.content_id} to {src.destination_channel_id}!</b>" + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_remaining > 0),
        parse_mode="HTML"
    )
