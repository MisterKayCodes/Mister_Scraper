import asyncio
import random
import html
from pathlib import Path
from typing import Tuple, Optional
from aiogram import Bot, types

import config
from core.text_cleaner import MessageCleaner
from core.media_resolver import sanitize_filename, resolve_extension
from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter
from .downloader import download_file

from loguru import logger

import time
from datetime import datetime, timedelta
from aiogram.exceptions import TelegramRetryAfter
from core.time_utils import now_wat

# Global Conveyor Belt Queue
# Queue items: Tuple[tweet_url: str, user_id: int, task_id: int, destination_channel: str, custom_signature: str, filter_mode: int]
conveyor_queue = asyncio.Queue()
_is_first_post = True
_in_flight_ids = set()

# Global Rate Limit Tracker for UI & Worker coordination
rate_limit_state = {
    "is_limited": False,
    "retry_after": 0,
    "free_at": None,
    "last_error": None
}

# Global Delivery Engine Tracker for Live Card UI
delivery_state = {
    "is_active": False,
    "current_target": "",
    "next_drop_at": None,
    "total_in_batch": 0,
    "remaining_in_batch": 0
}

async def rehydrate_conveyor_queue() -> int:
    """
    Fetches all un-posted (DISCOVERED, PENDING, QUEUED) items from DB and
    pushes them back into conveyor_queue if they are not already in it.
    Prevents queue starvation after bot restarts or unexpected errors.
    """
    async with AsyncSessionLocal() as session:
        pending_items = await Repository.get_all_pending_for_rehydration(session)
        if not pending_items:
            return 0

        sources = await Repository.get_active_sources(session)
        src_map = {(s.user_id, s.target.lower()): s for s in sources}

        count = 0
        for item in pending_items:
            tid = str(item.content_id)
            if tid in _in_flight_ids:
                continue
            if await Repository.is_duplicate(session, item.user_id, item.platform or "x", tid):
                continue

            tgt = (item.source_profile or "").lower()
            src = src_map.get((item.user_id, tgt))
            dest_channel = src.destination_channel_id if src else None
            source_id = src.id if src else None

            settings = await Repository.get_or_create_settings(session, item.user_id)
            if not dest_channel:
                dest_channel = settings.destination_channel_id
            sig = settings.custom_signature or ""
            f_mode = settings.filter_mode if settings.filter_mode is not None else 1

            if not dest_channel:
                continue

            url = item.url or f"https://x.com/{item.source_profile or 'i'}/status/{tid}"
            _in_flight_ids.add(tid)
            await conveyor_queue.put((url, item.user_id, source_id, dest_channel, sig, f_mode))
            count += 1

        if count > 0:
            logger.info(f"[CONVEYOR] Rehydrated {count} pending items into conveyor queue.")
        return count

def get_delivery_status(target: Optional[str] = None) -> dict:
    """Returns active delivery state for diagnostic card rendering, scoped by target if requested."""
    status = dict(delivery_state)
    clean_target = target.lstrip("@").strip().lower() if target else None

    if clean_target and hasattr(conveyor_queue, "_queue"):
        # Count only items in the in-memory queue belonging to this target
        target_in_queue = sum(1 for q_item in conveyor_queue._queue if clean_target in str(q_item[0]).lower())
        is_cur = clean_target in status.get("current_target", "").lower()
        status["queue_size"] = target_in_queue
        # If currently dripping this target, remaining in batch is queue + 1 (the one currently being processed)
        status["remaining_in_batch"] = target_in_queue + (1 if (status["is_active"] and is_cur) else 0)
        # Only show dripping if the active post belongs to this target or this target has items in queue
        if not is_cur and target_in_queue == 0:
            status["is_active"] = False
    else:
        status["queue_size"] = conveyor_queue.qsize()

    if status["next_drop_at"]:
        now = now_wat()
        if now >= status["next_drop_at"]:
            status["next_drop_secs"] = 0
        else:
            status["next_drop_secs"] = int((status["next_drop_at"] - now).total_seconds())
    else:
        status["next_drop_secs"] = 0
    return status

def get_rate_limit_status() -> dict:
    """Returns current rate limit state for diagnostic cards."""
    if rate_limit_state["is_limited"] and rate_limit_state["free_at"]:
        now = now_wat()
        if now >= rate_limit_state["free_at"]:
            rate_limit_state["is_limited"] = False
            rate_limit_state["free_at"] = None
    return rate_limit_state

async def process_queue_item(bot: Bot, item: Tuple) -> None:
    """Processes a single media item from the conveyor belt."""
    url, user_id, task_id, destination_channel, signature, filter_mode = item
    tweet_id = url.split("?")[0].rstrip("/").split("/")[-1]
    _in_flight_ids.add(tweet_id)

    try:
        # Check deduplication first
        async with AsyncSessionLocal() as session:
            if await Repository.is_duplicate(session, user_id, "x", tweet_id):
                print(f"[CONVEYOR] Skipped duplicate tweet: {tweet_id}")
                return

        # Extract metadata using XAdapter
        scraped = await asyncio.to_thread(XAdapter.get_single_post, url)
        if not scraped or not scraped.media_list:
            logger.info(f"[CONVEYOR] No media found in {url} (text-only or empty). Clearing from pending queue.")
            async with AsyncSessionLocal() as session:
                await Repository.mark_as_completed(session, user_id, "x", tweet_id, media_type="none")
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

        from .telegram_sender import send_media_resilient

        # Process and deliver each media item via Resilient Sender
        for i, media in enumerate(scraped.media_list):
            m_url = media.get("url")
            m_type = media.get("type", "image")

            success = await send_media_resilient(
                bot=bot,
                target_chat=destination_channel,
                media_url=m_url,
                media_type=m_type,
                caption=safe_caption,
                thumbnail_url=media.get("thumbnail_url"),
                width=media.get("width"),
                height=media.get("height"),
                duration=media.get("duration")
            )

            if success:
                async with AsyncSessionLocal() as session:
                    await Repository.mark_as_completed(session, user_id, "x", tweet_id)
                    if task_id:
                        await Repository.update_source_stats(session, source_id=task_id, delivered_increment=1, last_error="None (Healthy)")
                logger.info(f"[CONVEYOR] Successfully delivered {tweet_id} to {destination_channel}")
            else:
                err_msg = f"Delivery failed for {m_url[:50]}"
                logger.error(f"[CONVEYOR] {err_msg}")
                async with AsyncSessionLocal() as session:
                    await Repository.mark_as_failed(session, user_id, "x", tweet_id, err_msg)
                    if task_id:
                        await Repository.update_source_stats(session, source_id=task_id, last_error=err_msg)
    finally:
        _in_flight_ids.discard(tweet_id)

async def conveyor_worker(bot: Bot) -> None:
    """Continuous background worker with human anti-ban jitter & 429 auto-wait."""
    global _is_first_post
    logger.info("[CONVEYOR] Background worker started. Checking for orphaned queued items...")
    try:
        await rehydrate_conveyor_queue()
    except Exception as rehydrate_err:
        logger.error(f"[CONVEYOR] Startup rehydrate error: {rehydrate_err}")

    while True:
        item = await conveyor_queue.get()
        try:
            # Check if currently under Telegram 429 cooldown
            if rate_limit_state["is_limited"] and rate_limit_state["free_at"]:
                now = now_wat()
                if now < rate_limit_state["free_at"]:
                    remaining_wait = (rate_limit_state["free_at"] - now).total_seconds()
                    logger.warning(f"[CONVEYOR] Still in Telegram cooldown. Sleeping remaining {remaining_wait:.1f}s...")
                    await asyncio.sleep(remaining_wait)
                rate_limit_state["is_limited"] = False
                rate_limit_state["free_at"] = None

            # First item in batch: 1-5s for instant feedback
            # Subsequent items: 45-90s to protect Telegram channel
            if _is_first_post:
                jitter = random.uniform(1.0, 5.0)
                _is_first_post = False
            else:
                jitter = random.uniform(45.0, 90.0)

            # Extract target from url e.g. x.com/target/status/...
            url = str(item[0])
            clean_url = url.split("?")[0]
            parts = [p for p in clean_url.replace("https://", "").replace("http://", "").split("/") if p]
            current_target = parts[1] if (len(parts) >= 3 and parts[0].endswith("x.com")) else ""

            # Update live UI delivery state
            delivery_state["is_active"] = True
            delivery_state["current_target"] = current_target
            delivery_state["next_drop_at"] = now_wat() + timedelta(seconds=jitter)
            delivery_state["remaining_in_batch"] = conveyor_queue.qsize() + 1

            logger.info(f"[CONVEYOR] Pacing next item (@{current_target}). Sleeping for {jitter:.1f}s jitter...")
            await asyncio.sleep(jitter)
            await process_queue_item(bot, item)

            delivery_state["remaining_in_batch"] = conveyor_queue.qsize()
            if conveyor_queue.empty():
                rehydrated = await rehydrate_conveyor_queue()
                if rehydrated == 0:
                    delivery_state["is_active"] = False
                    delivery_state["next_drop_at"] = None

        except TelegramRetryAfter as rate_err:
            wait_seconds = rate_err.retry_after + 15
            free_time = now_wat() + timedelta(seconds=wait_seconds)
            rate_limit_state["is_limited"] = True
            rate_limit_state["retry_after"] = wait_seconds
            rate_limit_state["free_at"] = free_time
            rate_limit_state["last_error"] = f"Telegram 429: Rate limited for {wait_seconds}s"
            
            logger.warning(f"[CONVEYOR] ⚠️ Telegram 429 encountered! Auto-waiting {wait_seconds}s (retry_after={rate_err.retry_after} + 15s buffer). Free at {free_time.strftime('%H:%M:%S')}")
            
            # Put item back at front of queue to not lose it
            await conveyor_queue.put(item)
            await asyncio.sleep(wait_seconds)
            rate_limit_state["is_limited"] = False

        except Exception as e:
            logger.error(f"[CONVEYOR] Worker error: {e}")
        finally:
            conveyor_queue.task_done()
            if conveyor_queue.empty():
                rehydrated = await rehydrate_conveyor_queue()
                if rehydrated == 0:
                    delivery_state["is_active"] = False
                    delivery_state["next_drop_at"] = None

