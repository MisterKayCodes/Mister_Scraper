import asyncio
import html
from typing import Optional, Dict, List
from pathlib import Path
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from loguru import logger

import config
from core.text_cleaner import MessageCleaner
from core.media_resolver import sanitize_filename, resolve_extension, extract_status_urls
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter, ScrapedItem
from services.downloader import download_file
from services.telegram_sender import send_media_resilient
from bot.states import QuickGrabStates
from bot.keyboards import get_quick_grab_choice_kb, get_delivery_action_deck_kb

router = Router(name="quick_grab_router")

# Cache to avoid re-requesting metadata twice between preview and delivery
_scraped_cache: Dict[tuple, ScrapedItem] = {}

@router.message(F.text == "⚡ Quick Grab")
async def btn_quick_grab(message: types.Message, state: FSMContext):
    await state.set_state(QuickGrabStates.waiting_for_link)
    await message.answer(
        "⚡ <b>Quick Grab</b>\n\n"
        "Paste any X (Twitter) post link — or drop <b>multiple links</b> at once:\n"
        "<i>e.g. https://x.com/username/status/123456789</i>",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "qg_next")
async def cb_quick_grab_next(callback: types.CallbackQuery, state: FSMContext):
    """One-tap prompt when user clicks 'Grab Another Link'."""
    await state.set_state(QuickGrabStates.waiting_for_link)
    await callback.answer()
    await callback.message.reply(
        "⚡ <b>Ready!</b> Paste your next X post link (or multiple links) below 👇",
        parse_mode="HTML"
    )

@router.message(QuickGrabStates.waiting_for_link)
@router.message(F.text.regexp(r'https?://(?:(?:www\.)?x\.com|(?:www\.)?twitter\.com)/[A-Za-z0-9_]+/status/\d+'))
async def process_x_links(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    raw_text = message.text.strip()
    urls = extract_status_urls(raw_text)

    if not urls:
        await message.answer("❌ No valid X status links detected. Please paste a valid post link.")
        return

    # Check user branding settings
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)

    sig = settings.custom_signature or ""
    f_mode = settings.filter_mode if settings.filter_mode is not None else 1
    has_channel = bool(settings.destination_channel_id)

    # -------------------------------------------------------------
    # CASE 1: Single Link Drop (Interactive preview + fast delivery)
    # -------------------------------------------------------------
    if len(urls) == 1:
        url = urls[0]
        logger.info(f"[QUICK_GRAB] Single link received from User {message.from_user.id}: {url}")
        status_msg = await message.answer("🔍 <i>Fetching X content...</i>", parse_mode="HTML")

        scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
        if not scraped or not scraped.media_list:
            logger.warning(f"[QUICK_GRAB] No media found for {url}")
            await status_msg.edit_text("❌ <b>No media found</b> in this post (or link is private/deleted).", parse_mode="HTML")
            return

        _scraped_cache[(message.from_user.id, url)] = scraped
        clean_caption = MessageCleaner.clean(scraped.caption, mode=f_mode, signature=sig)
        await state.update_data(url=url, caption=clean_caption, author=scraped.author)

        card = (
            f"🎯 <b>Post from @{scraped.author}</b>\n\n"
            f"<b>Cleaned Caption:</b>\n<i>{clean_caption[:300]}</i>\n\n"
            f"📦 Media items: <b>{len(scraped.media_list)}</b>\n\n"
            "Where would you like me to send this?"
        )
        await status_msg.edit_text(card, reply_markup=get_quick_grab_choice_kb(url), parse_mode="HTML")
        return

    # -------------------------------------------------------------
    # CASE 2: Multi-Link Batch Drop ("One Tap, Many Work")
    # -------------------------------------------------------------
    total_count = len(urls)
    logger.info(f"[QUICK_GRAB] Batch drop of {total_count} links from User {message.from_user.id}")
    status_msg = await message.answer(
        f"⚡ <b>Batch Grab Initiated ({total_count} posts)</b>\n\n"
        f"⏳ Processing item 1 of {total_count}...",
        parse_mode="HTML"
    )

    delivered_count = 0
    last_author = ""

    for idx, u in enumerate(urls, start=1):
        try:
            await status_msg.edit_text(
                f"⚡ <b>Batch Grab ({total_count} posts)</b>\n\n"
                f"⏳ Downloading & delivering {idx}/{total_count}...",
                parse_mode="HTML"
            )
        except Exception:
            pass

        scraped = await asyncio.to_thread(XAdapter.get_single_post, u)
        if not scraped or not scraped.media_list:
            logger.warning(f"[BATCH] Skipping {u} (no media or error)")
            continue

        last_author = scraped.author
        clean_cap = MessageCleaner.clean(scraped.caption, mode=f_mode, signature=sig)

        ok = await deliver_media(
            bot=bot,
            target_chat=message.from_user.id,
            url=u,
            caption=clean_cap,
            status_msg=None, # keep batch status_msg clean
            scraped=scraped
        )
        if ok:
            delivered_count += 1

        # Gentle 1s jitter between batch items
        if idx < total_count:
            await asyncio.sleep(1.0)

    # Attach follow-up action deck to the batch summary
    deck_kb = get_delivery_action_deck_kb(
        author=last_author,
        can_repost=has_channel,
        url=urls[0] if urls else ""
    )
    await status_msg.edit_text(
        f"✅ <b>Batch Delivery Complete!</b>\n\n"
        f"📦 Successfully delivered <b>{delivered_count} of {total_count}</b> posts to your chat.\n\n"
        "<i>Tap below to grab another or auto-sync:</i>",
        reply_markup=deck_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "qg_send_me")
async def cb_send_to_me(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    url = data.get("url")
    if not url:
        await callback.answer("Session expired. Please paste the link again.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text("⏳ <i>Downloading and delivering to your chat...</i>", parse_mode="HTML")
    
    cached_scraped = _scraped_cache.pop((callback.from_user.id, url), None)
    author = data.get("author", "")
    
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
    has_channel = bool(settings.destination_channel_id)

    success = await deliver_media(bot, callback.from_user.id, url, data.get("caption", ""), status_msg=callback.message, scraped=cached_scraped)

    deck_kb = get_delivery_action_deck_kb(author=author, can_repost=has_channel, url=url)
    if success:
        try:
            await callback.message.edit_text("✅ <b>Delivered!</b> Enjoy your media.", reply_markup=deck_kb, parse_mode="HTML")
        except Exception:
            pass
    else:
        try:
            await callback.message.edit_text("❌ <b>Delivery failed.</b> Could not deliver media to chat.", reply_markup=deck_kb, parse_mode="HTML")
        except Exception:
            pass

@router.callback_query(F.data == "qg_post_channel")
async def cb_post_to_channel(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)

    if not settings.destination_channel_id:
        await callback.answer("⚠️ Please link a destination channel first in 'Channel & Branding'!", show_alert=True)
        return

    data = await state.get_data()
    url = data.get("url")
    if not url:
        await callback.answer("Session expired. Please paste the link again.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(f"⏳ <i>Posting to channel {settings.destination_channel_id}...</i>", parse_mode="HTML")
    
    cached_scraped = _scraped_cache.pop((callback.from_user.id, url), None)
    author = data.get("author", "")
    success = await deliver_media(bot, settings.destination_channel_id, url, data.get("caption", ""), status_msg=callback.message, scraped=cached_scraped)
    
    deck_kb = get_delivery_action_deck_kb(author=author, can_repost=False, url=url)
    if success:
        await callback.message.edit_text(f"✅ <b>Successfully posted</b> to <code>{settings.destination_channel_id}</code>!", reply_markup=deck_kb, parse_mode="HTML")
    else:
        await callback.message.edit_text(f"❌ <b>Delivery failed.</b> Make sure the bot is an Admin in <code>{settings.destination_channel_id}</code>.", reply_markup=deck_kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("qg_sync_author:"))
async def cb_quick_sync_author(callback: types.CallbackQuery, state: FSMContext):
    """1-Tap shortcut to initiate Auto-Sync for the author of a delivered post."""
    author = callback.data.split(":")[1]
    
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        
    if not settings.destination_channel_id:
        await callback.answer("⚠️ Please link a destination channel first in '⚙️ Channel & Branding'!", show_alert=True)
        return

    from bot.states import SyncStates
    from bot.keyboards import get_interval_selection_kb

    await state.update_data(target=author)
    await state.set_state(SyncStates.waiting_for_interval)
    await callback.answer()
    
    await callback.message.reply(
        f"🎯 <b>Auto-Sync Setup: @{author}</b>\n\n"
        f"📢 Destination: <code>{settings.destination_channel_id}</code>\n\n"
        "How often should we check for new posts?",
        reply_markup=get_interval_selection_kb(),
        parse_mode="HTML"
    )

async def deliver_media(
    bot: Bot,
    target_chat: any,
    url: str,
    caption: str,
    status_msg: Optional[types.Message] = None,
    scraped: Optional[ScrapedItem] = None
) -> bool:
    """Delivers media directly to user DM or channel with real-time throttled progress and resilient fallback."""
    if not scraped:
        scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
    
    if not scraped or not scraped.media_list:
        logger.error(f"[DELIVER] Failed to retrieve media list for {url}")
        return False

    safe_caption = html.escape(caption)[:1024]
    overall_success = False

    for i, media in enumerate(scraped.media_list):
        m_url = media.get("url")
        m_type = media.get("type", "image")
        
        ok = await send_media_resilient(
            bot=bot,
            target_chat=target_chat,
            media_url=m_url,
            media_type=m_type,
            caption=safe_caption,
            status_msg=status_msg
        )
        if ok:
            overall_success = True

    return overall_success
