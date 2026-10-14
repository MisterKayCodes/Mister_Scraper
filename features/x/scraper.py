import asyncio
import random
import re
import json
from pathlib import Path
from typing import List, Callable, Awaitable, Optional
from playwright.async_api import async_playwright
from playwright_stealth import stealth
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

    # Select target URL & expected GraphQL endpoint
    if mode == "timeline":
        url = f"https://x.com/{username}"
        graphql_key = "UserTweets"
    else:
        url = f"https://x.com/{username}/media"
        graphql_key = "UserMedia"

    intercepted_tweet_ids = set()
    links = []

    if status_callback:
        await status_callback("🚀 Initializing Stealth Radar...")

    async with browser_semaphore:
        async with async_playwright() as p:
            cookie_path = config.DATA_DIR / "cookies.json"
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
                await stealth(page)
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
                await asyncio.sleep(2)
                for btn_text in ["Yes, view profile", "View", "Yes"]:
                    nsfw_btn = page.get_by_role("button", name=btn_text)
                    if await nsfw_btn.count() > 0:
                        await nsfw_btn.first.click()
                        await asyncio.sleep(2)
                        break

                # Scroll to tease lazy-loaded content
                for i in range(8):
                    if len(intercepted_tweet_ids) >= limit:
                        break
                    if status_callback:
                        await status_callback(f"🔄 Scanning media feed ({len(intercepted_tweet_ids)} found)...")
                    
                    await page.mouse.move(random.randint(100, 600), random.randint(100, 600))
                    await asyncio.sleep(0.3)
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(random.uniform(1.5, 3.0))

                for tid in intercepted_tweet_ids:
                    links.append(f"https://x.com/{username}/status/{tid}")
                    if len(links) >= limit:
                        break

            except Exception as e:
                if status_callback:
                    await status_callback(f"❌ Scan error: {str(e)}")
            finally:
                await browser.close()

    return links[:limit]
