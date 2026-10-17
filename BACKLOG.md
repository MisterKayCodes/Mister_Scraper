# 📋 Backlog & MVP Scope: Mister_Scraper

> **Mode:** Fast-Shipping | **Target:** Working MVP Today | **Anti-Fog Rule:** No shiny distractions.

---

## 🎯 Phase 1: MVP Scope (Shipping TODAY)

### 1. 🧠 Core (The Brain)
- [x] `core/text_cleaner.py`: `MessageCleaner` with regex link & `@username` stripping + VIP signature injection.
- [x] `core/media_resolver.py`: Safe filename sanitization + extension resolution (`.mp4`, `.jpg`).
- [x] `extract_x_username()`: Flexible parser (`@user`, `x.com/user`, `x.com/user/media`).

### 2. 👁️ Features (The Eyes)
- [x] `features/x/fast_meta.py`: Fix vxtwitter 403 via `TelegramBot` User-Agent & query param stripping + 720p HD stream selection.
- [x] `features/x/scraper.py`: Playwright stealth radar with DOM extraction and cookie injection.
- [x] `features/x/adapter.py`: Normalized `ScrapedItem` dataclass interface.

### 3. 🧬 Services (The Carrier / Nervous System)
- [x] `services/downloader.py`: Atomic 128KB chunked media downloader.
- [x] `services/queue_worker.py`: Two-Stage State Machine (`DISCOVERED` -> `COMPLETED` / `FAILED`), Telegram 429 auto-wait, and paced jitter (1-5s first post, 45-90s subsequent).
- [x] `services/scheduler.py`: Cron runner supporting 30m, 2h, 6h, 12h, 24h intervals with `last_check`, `next_check`, and `last_error` tracking.
- [x] `services/quick_grab_service.py`: 0-byte instant Vault forwarder with adaptive batch pacing & preview testing.

### 4. 👄 Bot UI / UX Specification (The Mouth)
- [x] **Dynamic Self-Collapsing Checklist Wizard** on `/start`.
- [x] **⚡ Quick Grab Flow**:
  - Drop single or multi X links -> cleans caption -> offers `[ 👤 Send to Me ]`, `[ 📢 Post All to Channel ]`, and `[ 🧪 Test 1 to Channel ]`.
- [x] **🚀 Auto-Sync Flow & Pair Manager**:
  - Extended Intervals: `30m`, `2h`, `6h`, `12h`, `24h (Daily)`.
  - Diagnostic Feed Card with instant `[ 🔄 Refresh ]`, `[ ⚡ Check Now ]`, and `[ ▶️ Deliver Next Now ]`.
- [x] **⚙️ Channel & Branding Flow**:
  - Channel binding, VIP signature footer, link-stripping toggle.

### 5. 🌐 API (The Wall Socket)
- [x] `POST /scrape`: Direct link scrape for `Mister_Chief`.
- [x] `GET /health` & `GET /status`: Background task health check.

---

## 🚀 Phase 1.5: Deep Harvester & Continuous Profile Archive (IN PROGRESS)

- [ ] **1. Bug Fix in `core/media_resolver.py`**:
  - Pass `thumbnail_url` from `media_extended` into `media_list` item dicts so video thumbnails reach Telegram.
- [ ] **2. Continuous Link Hunter (`features/x/scraper.py`)**:
  - Continuous wheel-scroll loop with incremental DOM harvest on *every* scroll step.
  - Timeline article scoping (`article[data-testid="tweet"]`) to capture 100% of original posts AND retweets/reposts.
  - 3-strike convergence end-of-feed detector with lazy-load rescue nudge.
- [ ] **3. Database Migration & Repository (`data/models.py`, `data/repository.py`, `data/database.py`)**:
  - Add `task_id`, `source_profile`, `is_repost`, `position` to `seen_items`.
  - Add `source_profile`, `destination_channel_id`, `total_found`, `delivered_count`, `failed_count`, `next_post_at` to `harvest_tasks`.
  - Add auto-migration in `data/database.py`.
  - Repository methods: `create_harvest_job`, `bulk_insert_discovered_links`, `get_next_delivery_item` (Snowflake ID ASC).
- [ ] **4. Pure HTTP Delivery Engine (`services/queue_worker.py`)**:
  - Background worker picks up `DISCOVERED` items from DB without launching browser.
  - Calls `XAdapter.get_single_post()` via FxTwitter API with safe 0.5s-1.0s gap.
  - Delivers with 45-90s human pacing to Telegram channel.
- [ ] **5. Bot UI (`bot/keyboards.py`, `bot/handlers/sync_flow.py`)**:
  - `[ 🚀 Deep Harvest ]` button on Active Sources card.
  - Quantity picker: `[ 25 ]` `[ 50 ]` `[ 100 ]` `[ Max Profile ]`.
  - Live updating progress card (`Delivered: 12/84`).

---

## ⏳ Phase 2: Post-MVP / Future Polish (WAIT — Do NOT build today)

- [ ] Multi-platform harvesters (YouTube Shorts, Instagram Reels, TikTok).
- [ ] Paid subscription billing / access-key gating for external clients.
- [ ] Advanced analytics dashboard (total views, repost success rate charts).
- [ ] OCR watermark removal / video re-encoding with custom overlay logos.
- [ ] AI rewrite mode (using Groq to rephrase tweet text into original posts).
- [ ] **🚀 Deep Harvest Historical Teleportation / Fast-Forwarding**:
  - Instead of scrolling from top of profile through 100+ historical/already-seen posts step-by-step:
    - **Option A (Date Search Anchor)**: Extract oldest harvested tweet date (`YYYY-MM-DD`) from DB and navigate Playwright directly to `https://x.com/search?q=(from:username) until:YYYY-MM-DD&f=live` to start scrolling instantly where the archive left off.
    - **Option B (Turbo Skim)**: High-speed wheel scrolling with minimal delays until passing known tweet IDs, then dropping into normal human jitter and media extraction once entering unseen territory.
  - *Keep on hold until V2/staging environment so production scraping pipeline remains 100% stable.*

