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
