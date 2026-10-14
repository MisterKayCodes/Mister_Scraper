# 📋 Backlog & MVP Scope: Mister_Scraper

> **Mode:** Fast-Shipping | **Target:** Working MVP Today | **Anti-Fog Rule:** No shiny distractions.

---

## 🎯 Phase 1: MVP Scope (Shipping TODAY)

### 1. 🧠 Core (The Brain)
- [ ] `core/text_cleaner.py`: `MessageCleaner` with regex link & `@username` stripping + VIP signature injection.
- [ ] `core/media_resolver.py`: Safe filename sanitization + extension resolution (`.mp4`, `.jpg`).

### 2. 👁️ Features (The Eyes)
- [ ] `features/x/fast_meta.py`: Lightweight vxtwitter scraper for single links.
- [ ] `features/x/scraper.py`: Playwright stealth radar for profile media tab scraping.
- [ ] `features/x/adapter.py`: Normalized `ScrapedItem` dataclass interface.

### 3. 🧬 Services (The Carrier / Nervous System)
- [ ] `services/downloader.py`: Atomic 128KB chunked media downloader.
- [ ] `services/queue_worker.py`: Background conveyor belt with 60–120s anti-ban jitter intervals.
- [ ] `services/scheduler.py`: 60-minute loop checking monitored X profiles.

### 4. 👄 Bot UI / UX Specification (The Mouth)
- [ ] **Dynamic Self-Collapsing Checklist Wizard** on `/start`:
  - 1️⃣ ⚙️ Link Destination Channel (disappears once set).
  - 2️⃣ ✍️ Set VIP Signature/Link (disappears once set).
  - 3️⃣ 🚀 Ready: Add your first X target!
  - *Collapses into compact status dashboard once fully configured.*
- [ ] **⚡ Quick Grab Flow**:
  - Drop single X link -> cleans caption -> offers inline choice:
    `[ 👤 Send to Me Here ]` vs `[ 📢 Post to @MyChannel ]`.
- [ ] **🚀 Auto-Sync Flow**:
  - Track `@username` -> set interval (30m, 1h, 2h) -> background scheduler auto-posts clean content.
- [ ] **⚙️ Channel & Branding Flow**:
  - Set target channel (`@channel` or numeric ID), edit signature footer, toggle link-stripping ON/OFF.

### 5. 🌐 API (The Wall Socket)
- [ ] `POST /scrape`: Direct link scrape for `Mister_Chief`.
- [ ] `GET /health` & `GET /status`: Background task health check.

---

## ⏳ Phase 2: Post-MVP / Future Polish (WAIT — Do NOT build today)

- [ ] Multi-platform harvesters (YouTube Shorts, Instagram Reels, TikTok).
- [ ] Paid subscription billing / access-key gating for external clients.
- [ ] Advanced analytics dashboard (total views, repost success rate charts).
- [ ] OCR watermark removal / video re-encoding with custom overlay logos.
- [ ] AI rewrite mode (using Groq to rephrase tweet text into original posts).
