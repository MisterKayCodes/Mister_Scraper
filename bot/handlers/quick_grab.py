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

# Known main menu buttons that should always interrupt and escape FSM states
MENU_BUTTONS = {
    "🚀 Auto-Sync Channel",
    "⚡ Quick Grab",
    "📋 Active Sources",
    "⚙️ Channel & Branding",
    "/start"
}

@router.message(QuickGrabStates.waiting_for_link, F.text.in_(MENU_BUTTONS))
async def cancel_quick_grab_on_menu(message: types.Message, state: FSMContext):
    """If user clicks any main menu button while in Quick Grab state, clear state and let router delegate."""
    await state.clear()
    # Aiogram will re-dispatch or handlers for menu buttons will catch it if we delegate

@router.message(QuickGrabStates.waiting_for_link)
@router.message(F.text.regexp(r'https?://(?:(?:www\.)?x\.com|(?:www\.)?twitter\.com)/[A-Za-z0-9_]+/status/\d+'))
async def process_x_links(message: types.Message, state: FSMContext, bot: Bot):
    # Guard: If user sent a main menu button, ignore it here so the menu handler executes
    if message.text.strip() in MENU_BUTTONS:
        await state.clear()
        return

    raw_text = message.text.strip()
    urls = extract_status_urls(raw_text)

    if not urls:
        await message.answer(
            "⚠️ <b>Please send a valid X (Twitter) post link:</b>\n"
            "<i>e.g. https://x.com/DailyLoud/status/123456789</i>\n\n"
            "Or tap any menu button below to switch.",
            parse_mode="HTML"
        )
        return

    await state.clear()


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
            scraped=scraped,
            user_id=message.from_user.id
        )
        if ok:
            delivered_count += 1

        # Gentle 1s jitter between batch items
        if idx < total_count:
            await asyncio.sleep(1.0)

    # Clean up the old top status message so chat history stays clean
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Send the final action deck as a FRESH message at the very bottom
    last_tid = urls[-1].split("?")[0].rstrip("/").split("/")[-1] if urls else ""
    deck_kb = get_delivery_action_deck_kb(
        author=last_author,
        content_id=last_tid,
        has_channel=has_channel
    )
    await message.answer(
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
    tweet_id = url.split("?")[0].rstrip("/").split("/")[-1]
    
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
    has_channel = bool(settings.destination_channel_id)

    success = await deliver_media(bot, callback.from_user.id, url, data.get("caption", ""), status_msg=callback.message, scraped=cached_scraped, user_id=callback.from_user.id)

    # Stateless action deck: binds directly to tweet_id in Database Vault!
    deck_kb = get_delivery_action_deck_kb(author=author, content_id=tweet_id, has_channel=has_channel)
    
    # Delete the old top preview message and send the action deck at the bottom
    try:
        await callback.message.delete()
    except Exception:
        pass

    if success:
        await callback.message.answer("✅ <b>Delivered!</b> Enjoy your media.", reply_markup=deck_kb, parse_mode="HTML")
    else:
        await callback.message.answer("❌ <b>Delivery failed.</b> Could not deliver media to chat.", reply_markup=deck_kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("qg_repost:"))
async def cb_instant_repost_channel(callback: types.CallbackQuery, bot: Bot):
    """Zero-bandwidth instant forward using Telegram's European datacenter file_id!"""
    tweet_id = callback.data.split(":")[1]
    
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        if not settings.destination_channel_id:
            await callback.answer("⚠️ Link a channel in '⚙️ Channel & Branding' first!", show_alert=True)
            return

        from sqlalchemy import select
        from data.models import SeenItem
        stmt = select(SeenItem).where(SeenItem.user_id == callback.from_user.id, SeenItem.content_id == tweet_id)
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()

    if not item or not item.telegram_file_id:
        await callback.answer("Media copy unavailable in Vault. Please paste the link again.", show_alert=True)
        return

    await callback.answer("⚡ Forwarding to channel instantly...")
    try:
        if item.media_type == "video":
            await bot.send_video(
                chat_id=settings.destination_channel_id,
                video=item.telegram_file_id,
                caption=item.clean_caption or "",
                parse_mode="HTML"
            )
        else:
            await bot.send_photo(
                chat_id=settings.destination_channel_id,
                photo=item.telegram_file_id,
                caption=item.clean_caption or "",
                parse_mode="HTML"
            )
        logger.info(f"[REPOST] Instant 0-byte cloud repost of {tweet_id} to {settings.destination_channel_id}")
        await callback.message.reply(
            f"🚀 <b>Posted instantly</b> to <code>{settings.destination_channel_id}</code>! (0-byte cloud transfer)",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[REPOST] Error forwarding to channel: {e}")
        await callback.message.reply(f"❌ Failed to forward to channel: {e}")

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
    tweet_id = url.split("?")[0].rstrip("/").split("/")[-1]
    success = await deliver_media(bot, settings.destination_channel_id, url, data.get("caption", ""), status_msg=callback.message, scraped=cached_scraped, user_id=callback.from_user.id)
    
    deck_kb = get_delivery_action_deck_kb(author=author, content_id=tweet_id, has_channel=False)
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
    scraped: Optional[ScrapedItem] = None,
    user_id: Optional[int] = None
) -> bool:
    """Delivers media directly to user DM or channel with real-time throttled progress and resilient fallback."""
    if not scraped:
        scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
    
    if not scraped or not scraped.media_list:
        logger.error(f"[DELIVER] Failed to retrieve media list for {url}")
        return False

    safe_caption = html.escape(caption)[:1024]
    tweet_id = url.split("?")[0].rstrip("/").split("/")[-1]
    overall_success = False

    for i, media in enumerate(scraped.media_list):
        m_url = media.get("url")
        m_type = media.get("type", "image")
        
        file_id_or_ok = await send_media_resilient(
            bot=bot,
            target_chat=target_chat,
            media_url=m_url,
            media_type=m_type,
            caption=safe_caption,
            status_msg=status_msg,
            thumbnail_url=media.get("thumbnail_url")
        )
        if file_id_or_ok:
            overall_success = True
            # If user_id provided, record file_id in Database Vault for instant 0-byte forwarding!
            if user_id:
                try:
                    async with AsyncSessionLocal() as session:
                        await Repository.mark_as_completed(
                            session=session,
                            user_id=user_id,
                            platform="x",
                            content_id=tweet_id,
                            telegram_file_id=str(file_id_or_ok) if file_id_or_ok != "SUCCESS" else None,
                            media_type=m_type,
                            clean_caption=safe_caption
                        )
                except Exception as save_err:
                    logger.warning(f"[DELIVER] Could not cache file_id to Vault: {save_err}")

    return overall_success
