import asyncio
import html
from typing import Optional, List, Tuple
from aiogram import Bot, types
from loguru import logger

from core.text_cleaner import MessageCleaner
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter, ScrapedItem
from services.telegram_sender import send_media_resilient
from sqlalchemy import select
from data.models import SeenItem


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


async def process_batch_grab(
    bot: Bot,
    user_id: int,
    urls: List[str],
    status_msg: types.Message,
    filter_mode: int,
    signature: str
) -> Tuple[int, str]:
    """
    The Carrier (Batch Processor):
    Executes sequential media delivery for multi-link drops with live status updates.
    Returns (delivered_count, last_author).
    """
    total_count = len(urls)
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
        clean_cap = MessageCleaner.clean(scraped.caption, mode=filter_mode, signature=signature)

        ok = await deliver_media(
            bot=bot,
            target_chat=user_id,
            url=u,
            caption=clean_cap,
            status_msg=None,
            scraped=scraped,
            user_id=user_id
        )
        if ok:
            delivered_count += 1

        if idx < total_count:
            await asyncio.sleep(1.0)

    return delivered_count, last_author


async def repost_to_channel_from_vault(
    bot: Bot,
    user_id: int,
    tweet_id: str,
    channel_id: str
) -> Tuple[bool, str]:
    """
    Instant 0-byte cloud forwarder:
    Looks up telegram_file_id from Vault and posts directly to channel.
    Returns (success: bool, message: str).
    """
    async with AsyncSessionLocal() as session:
        stmt = select(SeenItem).where(SeenItem.user_id == user_id, SeenItem.content_id == tweet_id)
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()

    if not item or not item.telegram_file_id:
        return False, "Media copy unavailable in Vault. Please paste the link again."

    try:
        if item.media_type == "video":
            await bot.send_video(
                chat_id=channel_id,
                video=item.telegram_file_id,
                caption=item.clean_caption or "",
                supports_streaming=True,
                parse_mode="HTML"
            )
        else:
            await bot.send_photo(
                chat_id=channel_id,
                photo=item.telegram_file_id,
                caption=item.clean_caption or "",
                parse_mode="HTML"
            )
        logger.info(f"[REPOST] 0-byte instant repost of {tweet_id} to {channel_id}")
        return True, f"🚀 <b>Posted instantly</b> to <code>{channel_id}</code>! (0-byte cloud transfer)"
    except Exception as e:
        logger.error(f"[REPOST] Error forwarding to channel: {e}")
        return False, f"❌ Failed to forward to channel: {e}"
