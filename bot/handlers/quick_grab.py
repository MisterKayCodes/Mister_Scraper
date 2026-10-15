import asyncio
from typing import Dict
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from loguru import logger

from core.text_cleaner import MessageCleaner
from core.media_resolver import extract_status_urls
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter, ScrapedItem
from services.quick_grab_service import (
    deliver_media,
    process_batch_grab,
    repost_to_channel_from_vault,
    repost_batch_to_channel_from_vault
)
from bot.states import QuickGrabStates
from bot.keyboards import get_quick_grab_choice_kb, get_delivery_action_deck_kb
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="quick_grab_router")

# Cache to avoid re-requesting metadata twice between preview card and delivery click
_scraped_cache: Dict[tuple, ScrapedItem] = {}
# Ephemeral batch storage mapping short_id -> List[tweet_id] to stay well under Telegram 64-byte callback limit
_batch_cache: Dict[str, list] = {}

MENU_BUTTONS = {
    "🚀 Auto-Sync Channel",
    "⚡ Quick Grab",
    "📋 Active Sources",
    "⚙️ Channel & Branding",
    "/start"
}

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

    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)

    sig = settings.custom_signature or ""
    f_mode = settings.filter_mode if settings.filter_mode is not None else 1
    has_channel = bool(settings.destination_channel_id)

    # 1. Single Link Flow
    if len(urls) == 1:
        url = urls[0]
        status_msg = await message.answer("🔍 <i>Fetching X content...</i>", parse_mode="HTML")
        scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
        if not scraped or not scraped.media_list:
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

    # 2. Multi-Link Batch Flow (Delegated to Service)
    total_count = len(urls)
    status_msg = await message.answer(
        f"⚡ <b>Batch Grab Initiated ({total_count} posts)</b>\n\n"
        f"⏳ Processing item 1 of {total_count}...",
        parse_mode="HTML"
    )

    delivered_count, last_author = await process_batch_grab(
        bot=bot,
        user_id=message.from_user.id,
        urls=urls,
        status_msg=status_msg,
        filter_mode=f_mode,
        signature=sig
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    import uuid
    batch_ids = [u.split("?")[0].rstrip("/").split("/")[-1] for u in urls if "/status/" in u]
    batch_key = uuid.uuid4().hex[:8]
    _batch_cache[batch_key] = batch_ids

    deck_kb = get_delivery_action_deck_kb(
        author=last_author,
        batch_key=batch_key,
        batch_count=len(batch_ids),
        has_channel=has_channel
    )
    await message.answer(
        f"✅ <b>Batch Delivery Complete!</b>\n\n"
        f"📦 Successfully delivered <b>{delivered_count} of {total_count}</b> posts to your chat.\n\n"
        "<i>Tap below to publish to your channel or auto-sync:</i>",
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

    success = await deliver_media(
        bot=bot,
        target_chat=callback.from_user.id,
        url=url,
        caption=data.get("caption", ""),
        status_msg=callback.message,
        scraped=cached_scraped,
        user_id=callback.from_user.id
    )

    deck_kb = get_delivery_action_deck_kb(author=author, content_id=tweet_id, has_channel=has_channel)
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    if success:
        await callback.message.answer("✅ <b>Delivered!</b> Enjoy your media.", reply_markup=deck_kb, parse_mode="HTML")
    else:
        await callback.message.answer("❌ <b>Delivery failed.</b> Could not deliver media to chat.", reply_markup=deck_kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("qg_repost:"))
async def cb_instant_repost(callback: types.CallbackQuery, bot: Bot):
    """Stateless 0-byte instant channel forwarder using Telegram file_id."""
    tweet_id = callback.data.split(":")[1]
    
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        if not settings.destination_channel_id:
            await callback.answer("⚠️ Link a channel in '⚙️ Channel & Branding' first!", show_alert=True)
            return

    await callback.answer("⚡ Forwarding to channel instantly...")
    success, reply_text = await repost_to_channel_from_vault(bot, callback.from_user.id, tweet_id, settings.destination_channel_id)
    await callback.message.reply(reply_text, parse_mode="HTML")

@router.callback_query(F.data.startswith("qg_b_test:"))
async def cb_batch_test_one(callback: types.CallbackQuery, bot: Bot):
    """Posts only the FIRST post from a batch to let the user test preview before posting the rest."""
    batch_key = callback.data.split(":", 1)[1]
    batch_ids = _batch_cache.get(batch_key, [])

    if not batch_ids:
        await callback.answer("Batch expired or not found. Please paste links again.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        if not settings.destination_channel_id:
            await callback.answer("⚠️ Link a channel in '⚙️ Channel & Branding' first!", show_alert=True)
            return

    test_id = batch_ids[0]
    remaining_ids = batch_ids[1:]
    await callback.answer("🧪 Posting test clip to channel...")

    ok, msg = await repost_to_channel_from_vault(bot, callback.from_user.id, test_id, settings.destination_channel_id)
    if not ok:
        await callback.message.reply(msg, parse_mode="HTML")
        return

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⚡ Grab Another Link", callback_data="qg_next"))
    if remaining_ids:
        import uuid
        rem_key = uuid.uuid4().hex[:8]
        _batch_cache[rem_key] = remaining_ids
        builder.row(
            types.InlineKeyboardButton(
                text=f"📢 Post Remaining ({len(remaining_ids)}) to Channel",
                callback_data=f"qg_b_all:{rem_key}"
            )
        )

    await callback.message.reply(
        f"🧪 <b>Test Post Sent!</b>\n"
        f"1 clip posted to <code>{settings.destination_channel_id}</code>.\n\n"
        f"Check your channel to see how it looks. If you like it, tap below to ship the remaining {len(remaining_ids)} posts:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("qg_b_all:"))
async def cb_batch_post_all(callback: types.CallbackQuery, bot: Bot):
    """Forwards all posts in the batch from Vault to channel sequentially with 0-byte transfer."""
    batch_key = callback.data.split(":", 1)[1]
    batch_ids = _batch_cache.get(batch_key, [])

    if not batch_ids:
        await callback.answer("Batch expired or not found. Please paste links again.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        if not settings.destination_channel_id:
            await callback.answer("⚠️ Link a channel in '⚙️ Channel & Branding' first!", show_alert=True)
            return

    await callback.answer(f"🚀 Shipping {len(batch_ids)} posts to channel...")
    status_reply = await callback.message.reply(
        f"⏳ <i>Forwarding {len(batch_ids)} posts to {settings.destination_channel_id}...</i>",
        parse_mode="HTML"
    )

    success_count, failed_ids = await repost_batch_to_channel_from_vault(
        bot=bot,
        user_id=callback.from_user.id,
        tweet_ids=batch_ids,
        channel_id=settings.destination_channel_id
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⚡ Grab Another Link", callback_data="qg_next"))

    if success_count == len(batch_ids):
        await status_reply.edit_text(
            f"🚀 <b>All {success_count} posts forwarded</b> to <code>{settings.destination_channel_id}</code>! (0-byte cloud transfer)",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    else:
        await status_reply.edit_text(
            f"⚠️ Forwarded <b>{success_count} of {len(batch_ids)}</b> posts to <code>{settings.destination_channel_id}</code>.\n"
            f"Failed: {len(failed_ids)} items.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )



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
