import asyncio
import random
import re
import json
import time
from pathlib import Path
from typing import List, Callable, Awaitable, Optional
from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None
from loguru import logger
import config
from .exceptions import ScraperException, PageNeverLoaded, AccountUnavailable, SessionExpired

# Resource Guard: Only one headless Chromium runs at a time (VPS memory protection)
browser_semaphore = asyncio.Semaphore(1)

def _read_mem_info() -> dict:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemAvailable:" in line or "SwapFree:" in line or "MemTotal:" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = v.strip()
    except Exception:
        pass
    return info

def _prune_old_dumps(directory: Path, pattern: str, keep: int = 5):
    try:
        files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_file in files[keep:]:
            old_file.unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"[RADAR] Error pruning dumps: {e}")

async def _create_browser_tab(browser, has_cookies: bool, cookie_path: Path, intercepted_ids: set):
    """Helper that creates a new browser context, applies stealth and configures listeners."""
    context_args = {
        "user_agent": config.DEFAULT_HEADERS["User-Agent"],
        "viewport": {"width": 1280, "height": 720}
    }
    if has_cookies:
        context_args["storage_state"] = str(cookie_path)

    context = await browser.new_context(**context_args)
    page = await context.new_page()

    if stealth_async:
        try:
            await stealth_async(page)
        except Exception:
            pass

    def on_response(response):
        if "/graphql/" in response.url and "UserTweets" in response.url:
            logger.info(f"[RADAR] GraphQL UserTweets response: status={response.status} url={response.url[:90]}...")

    def on_request_failed(request):
        if "/graphql/" in request.url and "UserTweets" in request.url:
            logger.warning(f"[RADAR] GraphQL UserTweets request failed: {request.failure} url={request.url[:90]}...")

    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)

    async def capture_graphql_body(response):
        if "/graphql/" in response.url and "UserTweets" in response.url:
            try:
                body = await response.text()
                found = re.findall(r'"rest_id":"(\d+)"', body)
                found += re.findall(r'"conversation_id_str":"(\d+)"', body)
                found += re.findall(r'https://(?:twitter|x)\.com/[^/]+/status/(\d+)', body)
                for tid in found:
                    if tid.isdigit() and len(tid) > 10:
                        intercepted_ids.add(tid)
            except Exception:
                pass

    page.on("response", capture_graphql_body)
    return context, page

async def _check_empty_account_state(page) -> Optional[str]:
    """
    Checks if the profile is legitimately empty, suspended, non-existent or protected.
    Checks both standard and curly apostrophes, and both 'tweets' and 'posts'.
    """
    try:
        body_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        text_lower = body_text.lower()

        # Check page title first
        title = (await page.title()).lower()
        if "page not found" in title:
            return "This page or account does not exist"

        if "account suspended" in text_lower:
            return "Account suspended"

        if ("this account doesn't exist" in text_lower or "this account doesn’t exist" in text_lower or
            "this page doesn't exist" in text_lower or "this page doesn’t exist" in text_lower):
            return "This account does not exist"

        if "these posts are protected" in text_lower or "these tweets are protected" in text_lower:
            return "These posts are protected"

        if ("hasn't posted" in text_lower or "hasn’t posted" in text_lower or
            "hasn't tweeted" in text_lower or "hasn’t tweeted" in text_lower):
            return "User has not published any posts"

    except Exception:
        pass
    return None

async def _dismiss_nsfw_modal_if_present(page, status_callback) -> bool:
    """
    Dismisses sensitive content warning if present.
    Exits early if timeline articles already appeared (e.g. non-NSFW profile).
    """
    for attempt in range(16):
        has_tweets = await page.evaluate("() => document.querySelector('article[data-testid=\"tweet\"]') !== null")
        if has_tweets:
            return False

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
            logger.info(f"[RADAR] Bypassed NSFW sensitive profile modal on attempt {attempt + 1}.")
            if status_callback:
                await status_callback("🔓 Bypassed NSFW sensitive profile warning. Loading timeline...")
            try:
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=8000)
            except Exception:
                await asyncio.sleep(2.0)
            return True
        await asyncio.sleep(0.8)
    return False

async def scrape_profile_media(
    username: str,
    limit: int = 10,
    status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    mode: str = "media",
    exclude_ids: Optional[set[str]] = None
) -> List[str]:
    """
    The Eyes (Stealth Radar):
    Scrapes an X profile using Playwright stealth and GraphQL response interception.
    Returns a list of direct status URLs: ['https://x.com/user/status/123456789', ...]
    If exclude_ids is provided, skips historical posts and digs deeper until 'limit' new posts are found.
    """
    if username.startswith("@"):
        username = username[1:]

    # Always scrape the timeline (profile root) — X no longer fires UserMedia GraphQL
    # on authenticated sessions navigating to /media. DOM extraction from the main
    # timeline is the proven working approach.
    url = f"https://x.com/{username}"
    mem_start = _read_mem_info()
    if mem_start:
        logger.info(f"[RADAR] Scrape start host memory: {mem_start}")

    graphql_key = "UserTweets"  # Bonus: catch any GraphQL that fires too

    intercepted_tweet_ids = set()
    links = []
    already_seen = {str(x) for x in exclude_ids} if exclude_ids else set()
    skipped_seen_count = 0

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
                logger.error(f"[RADAR] Browser launch failed: {e}")
                if status_callback:
                    await status_callback(f"❌ Browser launch error: {str(e)}")
                raise PageNeverLoaded(f"Browser launch failed: {e}") from e

            context = None
            page = None
            try:
                context, page = await _create_browser_tab(browser, has_cookies, cookie_path, intercepted_tweet_ids)

                # ==========================================
                # Page Hydration & Retry Loop (Up to 3 Attempts in Same Browser)
                # ==========================================
                hydrated = False
                for attempt in range(1, 4):
                    try:
                        if attempt == 1:
                            if status_callback:
                                await status_callback(f"🔍 Navigating to @{username}...")
                            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        elif attempt == 2:
                            logger.warning(f"[RADAR] Blank page on attempt 1. Executing page.reload() (attempt 2/3) for @{username}...")
                            if status_callback:
                                await status_callback("⚠️ Blank page detected, retrying (2/3)...")
                            await page.reload(wait_until="domcontentloaded", timeout=60000)
                        elif attempt == 3:
                            logger.warning(f"[RADAR] Blank page on attempt 2. Rebuilding fresh context (attempt 3/3) for @{username}...")
                            if status_callback:
                                await status_callback("⚠️ Blank page detected, refreshing session (3/3)...")
                            await context.close()
                            context, page = await _create_browser_tab(browser, has_cookies, cookie_path, intercepted_tweet_ids)
                            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                        # Check redirect to login
                        if "/login" in page.url or "/i/flow/" in page.url:
                            logger.warning(f"[RADAR] X redirected to login page for @{username}. Session expired.")
                            raise SessionExpired(f"X redirected to login for @{username}. Cookies are expired or missing.")

                        # Dismiss NSFW if present (exits early if articles already present)
                        await _dismiss_nsfw_modal_if_present(page, status_callback)

                        # Wait up to 15s for articles to hydrate
                        try:
                            await page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
                        except Exception:
                            pass

                        # Collect attempt diagnostics
                        article_count = await page.evaluate("() => document.querySelectorAll('article[data-testid=\"tweet\"]').length")
                        page_title = await page.title()
                        logger.info(f"[RADAR] Attempt {attempt}/3 diagnostics: articles={article_count}, title='{page_title}', url='{page.url}'")

                        if article_count > 0:
                            hydrated = True
                            break

                        # Check legitimate empty / unavailable state — never retry if so
                        empty_reason = await _check_empty_account_state(page)
                        if empty_reason:
                            logger.warning(f"[RADAR] Account @{username} unavailable or empty: {empty_reason}")
                            raise AccountUnavailable(f"Account @{username} is unavailable: {empty_reason}")

                    except ScraperException:
                        raise
                    except Exception as attempt_err:
                        logger.warning(f"[RADAR] Attempt {attempt}/3 encountered navigation/hydration error: {attempt_err}")
                        if attempt == 3:
                            break
                        continue

                # If still 0 articles after 3 attempts, save diagnostic evidence and raise PageNeverLoaded
                if not hydrated:
                    mem_fail = _read_mem_info()
                    logger.error(f"[RADAR] Failed to hydrate timeline for @{username} after 3 attempts. Memory on failure: {mem_fail}")

                    scratch_dir = config.BASE_DIR / "scratch"
                    scratch_dir.mkdir(exist_ok=True)
                    ts = int(time.time())
                    html_dump_path = scratch_dir / f"blank_page_{username}_{ts}.html"
                    png_dump_path = scratch_dir / f"blank_page_{username}_{ts}.png"

                    try:
                        content = await page.content()
                        html_dump_path.write_text(content, encoding="utf-8")
                        await page.screenshot(path=str(png_dump_path), full_page=True)
                        logger.info(f"[RADAR] Saved failure dumps to {html_dump_path} and {png_dump_path}")
                        _prune_old_dumps(scratch_dir, "blank_page_*.html", keep=5)
                        _prune_old_dumps(scratch_dir, "blank_page_*.png", keep=5)
                    except Exception as dump_err:
                        logger.debug(f"[RADAR] Failed saving failure dump: {dump_err}")

                    raise PageNeverLoaded(f"Timeline for @{username} never loaded (0 posts in DOM after 3 attempts)")

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

                while len(links) < limit:
                    scroll_count += 1

                    # 1. Incremental Harvest: Extract visible tweets on THIS scroll step
                    dom_yield_count = 0
                    try:
                        visible_posts = await page.evaluate(EXTRACT_TIMELINE_JS, username.lower())
                        new_batch_count = 0
                        for it in visible_posts:
                            tid = it["id"]
                            if tid in intercepted_tweet_ids:
                                continue
                            intercepted_tweet_ids.add(tid)
                            dom_yield_count += 1

                            if tid in already_seen:
                                skipped_seen_count += 1
                                continue

                            links.append(it["url"])
                            new_batch_count += 1
                            if len(links) >= limit:
                                break
                    except Exception as harvest_err:
                        new_batch_count = 0
                        dom_yield_count = 0

                    if status_callback and (new_batch_count > 0 or skipped_seen_count > 0):
                        if already_seen:
                            await status_callback(f"🔎 Found {len(links)}/{limit} new posts (skipped {skipped_seen_count} historical)...")
                        else:
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

                    # True feed stall only occurs if the DOM yielded 0 posts (seen or unseen) and page cannot move
                    if dom_yield_count == 0 and (is_at_bottom or scroll_stalled):
                        stale_strikes += 1
                        logger.warning(f"[RADAR] DOM yielded 0 posts this scroll (Strike {stale_strikes}/{max_stale_strikes}). Timeline may be exhausted.")
                        if status_callback:
                            await status_callback(f"⚠️ Feed stalled (Strike {stale_strikes}/{max_stale_strikes})...")

                        if stale_strikes == 2:
                            logger.info("[RADAR] Strike 2 — executing rescue nudge (scroll up then down) to unstick X virtual scroll...")
                            # Rescue nudge: scroll UP 350px, wait, scroll DOWN 700px
                            await page.mouse.wheel(0, -350)
                            await asyncio.sleep(1.2)
                            await page.mouse.wheel(0, 700)
                            await asyncio.sleep(2.0)
                            continue

                        if stale_strikes >= max_stale_strikes:
                            logger.info(f"[RADAR] End of scrollable feed confirmed. Collected {len(links)} posts. Exiting scroll loop cleanly.")
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
                if not links and skipped_seen_count == 0:
                    raise PageNeverLoaded(f"Zero posts harvested and zero historical posts seen for @{username}")

            except ScraperException:
                raise
            except Exception as e:
                logger.error(f"[RADAR] Playwright session encountered an error for @{username}: {e}")
                if status_callback:
                    await status_callback(f"❌ Scan error: {str(e)}")
                if not links and skipped_seen_count == 0:
                    raise PageNeverLoaded(f"Playwright error during scraping: {e}") from e
            finally:
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
                await browser.close()

    return links[:limit]
