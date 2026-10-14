from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from data.database import AsyncSessionLocal
from data.repository import Repository
from bot.keyboards import get_main_reply_keyboard

router = Router(name="menu_router")

def render_checklist_banner(settings) -> str:
    """Builds the dynamic self-collapsing checklist wizard banner."""
    has_channel = bool(settings.destination_channel_id)
    has_signature = bool(settings.custom_signature)

    # 1. Fresh state: No channel set
    if not has_channel:
        return (
            "🚀 <b>MISTER SCRAPER — Autopilot Content Engine</b>\n\n"
            "📋 <b>SETUP WIZARD (Get started in 60s):</b>\n"
            "1️⃣ ⚙️ <b>Link your Channel</b> (Tap 'Channel & Branding' below)\n"
            "2️⃣ ✍️ <b>Set your VIP Signature</b> (Optional)\n"
            "3️⃣ 🚀 <b>Add an X account</b> to auto-clone content!\n\n"
            "<i>Select an option below to begin:</i>"
        )

    # 2. Channel configured, no signature
    if not has_signature:
        return (
            "🚀 <b>MISTER SCRAPER — Autopilot Content Engine</b>\n\n"
            "📋 <b>SETUP WIZARD:</b>\n"
            f"✅ <b>Channel:</b> <code>{settings.destination_channel_id}</code>\n"
            "1️⃣ ✍️ <b>Set your VIP Signature</b> (Tap 'Channel & Branding' below)\n"
            "2️⃣ 🚀 <b>Add an X account</b> to auto-clone content!\n\n"
            "<i>Select an option below:</i>"
        )

    # 3. Fully configured: Collapsed Command Center
    return (
        "🚀 <b>MISTER SCRAPER — Command Center</b>\n\n"
        f"📢 <b>Target Channel:</b> <code>{settings.destination_channel_id}</code>\n"
        f"✍️ <b>Signature:</b> <i>{settings.custom_signature}</i>\n"
        f"🧹 <b>Link Stripping:</b> {'Active ✅' if settings.filter_mode == 1 else 'Disabled ⚪'}\n\n"
        "<i>Ready to harvest. Use the buttons below:</i>"
    )

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)

    banner = render_checklist_banner(settings)
    await message.answer(banner, reply_markup=get_main_reply_keyboard(bool(settings.destination_channel_id)), parse_mode="HTML")
