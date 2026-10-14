import asyncio
import random
import html
from pathlib import Path
from typing import Tuple
from aiogram import Bot, types

import config
from core.text_cleaner import MessageCleaner
from core.media_resolver import sanitize_filename, resolve_extension
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter
from .downloader import download_file

from loguru import logger

# Global Conveyor Belt Queue
# Queue items: Tuple[tweet_url: str, user_id: int, task_id: int, destination_channel: str, custom_signature: str, filter_mode: int]
conveyor_queue = asyncio.Queue()
_is_first_post = True

async def process_queue_item(bot: Bot, item: Tuple) -> None:
    """Processes a single media item from the conveyor belt."""
    url, user_id, task_id, destination_channel, signature, filter_mode = item
    tweet_id = url.split("?")[0].rstrip("/").split("/")[-1]

    # Check deduplication first
    async with AsyncSessionLocal() as session:
        if await Repository.is_duplicate(session, user_id, "x", tweet_id):
            print(f"[CONVEYOR] Skipped duplicate tweet: {tweet_id}")
            return

    # Extract metadata using XAdapter
    scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
    if not scraped or not scraped.media_list:
        print(f"[CONVEYOR] No media found in {url}")
        return

    # Clean caption using The Brain (MessageCleaner)
    clean_caption = MessageCleaner.clean(
        text=scraped.caption,
        mode=filter_mode,
        signature=signature
    )
    safe_caption = html.escape(clean_caption)[:1024]

    download_dir = Path(config.DOWNLOAD_DIR)
    download_dir.mkdir(exist_ok=True)
    safe_base_name = sanitize_filename(scraped.caption)

    # Process and download each media item
    for i, media in enumerate(scraped.media_list):
        m_url = media.get("url")
        m_type = media.get("type", "image")
        ext = resolve_extension(m_type, m_url)

        file_name = f"{safe_base_name}_{tweet_id}_{i}.{ext}"
        local_path = download_dir / file_name

        # Download chunked
        success = await asyncio.to_thread(download_file, m_url, local_path)
        if not success:
            err_msg = f"Failed to download media: {m_url[:50]}"
            logger.error(f"[CONVEYOR] {err_msg}")
            async with AsyncSessionLocal() as session:
                await Repository.mark_as_failed(session, user_id, "x", tweet_id, err_msg)
            continue

        # Upload to target channel
        try:
            file_input = types.FSInputFile(str(local_path))
            if "video" in m_type.lower() or ext == "mp4":
                await bot.send_video(
                    chat_id=destination_channel,
                    video=file_input,
                    caption=safe_caption,
                    parse_mode="HTML",
                    request_timeout=300
                )
            else:
                await bot.send_photo(
                    chat_id=destination_channel,
                    photo=file_input,
                    caption=safe_caption,
                    parse_mode="HTML",
                    request_timeout=60
                )

            # Mark as COMPLETED in The Vault (Guaranteed State)
            async with AsyncSessionLocal() as session:
                await Repository.mark_as_completed(session, user_id, "x", tweet_id)
                # If tied to a scheduled source, update its delivery stats
                if task_id:
                    await Repository.update_source_stats(session, source_id=task_id, delivered_increment=1, last_error="None (Healthy)")

            logger.info(f"[CONVEYOR] Successfully delivered {tweet_id} to {destination_channel}")

        except Exception as e:
            err_msg = f"Telegram upload error: {str(e)[:100]}"
            logger.error(f"[CONVEYOR] Error posting to {destination_channel}: {err_msg}")
            async with AsyncSessionLocal() as session:
                await Repository.mark_as_failed(session, user_id, "x", tweet_id, err_msg)
                if task_id:
                    await Repository.update_source_stats(session, source_id=task_id, last_error=err_msg)
        finally:
            if local_path.exists():
                try:
                    local_path.unlink()
                except Exception:
                    pass

async def conveyor_worker(bot: Bot) -> None:
    """Continuous background worker with human anti-ban jitter."""
    global _is_first_post
    logger.info("[CONVEYOR] Background worker started.")
    while True:
        item = await conveyor_queue.get()
        try:
            # First item in batch: 1-5s for instant feedback
            # Subsequent items: 45-90s to protect Telegram channel
            if _is_first_post:
                jitter = random.uniform(1.0, 5.0)
                _is_first_post = False
            else:
                jitter = random.uniform(45.0, 90.0)

            logger.info(f"[CONVEYOR] Pacing next item. Sleeping for {jitter:.1f}s jitter...")
            await asyncio.sleep(jitter)
            await process_queue_item(bot, item)
        except Exception as e:
            logger.error(f"[CONVEYOR] Worker error: {e}")
        finally:
            conveyor_queue.task_done()

