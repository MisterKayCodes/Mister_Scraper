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

# Global Conveyor Belt Queue
# Queue items: Tuple[tweet_url: str, user_id: int, task_id: int, destination_channel: str, custom_signature: str, filter_mode: int]
conveyor_queue = asyncio.Queue()

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
            print(f"[CONVEYOR] Failed to download media: {m_url}")
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

            # Mark as seen in The Vault
            async with AsyncSessionLocal() as session:
                await Repository.mark_as_seen(session, user_id, "x", tweet_id)
                if task_id:
                    await Repository.update_task(session, task_id, processed_count=1, success_count=1)

            print(f"[CONVEYOR] Successfully posted {tweet_id} to {destination_channel}")

        except Exception as e:
            print(f"[CONVEYOR] Error posting to {destination_channel}: {e}")
        finally:
            if local_path.exists():
                try:
                    local_path.unlink()
                except Exception:
                    pass

async def conveyor_worker(bot: Bot) -> None:
    """Continuous background worker with human anti-ban jitter."""
    print("[CONVEYOR] Background worker started.")
    while True:
        item = await conveyor_queue.get()
        try:
            # Jitter pacing: 30-90 seconds to mimic human cadence
            jitter = random.uniform(30.0, 90.0)
            await asyncio.sleep(jitter)
            await process_queue_item(bot, item)
        except Exception as e:
            print(f"[CONVEYOR] Worker error: {e}")
        finally:
            conveyor_queue.task_done()
