from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from data.database import AsyncSessionLocal
from data.repository import Repository
from bot.keyboards import get_main_reply_keyboard

router = Router(name="menu_router")

def render_checklist_banner(settings, active_sources_count: int = 0) -> str:
    """Builds the dynamic self-collapsing checklist wizard banner."""
    has_channel = bool(settings.destination_channel_id)
    has_sources = active_sources_count > 0

    # 1. Fresh state: No channel set
    if not has_channel:
        return (
            "🚀 <b>MISTER SCRAPER — Autopilot Content Engine</b>\n\n"
            "📋 <b>SETUP WIZARD (Get started in 60s):</b>\n"
            "1️⃣ ⚙️ <b>Link your Channel</b> (Tap '⚙️ Channel & Branding')\n"
            "2️⃣ 🚀 <b>Add an X Profile</b> (Tap '🚀 Auto-Sync Channel')\n"
            "3️⃣ ⚡ <b>Sit back</b> as clean media flows to your channel!\n\n"
            "<i>Select an option below to begin:</i>"
        )

    # 2. Channel configured, but no X profiles linked yet
    if not has_sources:
        return (
            "🚀 <b>MISTER SCRAPER — Autopilot Content Engine</b>\n\n"
            "📋 <b>SETUP WIZARD:</b>\n"
            f"✅ <b>Destination Channel:</b> <code>{settings.destination_channel_id}</code>\n"
            "👉 <b>NEXT STEP:</b> Tap <b>'🚀 Auto-Sync Channel'</b> to link your first X profile!\n\n"
            "<i>Select an option below:</i>"
        )

    # 3. Fully configured: Collapsed Command Center with Live Stats
    return (
        "🚀 <b>MISTER SCRAPER — Command Center</b>\n\n"
        f"📢 <b>Channel:</b> <code>{settings.destination_channel_id}</code>\n"
        f"🔗 <b>Active Sources:</b> <b>{active_sources_count} profile(s) linked</b> ✅\n"
        f"✍️ <b>VIP Signature:</b> <i>{settings.custom_signature or 'None'}</i>\n"
        f"🧹 <b>Link Stripping:</b> {'Active ✅' if settings.filter_mode == 1 else 'Disabled ⚪'}\n\n"
        "<i>All systems operational. Tap '📋 Active Sources' to manage feeds:</i>"
    )

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)
        sources = await Repository.get_user_sources(session, message.from_user.id)

    banner = render_checklist_banner(settings, active_sources_count=len(sources))
    await message.answer(banner, reply_markup=get_main_reply_keyboard(bool(settings.destination_channel_id)), parse_mode="HTML")
