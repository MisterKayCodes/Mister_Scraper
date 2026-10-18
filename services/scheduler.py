import asyncio
from datetime import timedelta
from typing import Optional

from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter
from .queue_worker import conveyor_queue
from core.time_utils import now_wat
from loguru import logger

from features.x.exceptions import PageNeverLoaded, AccountUnavailable, SessionExpired

# In-memory transient failure tracker: src.id -> count
_source_failure_counts = {}

async def run_scheduler_loop() -> None:
    """
    The Carrier (Scheduler):
    Checks active scheduled sources every 60 seconds.
    If a source's interval has elapsed, scans the X profile for new media
    and feeds unseen posts into the conveyor belt.
    """
    print("[SCHEDULER] Auto-check loop started.")

    while True:
        try:
            async with AsyncSessionLocal() as session:
                sources = await Repository.get_active_sources(session)
                now = now_wat()

                for src in sources:
                    # Check if run interval has elapsed
                    if src.next_check and src.next_check > now:
                        continue

                    print(f"[SCHEDULER] Checking X target @{src.target} for User {src.user_id}...")

                    # Fetch user settings for branding
                    settings = await Repository.get_or_create_settings(session, src.user_id)
                    sig = settings.custom_signature or ""
                    f_mode = settings.filter_mode if settings.filter_mode is not None else 1

                    # Harvest latest status links via stealth radar
                    next_retry_minutes = src.interval_minutes
                    try:
                        links = await XAdapter.get_profile_posts(src.target, limit=10)
                        logger.info(f"[SCHEDULER] Scanned @{src.target}: found {len(links)} candidate links.")
                        queued_count = 0

                        # Reverse links: deliver oldest to newest so channel narrative is chronological
                        chronological_links = list(reversed(links))

                        for link in chronological_links:
                            tweet_id = link.split("?")[0].rstrip("/").split("/")[-1]
                            # Check dedup: skip if already COMPLETED
                            if not await Repository.is_duplicate(session, src.user_id, "x", tweet_id):
                                # Mark as discovered with source_profile so we know whose item it is
                                await Repository.mark_as_discovered(session, src.user_id, "x", tweet_id, source_profile=src.target)
                                # Push to conveyor belt queue with src.id as task_id
                                await conveyor_queue.put((
                                    link,
                                    src.user_id,
                                    src.id, # Binds to ScheduledSource for delivery stats!
                                    src.destination_channel_id,
                                    sig,
                                    f_mode
                                ))
                                queued_count += 1

                        logger.info(f"[SCHEDULER] Queued {queued_count} new posts for @{src.target} -> {src.destination_channel_id}")
                        src.last_error = "None (Healthy)"
                        _source_failure_counts[src.id] = 0
                        next_retry_minutes = src.interval_minutes

                    except PageNeverLoaded as pnl_err:
                        err_str = f"PageNeverLoaded: {str(pnl_err)[:100]}"
                        logger.error(f"[SCHEDULER] Blank page failure for @{src.target}: {err_str}")
                        src.last_error = err_str

                        fails = _source_failure_counts.get(src.id, 0) + 1
                        _source_failure_counts[src.id] = fails
                        if fails <= 3:
                            next_retry_minutes = 30
                            logger.info(f"[SCHEDULER] Fast retry scheduled for @{src.target} in 30 minutes (attempt {fails}/3).")
                        else:
                            next_retry_minutes = src.interval_minutes
                            logger.warning(f"[SCHEDULER] Exceeded 3 consecutive fast retries for @{src.target}. Backing off to {src.interval_minutes}m.")

                    except (SessionExpired, AccountUnavailable) as fatal_err:
                        err_str = f"{type(fatal_err).__name__}: {str(fatal_err)[:100]}"
                        logger.error(f"[SCHEDULER] Fatal source error for @{src.target}: {err_str}")
                        src.last_error = err_str
                        # No fast retry for expired session or deleted/protected accounts
                        _source_failure_counts[src.id] = 0
                        next_retry_minutes = src.interval_minutes

                    except Exception as harvest_err:
                        err_str = f"Harvest error: {str(harvest_err)[:100]}"
                        logger.error(f"[SCHEDULER] Error scraping @{src.target}: {err_str}")
                        src.last_error = err_str
                        fails = _source_failure_counts.get(src.id, 0) + 1
                        _source_failure_counts[src.id] = fails
                        if fails <= 3:
                            next_retry_minutes = 30
                        else:
                            next_retry_minutes = src.interval_minutes

                    # Update next run time
                    next_time = now + timedelta(minutes=next_retry_minutes)
                    src.last_check = now
                    src.next_check = next_time
                    await session.commit()

        except Exception as e:
            print(f"[SCHEDULER] Loop error: {e}")

        # Sleep 60 seconds before next interval check
        await asyncio.sleep(60)
