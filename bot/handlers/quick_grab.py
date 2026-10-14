import asyncio
import html
from typing import Optional, Dict
from pathlib import Path
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from loguru import logger

import config
from core.text_cleaner import MessageCleaner
from core.media_resolver import sanitize_filename, resolve_extension
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter, ScrapedItem
from services.downloader import download_file
from bot.states import QuickGrabStates
from bot.keyboards import get_quick_grab_choice_kb
from bot.utils.progress import TelegramProgressTracker

router = Router(name="quick_grab_router")

# Cache to avoid re-requesting vxtwitter twice
_scraped_cache: Dict[tuple, ScrapedItem] = {}

@router.message(F.text == "⚡ Quick Grab")
async def btn_quick_grab(message: types.Message, state: FSMContext):
    await state.set_state(QuickGrabStates.waiting_for_link)
    await message.answer(
        "⚡ <b>Quick Grab</b>\n\n"
        "Send me any X (Twitter) post link:\n"
        "<i>e.g. https://x.com/username/status/123456789</i>",
        parse_mode="HTML"
    )

@router.message(QuickGrabStates.waiting_for_link)
@router.message((F.text.contains("x.com/") | F.text.contains("twitter.com/")) & F.text.contains("/status/"))
async def process_x_link(message: types.Message, state: FSMContext):
    await state.clear()
    url = message.text.strip()
    logger.info(f"[QUICK_GRAB] Received post link from User {message.from_user.id}: {url}")
    status_msg = await message.answer("🔍 <i>Fetching X content...</i>", parse_mode="HTML")

    # Fetch using XAdapter
    scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
    if not scraped or not scraped.media_list:
        logger.warning(f"[QUICK_GRAB] No media found for {url}")
        await status_msg.edit_text("❌ <b>No media found</b> in this post (or link is private/deleted).", parse_mode="HTML")
        return

    # Cache metadata for immediate delivery reuse
    _scraped_cache[(message.from_user.id, url)] = scraped

    # Fetch user branding settings
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)

    sig = settings.custom_signature or ""
    f_mode = settings.filter_mode if settings.filter_mode is not None else 1

    clean_caption = MessageCleaner.clean(scraped.caption, mode=f_mode, signature=sig)
    await state.update_data(
        url=url,
        caption=clean_caption,
        author=scraped.author
    )

    card = (
        f"🎯 <b>Post Found from @{scraped.author}</b>\n\n"
        f"<b>Cleaned Caption:</b>\n<i>{clean_caption[:300]}</i>\n\n"
        f"📦 Media items: <b>{len(scraped.media_list)}</b>\n\n"
        "Where would you like me to send this?"
    )

    await status_msg.edit_text(card, reply_markup=get_quick_grab_choice_kb(url), parse_mode="HTML")

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
    success = await deliver_media(bot, callback.from_user.id, url, data.get("caption", ""), status_msg=callback.message, scraped=cached_scraped)

    if success:
        try:
            await callback.message.edit_text("✅ <b>Delivered!</b> Enjoy your media.", parse_mode="HTML")
        except Exception:
            pass
    else:
        try:
            await callback.message.edit_text("❌ <b>Delivery failed.</b> Could not deliver media to chat.", parse_mode="HTML")
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
    success = await deliver_media(bot, settings.destination_channel_id, url, data.get("caption", ""), status_msg=callback.message, scraped=cached_scraped)
    if success:
        await callback.message.edit_text(f"✅ <b>Successfully posted</b> to <code>{settings.destination_channel_id}</code>!", parse_mode="HTML")
    else:
        await callback.message.edit_text(f"❌ <b>Delivery failed.</b> Make sure the bot is an Admin in <code>{settings.destination_channel_id}</code>.", parse_mode="HTML")

from services.telegram_sender import send_media_resilient

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
