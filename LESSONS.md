# Lessons Learned: Mister_Scraper

<!--
Format:
## [Short title of the bug/incident]
- Symptom: What broke or behaved unexpectedly
- Cause: Why it broke at root level
- Fix: What resolved it
- Verified by: Exact user observation / log output proving it works
-->

## Large Video Upload Timeout and Socket Drop (WinError 64)
- Symptom: High-bitrate 1080p video (25MB+) timed out after 5 minutes and crashed upload with `ClientOSError: [WinError 64] The specified network name is no longer available`.
- Cause: Scraper selected raw uncompressed 10.4 Mbps stream; uploading 25MB over residential upstream pipe to Telegram API stalled the TCP socket.
- Fix: Added FxTwitter metadata negotiation to select 720p HD stream (2.1 Mbps, ~7MB) and introduced Tier 1 direct cloud transfer (`video=media_url`) with resilient fallback in `services/telegram_sender.py`.
- Verified by: arrived under 3 seconds it arrived in the telegram chat-- and this is the logs: Tier 1 Cloud transfer SUCCESS for 8610146054 for multiple posts

## Telegram Video Thumbnail Discard and Blank Player Box
- Symptom: Videos uploaded via Telegram Bot API showed a blank black box with a download arrow instead of an inline preview thumbnail, and progress percentage was not updating during upload.
- Cause: Twitter CDN image URLs were passed directly as URLInputFile (which Twitter blocks from Telegram IPs), and raw image dimensions (1200x675) exceeded Telegram's strict 320x320 thumbnail limit, causing Telegram to silently drop the thumbnail. Furthermore, `supports_streaming=True` was omitted.
- Fix: Downloaded thumbnail locally, scaled it to max 320x320 JPEG via Pillow, passed it as FSInputFile with `supports_streaming=True`, and implemented `ProgressFSInputFile` to stream live upload percentage chunks to `TelegramProgressTracker`.
- Verified by: it works the thumbnail works the progress bars work and it uploaded it to the channel as wel when  clicked channel

## NSFW Sensitive Profile Modal Scrape Failure
- Symptom: Headless Playwright scraper returned 0 items on sensitive/NSFW profiles.
- Cause: X hydrated the "Yes, view profile" modal after Playwright accessibility role lookup executed, so get_by_role failed to locate the button.
- Fix: Replaced role lookup with a polling page.evaluate loop that queries button elements by innerText directly in the DOM and calls click().
- Verified by: the nsfw oe worked yes

## In-Memory Queue Starvation and DB Backlog Orphanage on Restart
- Symptom: Diagnostic card reported "Idle (Waiting for new posts)" despite 18 pending items in SQLite, halting channel deliveries after restart.
- Cause: `conveyor_queue` was an in-memory `asyncio.Queue` wiped on process termination; no rehydration mechanism queried `seen_items` in `DISCOVERED` state at startup.
- Fix: Added `rehydrate_conveyor_queue()` at bot boot and on worker batch drain, with in-flight ID deduplication.
- Verified by: it posted one from goddessofporno just now

## Cross-Source Diagnostic Contamination and Zombie Pending Post Discrepancy
- Symptom: Diagnostic card showed inconsistent queue counts (e.g. 5 pending in preview header vs 2 in status, or inflated counts across sources).
- Cause: `get_pending_items` and `get_pending_count` lacked a `source_profile` filter, aggregating all sources globally; furthermore, text-only tweets with no downloadable media remained indefinitely stuck in `DISCOVERED` status as zombie pending records.
- Fix: Scoped pending/failed repository queries strictly to `source_profile == src.target` and marked text-only/no-media items as `COMPLETED` (`media_type="none"`) in the database.
- Verified by: and btw the 2 inconsistent queued numbers in scraper feed is consistent now

