# 📋 Backlog & MVP Scope: Mister_Scraper

> **Mode:** Fast-Shipping | **Target:** Working MVP Today | **Anti-Fog Rule:** No shiny distractions.

---

## 🎯 Phase 1: MVP Scope (Shipping TODAY)

### 1. 🧠 Core (The Brain)
- [x] `core/text_cleaner.py`: `MessageCleaner` with regex link & `@username` stripping + VIP signature injection.
- [x] `core/media_resolver.py`: Safe filename sanitization + extension resolution (`.mp4`, `.jpg`).
- [x] `extract_x_username()`: Flexible parser (`@user`, `x.com/user`, `x.com/user/media`).

### 2. 👁️ Features (The Eyes)
- [ ] `features/x/fast_meta.py`: Fix vxtwitter 403 via `TelegramBot` User-Agent & query param stripping.
- [x] `features/x/scraper.py`: Playwright stealth radar with chronological waterfall scraping (stops when encountering already completed tweets).
- [x] `features/x/adapter.py`: Normalized `ScrapedItem` dataclass interface.

### 3. 🧬 Services (The Carrier / Nervous System)
- [x] `services/downloader.py`: Atomic 128KB chunked media downloader.
- [ ] `services/queue_worker.py`: Two-Stage State Machine (`PENDING` -> `COMPLETED` / `FAILED`), automatic retries (max 3), and paced jitter (1-5s first post, 45-90s subsequent).
- [ ] `services/scheduler.py`: Cron runner supporting 30m, 2h, 6h, 12h, 24h intervals with `last_check`, `next_check`, and `last_error` tracking.

### 4. 👄 Bot UI / UX Specification (The Mouth)
- [x] **Dynamic Self-Collapsing Checklist Wizard** on `/start`.
- [x] **⚡ Quick Grab Flow**:
  - Drop single X link -> cleans caption -> offers inline choice: `[ 👤 Send to Me ]` vs `[ 📢 Post to Channel ]`.
- [ ] **🚀 Auto-Sync Flow & Pair Manager**:
  - Extended Intervals: `30m`, `2h`, `6h`, `12h`, `24h (Daily)`.
  - Diagnostic Feed Card:
    - Status: ACTIVE / PAUSED
    - Source ➔ Destination
    - Check Interval & Next Check countdown (`In Xm`)
    - Total Delivered count
    - Last Error: exact diagnostic or `None (Healthy)`
    - Controls: `[ ⏸️ Pause ]` | `[ 🔄 Check Now ]` | `[ 🗑️ Unlink ]`
- [x] **⚙️ Channel & Branding Flow**:
  - Channel binding, VIP signature footer, link-stripping toggle.

### 5. 🌐 API (The Wall Socket)
- [x] `POST /scrape`: Direct link scrape for `Mister_Chief`.
- [x] `GET /health` & `GET /status`: Background task health check.

---

## ⏳ Phase 2: Post-MVP / Future Polish (WAIT — Do NOT build today)

- [ ] Multi-platform harvesters (YouTube Shorts, Instagram Reels, TikTok).
- [ ] Paid subscription billing / access-key gating for external clients.
- [ ] Advanced analytics dashboard (total views, repost success rate charts).
- [ ] OCR watermark removal / video re-encoding with custom overlay logos.
- [ ] AI rewrite mode (using Groq to rephrase tweet text into original posts).
