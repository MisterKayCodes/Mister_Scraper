import asyncio
import random
import re
import json
from pathlib import Path
from typing import List, Callable, Awaitable, Optional
from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None
import config

# Resource Guard: Only one headless Chromium runs at a time (VPS memory protection)
browser_semaphore = asyncio.Semaphore(1)

async def scrape_profile_media(
    username: str,
    limit: int = 10,
    status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    mode: str = "media"
) -> List[str]:
    """
    The Eyes (Stealth Radar):
    Scrapes an X profile using Playwright stealth and GraphQL response interception.
    Returns a list of direct status URLs: ['https://x.com/user/status/123456789', ...]
    """
    if username.startswith("@"):
        username = username[1:]

    # Always scrape the timeline (profile root) — X no longer fires UserMedia GraphQL
    # on authenticated sessions navigating to /media. DOM extraction from the main
    # timeline is the proven working approach.
    url = f"https://x.com/{username}"
    graphql_key = "UserTweets"  # Bonus: catch any GraphQL that fires too

    intercepted_tweet_ids = set()
    links = []

    if status_callback:
        await status_callback("🚀 Initializing Stealth Radar...")

    async with browser_semaphore:
        async with async_playwright() as p:
            cookie_path = config.DATA_DIR / "cookies.json"

            # Auto-generate cookies.json from .env if missing but tokens provided
            if not cookie_path.exists() and config.X_AUTH_TOKEN:
                c_list = [
                    {
                        "name": "auth_token",
                        "value": config.X_AUTH_TOKEN,
                        "domain": ".x.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None"
                    }
                ]
                if config.X_CT0:
                    c_list.append({
                        "name": "ct0",
                        "value": config.X_CT0,
                        "domain": ".x.com",
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "Lax"
                    })
                with open(cookie_path, "w", encoding="utf-8") as f:
                    json.dump({"cookies": c_list, "origins": []}, f)

            has_cookies = cookie_path.exists()

            # Sanitize cookies if present
            if has_cookies:
                try:
                    with open(cookie_path, "r", encoding="utf-8") as f:
                        cdata = json.load(f)
                    cookies_list = cdata if isinstance(cdata, list) else cdata.get("cookies", [])
                    needs_save = False
                    for c in cookies_list:
                        if "sameSite" in c:
                            ss = str(c["sameSite"]).lower()
                            if ss in ["no_restriction", "none"]:
                                c["sameSite"] = "None"
                                needs_save = True
                            elif ss in ["lax"]:
                                c["sameSite"] = "Lax"
                                needs_save = True
                            elif ss in ["strict"]:
                                c["sameSite"] = "Strict"
                                needs_save = True
                            else:
                                del c["sameSite"]
                                needs_save = True
                    if isinstance(cdata, list) or needs_save:
                        with open(cookie_path, "w", encoding="utf-8") as f:
                            json.dump({"cookies": cookies_list, "origins": []}, f)
                except Exception:
                    pass

            if status_callback:
                await status_callback(f"🌐 Launching Chromium (Cookies: {has_cookies})...")

            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage"
                    ]
                )
            except Exception as e:
                if status_callback:
                    await status_callback(f"❌ Browser launch error: {str(e)}")
                return []

            context_args = {
                "user_agent": config.DEFAULT_HEADERS["User-Agent"],
                "viewport": {"width": 1280, "height": 720}
            }
            if has_cookies:
                context_args["storage_state"] = str(cookie_path)

            context = await browser.new_context(**context_args)
            page = await context.new_page()

            # Apply anti-bot stealth mask
            try:
                if stealth_async:
                    await stealth_async(page)
            except Exception:
                pass

            # Intercept GraphQL responses
            async def handle_response(response):
                if "/graphql/" in response.url and graphql_key in response.url:
                    try:
                        body = await response.text()
                        found = re.findall(r'"rest_id":"(\d+)"', body)
                        found += re.findall(r'"conversation_id_str":"(\d+)"', body)
                        found += re.findall(r'https://(?:twitter|x)\.com/[^/]+/status/(\d+)', body)

                        for tid in found:
                            if tid.isdigit() and len(tid) > 10:
                                intercepted_tweet_ids.add(tid)
                    except Exception:
                        pass

            page.on("response", handle_response)

            if status_callback:
                await status_callback(f"🔍 Navigating to @{username}...")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Check redirect to login
                if "/login" in page.url or "/i/flow/" in page.url:
                    if status_callback:
                        await status_callback("⚠️ Session cookies required for this profile. Diverted to login.")
                    return []

                # Bypass NSFW "Sensitive Content" warning if present
                for _ in range(8):
                    dismissed = await page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        for (const b of btns) {
                            const txt = (b.innerText || '').toLowerCase();
                            if (txt.includes('yes, view profile') || txt.includes('view profile') || txt === 'yes') {
                                b.click();
                                return true;
                            }
                        }
                        return false;
                    }''')
                    if dismissed:
                        if status_callback:
                            await status_callback("🔓 Bypassed NSFW sensitive profile warning.")
                        await asyncio.sleep(2)
                        break
                    await asyncio.sleep(0.8)

                # Continuous Link Hunter: incremental extraction on every scroll step
                # Extracts status IDs from article[data-testid="tweet"] to capture 100% of posts AND reposts
                EXTRACT_TIMELINE_JS = '''
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

                        // Identify reposts / retweets
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
                '''

                stale_strikes = 0
                max_stale_strikes = 3
                last_scroll_y = await page.evaluate("() => window.scrollY")
                scroll_count = 0

                while len(intercepted_tweet_ids) < limit:
                    scroll_count += 1

                    # 1. Incremental Harvest: Extract visible tweets on THIS scroll step
                    try:
                        visible_posts = await page.evaluate(EXTRACT_TIMELINE_JS, username.lower())
                        new_batch_count = 0
                        for it in visible_posts:
                            tid = it["id"]
                            if tid not in intercepted_tweet_ids:
                                intercepted_tweet_ids.add(tid)
                                links.append(it["url"])
                                new_batch_count += 1
                                if len(links) >= limit:
                                    break
                    except Exception as harvest_err:
                        new_batch_count = 0

                    if status_callback and new_batch_count > 0:
                        await status_callback(f"🔎 Found {len(links)}/{limit} posts (+{new_batch_count} this scroll)...")

                    if len(links) >= limit:
                        break

                    # 2. Check End-of-Feed Convergence
                    metrics = await page.evaluate('''() => ({
                        scrollY: window.scrollY,
                        innerHeight: window.innerHeight,
                        scrollHeight: document.documentElement.scrollHeight
                    })''')
                    is_at_bottom = (metrics["scrollY"] + metrics["innerHeight"]) >= (metrics["scrollHeight"] - 120)
                    scroll_stalled = abs(metrics["scrollY"] - last_scroll_y) < 10
                    last_scroll_y = metrics["scrollY"]

                    if new_batch_count == 0 and (is_at_bottom or scroll_stalled):
                        stale_strikes += 1
                        if status_callback:
                            await status_callback(f"⚠️ Feed stalled (Strike {stale_strikes}/{max_stale_strikes})...")

                        if stale_strikes == 2:
                            # Rescue nudge: scroll UP 350px, wait, scroll DOWN 700px
                            await page.mouse.wheel(0, -350)
                            await asyncio.sleep(1.2)
                            await page.mouse.wheel(0, 700)
                            await asyncio.sleep(2.0)
                            continue

                        if stale_strikes >= max_stale_strikes:
                            if status_callback:
                                await status_callback(f"🏁 End of feed reached ({len(links)} posts captured).")
                            break
                    else:
                        stale_strikes = 0

                    # 3. Human Pacing & Movement
                    await page.mouse.move(random.randint(250, 750), random.randint(200, 600))
                    scroll_delta = random.randint(650, 950)
                    await page.mouse.wheel(0, scroll_delta)

                    # Periodic reading hesitation every 8 scrolls
                    if scroll_count % 8 == 0:
                        await asyncio.sleep(random.uniform(2.5, 4.0))
                    else:
                        await asyncio.sleep(random.uniform(1.2, 2.2))

                if status_callback:
                    await status_callback(f"✅ Hunter Complete: Collected {len(links)} posts.")

            except Exception as e:
                if status_callback:
                    await status_callback(f"❌ Scan error: {str(e)}")
            finally:
                await browser.close()

    return links[:limit]
