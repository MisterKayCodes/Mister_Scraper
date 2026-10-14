from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext

from data.database import AsyncSessionLocal
from data.repository import Repository
from bot.states import SetupStates
from bot.keyboards import get_branding_inline_kb

router = Router(name="settings_router")

@router.message(F.text == "⚙️ Channel & Branding")
async def btn_branding(message: types.Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, message.from_user.id)

    channel_display = f"<code>{settings.destination_channel_id}</code>" if settings.destination_channel_id else "<i>Not set ❌</i>"
    signature_display = f"<i>{settings.custom_signature}</i>" if settings.custom_signature else "<i>None (raw text)</i>"
    strip_display = "Active (Competitor links & @handles removed) ✅" if settings.filter_mode == 1 else "Disabled ⚪"

    card = (
        "⚙️ <b>Channel & Branding Settings</b>\n\n"
        f"📢 <b>Destination Channel:</b> {channel_display}\n"
        f"✍️ <b>VIP Signature:</b> {signature_display}\n"
        f"🧹 <b>Link Stripping:</b> {strip_display}\n\n"
        "Tap an option below to update your setup:"
    )

    await message.answer(card, reply_markup=get_branding_inline_kb(settings.filter_mode or 1), parse_mode="HTML")

@router.callback_query(F.data == "set_channel")
async def cb_set_channel(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SetupStates.waiting_for_channel)
    await callback.message.edit_text(
        "📢 <b>Set Destination Channel</b>\n\n"
        "Please send your channel's public username or numeric ID:\n"
        "<i>e.g. @MyCryptoVIP or -100123456789</i>\n\n"
        "⚠️ <b>Important:</b> Ensure this bot has been added as an <b>Admin</b> to that channel so it has posting permissions!",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(SetupStates.waiting_for_channel)
async def process_channel_input(message: types.Message, state: FSMContext):
    channel_id = message.text.strip()
    await state.clear()

    async with AsyncSessionLocal() as session:
        await Repository.update_settings(session, message.from_user.id, destination_channel_id=channel_id)

    await message.answer(
        f"✅ <b>Destination Channel Saved:</b> <code>{channel_id}</code>\n\n"
        "Type /start to return to the Command Center.",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "set_signature")
async def cb_set_signature(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SetupStates.waiting_for_signature)
    await callback.message.edit_text(
        "✍️ <b>Set VIP Signature / Custom Footer</b>\n\n"
        "Send the text you want appended to the bottom of every clean post.\n"
        "<i>Example:</i>\n"
        "<code>🚀 Join our VIP Channel: https://t.me/our_vip</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(SetupStates.waiting_for_signature)
async def process_signature_input(message: types.Message, state: FSMContext):
    sig = message.text.strip()
    await state.clear()

    async with AsyncSessionLocal() as session:
        await Repository.update_settings(session, message.from_user.id, custom_signature=sig)

    await message.answer(
        f"✅ <b>VIP Signature Updated!</b>\n\n"
        f"<i>Preview:</i>\n{sig}\n\n"
        "Type /start to return to the Command Center.",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "toggle_strip")
async def cb_toggle_strip(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        settings = await Repository.get_or_create_settings(session, callback.from_user.id)
        new_mode = 0 if settings.filter_mode == 1 else 1
        await Repository.update_settings(session, callback.from_user.id, filter_mode=new_mode)

    await callback.answer(f"Link Stripping: {'Active ✅' if new_mode == 1 else 'Disabled ⚪'}")
    # Refresh screen
    await btn_branding(callback.message, FSMContext(storage=None, key=None))
