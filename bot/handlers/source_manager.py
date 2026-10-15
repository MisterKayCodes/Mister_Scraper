"""
source_manager.py — Handlers for the Active Sources diagnostic card.

Covers: list sources, view card, refresh, toggle pause, manual check now,
        back-to-list navigation, and delete source.
"""
from aiogram import Router, types, F
from loguru import logger

from sqlalchemy import select
from data.database import AsyncSessionLocal
from data.repository import Repository
from data.models import ScheduledSource
from bot.keyboards import get_source_item_kb, get_sources_selector_kb
from bot.helpers.card_formatters import format_source_diagnostic_card, format_queue_preview

router = Router(name="source_manager_router")


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

    if len(sources) > 1:
        await message.answer(
            f"📋 <b>Your Active Sources ({len(sources)}):</b>\n"
            "Tap a source below to manage its cloning pipeline, check queue, or Deep Harvest:",
            reply_markup=get_sources_selector_kb(sources),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"📋 <b>Your Active Sources ({len(sources)}):</b>\nManage your cloning pipelines below:",
            parse_mode="HTML"
        )
        for src in sources:
            async with AsyncSessionLocal() as session:
                pending = await Repository.get_pending_items(session, message.from_user.id, "x")
                total_pending = await Repository.get_pending_count(session, message.from_user.id, "x")
                total_failed = await Repository.get_failed_count(session, message.from_user.id, "x")
            queue_text = format_queue_preview(pending, src.target, total_count=total_pending)
            await message.answer(
                format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_pending) + queue_text,
                reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_pending > 0),
                parse_mode="HTML"
            )


@router.callback_query(F.data == "src_back_to_list")
async def cb_src_back_to_list(callback: types.CallbackQuery):
    """Returns user to the inline source selector from inside a diagnostic card."""
    async with AsyncSessionLocal() as session:
        sources = await Repository.get_user_sources(session, callback.from_user.id)

    await callback.answer()
    if not sources:
        await callback.message.edit_text("📋 No active sources found.", parse_mode="HTML")
        return

    await callback.message.edit_text(
        f"📋 <b>Your Active Sources ({len(sources)}):</b>\n"
        "Tap a source below to manage its cloning pipeline, check queue, or Deep Harvest:",
        reply_markup=get_sources_selector_kb(sources),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("src_view:"))
async def cb_view_source(callback: types.CallbackQuery):
    """Opens the detailed diagnostic card when a source is selected from the inline list."""
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()
        pending = await Repository.get_pending_items(session, callback.from_user.id, "x")
        total_pending = await Repository.get_pending_count(session, callback.from_user.id, "x")
        total_failed = await Repository.get_failed_count(session, callback.from_user.id, "x")

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    await callback.answer()
    queue_text = format_queue_preview(pending, src.target, total_count=total_pending)
    await callback.message.edit_text(
        format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_pending) + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_pending > 0, has_multiple_sources=True),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("src_refresh:"))
async def cb_refresh_source(callback: types.CallbackQuery):
    """Instant local refresh: queries DB without network/browser, recalculates stats & queue."""
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
        res = await session.execute(stmt)
        src = res.scalar_one_or_none()
        pending = await Repository.get_pending_items(session, callback.from_user.id, "x")
        total_pending = await Repository.get_pending_count(session, callback.from_user.id, "x")
        total_failed = await Repository.get_failed_count(session, callback.from_user.id, "x")

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    await callback.answer("🔄 Card refreshed")
    queue_text = format_queue_preview(pending, src.target, total_count=total_pending)
    await callback.message.edit_text(
        format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_pending) + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_pending > 0),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("src_toggle:"))
async def cb_toggle_source(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        src = await Repository.toggle_source(session, source_id, callback.from_user.id)
        pending = await Repository.get_pending_items(session, callback.from_user.id, "x")
        total_pending = await Repository.get_pending_count(session, callback.from_user.id, "x")
        total_failed = await Repository.get_failed_count(session, callback.from_user.id, "x")

    if not src:
        await callback.answer("Source not found.", show_alert=True)
        return

    status_label = "Resumed ▶️" if src.is_active else "Paused ⏸️"
    await callback.answer(f"Feed @{src.target} is now {status_label}")
    queue_text = format_queue_preview(pending, src.target, total_count=total_pending)
    await callback.message.edit_text(
        format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_pending) + queue_text,
        reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_pending > 0),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("src_check:"))
async def cb_check_source_now(callback: types.CallbackQuery):
    source_id = int(callback.data.split(":")[1])
    await callback.answer("⏳ Triggered radar scan...")

    async with AsyncSessionLocal() as session:
        stmt = select(ScheduledSource).where(
            ScheduledSource.id == source_id,
            ScheduledSource.user_id == callback.from_user.id
        )
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

    from features.x.adapter import XAdapter
    from services.queue_worker import conveyor_queue

    try:
        links = await XAdapter.get_profile_posts(src.target, limit=5)
        new_count = 0
        async with AsyncSessionLocal() as session:
            settings = await Repository.get_or_create_settings(session, callback.from_user.id)
            sig = settings.custom_signature or ""
            f_mode = settings.filter_mode if settings.filter_mode is not None else 1

            chronological_links = list(reversed(links))
            for link in chronological_links:
                tid = link.split("?")[0].rstrip("/").split("/")[-1]
                if not await Repository.is_duplicate(session, src.user_id, "x", tid):
                    await Repository.mark_as_discovered(session, src.user_id, "x", tid)
                    await conveyor_queue.put((link, src.user_id, src.id, src.destination_channel_id, sig, f_mode))
                    new_count += 1

            pending = await Repository.get_pending_items(session, callback.from_user.id, "x")
            total_pending = await Repository.get_pending_count(session, callback.from_user.id, "x")
            total_failed = await Repository.get_failed_count(session, callback.from_user.id, "x")

        # Reload fresh card after scan
        async with AsyncSessionLocal() as session:
            res = await session.execute(stmt)
            src = res.scalar_one_or_none()
            if src:
                result_note = f"\n\n✅ <b>Radar Scan Complete:</b> Found {len(links)} posts, queued <b>{new_count} new</b> for delivery!"
                queue_text = format_queue_preview(pending, src.target, total_count=total_pending)
                await callback.message.edit_text(
                    format_source_diagnostic_card(src, failed_count=total_failed, pending_count=total_pending) + result_note + queue_text,
                    reply_markup=get_source_item_kb(src.id, src.is_active, has_pending=total_pending > 0),
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"[CHECK_NOW] Error scanning @{src.target}: {e}")
        await callback.message.edit_text(
            format_source_diagnostic_card(src) + f"\n\n❌ <b>Scan Error:</b> <code>{str(e)[:100]}</code>",
            reply_markup=get_source_item_kb(src.id, src.is_active),
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
