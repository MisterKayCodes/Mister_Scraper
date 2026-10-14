import asyncio
from datetime import datetime, timedelta
from typing import Optional

from data.database import AsyncSessionLocal
from data.repository import Repository
from features.x.adapter import XAdapter
from .queue_worker import conveyor_queue

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
                now = datetime.utcnow()

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
                    links = await XAdapter.get_profile_posts(src.target, limit=5)

                    for link in links:
                        tweet_id = link.split("?")[0].rstrip("/").split("/")[-1]
                        # Check dedup
                        if not await Repository.is_duplicate(session, src.user_id, "x", tweet_id):
                            # Push to conveyor belt queue
                            await conveyor_queue.put((
                                link,
                                src.user_id,
                                0, # task_id
                                src.destination_channel_id,
                                sig,
                                f_mode
                            ))
                            print(f"[SCHEDULER] Queued new tweet {tweet_id} for @{src.target}")

                    # Update next run time
                    next_time = now + timedelta(minutes=src.interval_minutes)
                    src.last_check = now
                    src.next_check = next_time
                    await session.commit()

        except Exception as e:
            print(f"[SCHEDULER] Loop error: {e}")

        # Sleep 60 seconds before next interval check
        await asyncio.sleep(60)
