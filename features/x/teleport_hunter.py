"""
teleport_hunter.py — Detachable Hybrid Fast-Forward Engine for X/Twitter Scraping.

Responsibilities:
1. For small archives (1 <= len(exclude_ids) <= 50):
   Executes 'Turbo Skim' down the creator's profile timeline with minimal delay,
   rapidly scrolling until it passes known historical posts.
2. For deep archives (len(exclude_ids) > 50):
   Extracts the earliest known Snowflake ID from exclude_ids, derives its UTC date,
   and navigates directly to X's native search:
   `https://x.com/search?q=(from:username)%20until:YYYY-MM-DD&f=live`
   Zero wasted scrolls — starts right at the historical cutoff!

Safety:
Entire module is isolated. If any error or unexpected HTML occurs, the caller's
circuit breaker falls back seamlessly to the standard battle-tested scroll loop.
"""

import asyncio
import random
import re
from datetime import timedelta
from typing import List, Callable, Awaitable, Optional, Set
from playwright.async_api import Page
from loguru import logger
from core.time_utils import snowflake_to_datetime


EXTRACT_TIMELINE_JS = """
(targetUser) => {
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    const items = [];
    for (const article of articles) {
        const timeEl = article.querySelector('time');
        if (!timeEl) continue;
        const anchor = timeEl.closest('a');
        if (!anchor) continue;
        const href = anchor.getAttribute('href');
        if (!href || !href.includes('/status/')) continue;

        const match = href.match(/\\/([^\\/]+)\\/status\\/(\\d+)/);
        if (!match) continue;

        const author = match[1];
        const tweetId = match[2];

        const socialContext = article.querySelector('[data-testid="socialContext"]');
        const isRepost = Boolean(socialContext) || (author.toLowerCase() !== targetUser.toLowerCase());

        items.push({
            id: tweetId,
            url: `https://x.com/${author}/status/${tweetId}`,
            author: author,
            is_repost: isRepost
        });
    }
    return items;
}
"""


def get_oldest_seen_date(exclude_ids: Set[str]) -> Optional[str]:
    """
    Finds the earliest tweet in exclude_ids and returns its YYYY-MM-DD date.
    Adds a 1-day safety buffer (next day) to prevent missing same-day posts.
    """
    valid_ids = [int(tid) for tid in exclude_ids if tid.isdigit() and len(tid) > 10]
    if not valid_ids:
        return None
    oldest_id = min(valid_ids)
    dt = snowflake_to_datetime(oldest_id)
    # until operator on X is exclusive (returns tweets before YYYY-MM-DD 00:00:00 UTC)
    # We add 1 day so tweets from the same day as oldest_id are included
    target_dt = dt + timedelta(days=1)
    return target_dt.strftime("%Y-%m-%d")


async def attempt_teleport_harvest(
    page: Page,
    username: str,
    limit: int,
    exclude_ids: Set[str],
    status_callback: Optional[Callable[[str], Awaitable[None]]] = None
) -> List[str]:
    """
    Tries hybrid fast-forward. Returns collected list of new tweet URLs.
    If archive is deep (> 50 items), jumps via search until:YYYY-MM-DD.
    If archive is small (1..50), turbo skims down profile.
    """
    if username.startswith("@"):
        username = username[1:]

    seen_count = len(exclude_ids)
    if seen_count == 0:
        return []

    collected_links: List[str] = []
    intercepted_ids: Set[str] = set()
    already_seen: Set[str] = {str(x) for x in exclude_ids}

    # -------------------------------------------------------------
    # STRATEGY A: Date Search Anchor (> 50 historical items)
    # -------------------------------------------------------------
    if seen_count > 50:
        cutoff_date = get_oldest_seen_date(exclude_ids)
        if cutoff_date:
            logger.info(f"[TELEPORT] Deep archive detected ({seen_count} seen items). Teleporting to until:{cutoff_date}...")
            if status_callback:
                await status_callback(f"⚡ Fast-Forward: Teleporting past {seen_count} historical posts (until {cutoff_date})...")

            search_query = f"(from:{username}) until:{cutoff_date}"
            search_url = f"https://x.com/search?q={search_query}&f=live"

            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.5)

            # Wait for search tweets to render
            try:
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=7000)
            except Exception:
                pass

            # Harvest search results
            stale_strikes = 0
            while len(collected_links) < limit and stale_strikes < 3:
                posts = await page.evaluate(EXTRACT_TIMELINE_JS, username.lower())
                new_in_scroll = 0
                for it in posts:
                    tid = it["id"]
                    if tid in intercepted_ids:
                        continue
                    intercepted_ids.add(tid)
                    if tid in already_seen:
                        continue
                    collected_links.append(it["url"])
                    new_in_scroll += 1
                    if len(collected_links) >= limit:
                        break

                if status_callback and new_in_scroll > 0:
                    await status_callback(f"🔎 Fast-Forward: Found {len(collected_links)}/{limit} new posts...")

                if len(collected_links) >= limit:
                    break

                if new_in_scroll == 0:
                    stale_strikes += 1
                else:
                    stale_strikes = 0

                await page.mouse.wheel(0, random.randint(700, 950))
                await asyncio.sleep(random.uniform(1.2, 2.0))

            logger.info(f"[TELEPORT] Search anchor collected {len(collected_links)} posts.")
            if collected_links:
                return collected_links[:limit]

    # -------------------------------------------------------------
    # STRATEGY B: Turbo Skim (1..50 historical items)
    # -------------------------------------------------------------
    logger.info(f"[TELEPORT] Small archive detected ({seen_count} seen items). Engaging Turbo Skim...")
    if status_callback:
        await status_callback(f"⚡ Turbo Skim: Fast-scrolling past {seen_count} historical posts...")

    # Rapid wheel scrolling to push past the top 1-2 pages of tweets
    for skim_step in range(min(12, max(3, seen_count // 4))):
        await page.mouse.wheel(0, 1200)
        await asyncio.sleep(0.35)

    await asyncio.sleep(1.0)
    logger.info("[TELEPORT] Turbo Skim complete. Handing over to standard harvest.")
    return []
