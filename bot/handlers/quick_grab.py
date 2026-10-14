import asyncio
import html
from pathlib import Path
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext

import config
from core.text_cleaner import MessageCleaner
from core.media_resolver import sanitize_filename, resolve_extension
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter
from services.downloader import download_file
from bot.states import QuickGrabStates
from bot.keyboards import get_quick_grab_choice_kb

router = Router(name="quick_grab_router")

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
@router.message(F.text.contains("x.com") | F.text.contains("twitter.com"))
async def process_x_link(message: types.Message, state: FSMContext):
    await state.clear()
    url = message.text.strip()
    status_msg = await message.answer("🔍 <i>Fetching X content...</i>", parse_mode="HTML")

    # Fetch using XAdapter
    scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
    if not scraped or not scraped.media_list:
        await status_msg.edit_text("❌ <b>No media found</b> in this post (or link is private/deleted).", parse_mode="HTML")
        return

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

    await callback.message.edit_text("⏳ <i>Downloading and delivering to your chat...</i>", parse_mode="HTML")
    await deliver_media(bot, callback.from_user.id, url, data.get("caption", ""))
    await callback.answer()

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

    await callback.message.edit_text(f"⏳ <i>Posting directly to {settings.destination_channel_id}...</i>", parse_mode="HTML")
    success = await deliver_media(bot, settings.destination_channel_id, url, data.get("caption", ""))
    if success:
        await callback.message.edit_text(f"✅ <b>Successfully posted</b> to <code>{settings.destination_channel_id}</code>!", parse_mode="HTML")
    else:
        await callback.message.edit_text(f"❌ <b>Delivery failed.</b> Make sure the bot is an Admin in <code>{settings.destination_channel_id}</code>.", parse_mode="HTML")
    await callback.answer()

async def deliver_media(bot: Bot, target_chat: any, url: str, caption: str) -> bool:
    """Delivers media directly to user DM or channel."""
    scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
    if not scraped or not scraped.media_list:
        return False

    download_dir = Path(config.DOWNLOAD_DIR)
    download_dir.mkdir(exist_ok=True)
    safe_caption = html.escape(caption)[:1024]

    success = False
    for i, media in enumerate(scraped.media_list):
        m_url = media.get("url")
        m_type = media.get("type", "image")
        ext = resolve_extension(m_type, m_url)

        local_path = download_dir / f"qg_{i}.{ext}"
        if await asyncio.to_thread(download_file, m_url, local_path):
            try:
                file_input = types.FSInputFile(str(local_path))
                if "video" in m_type.lower() or ext == "mp4":
                    await bot.send_video(target_chat, video=file_input, caption=safe_caption, parse_mode="HTML")
                else:
                    await bot.send_photo(target_chat, photo=file_input, caption=safe_caption, parse_mode="HTML")
                success = True
            except Exception as e:
                print(f"[QUICK_GRAB] Send error: {e}")
            finally:
                if local_path.exists():
                    try: local_path.unlink()
                    except: pass
    return success
