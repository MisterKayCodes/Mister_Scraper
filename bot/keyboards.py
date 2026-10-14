from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_reply_keyboard(has_channel: bool = False) -> ReplyKeyboardMarkup:
    """Clean MVP menu layout with Active Sources."""
    kb = [
        [KeyboardButton(text="🚀 Auto-Sync Channel"), KeyboardButton(text="⚡ Quick Grab")],
        [KeyboardButton(text="📋 Active Sources"), KeyboardButton(text="⚙️ Channel & Branding")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_quick_grab_choice_kb(tweet_url: str) -> InlineKeyboardMarkup:
    """Inline choice after grabbing an X post."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Send to Me Here", callback_data="qg_send_me"),
        InlineKeyboardButton(text="📢 Post to Channel", callback_data="qg_post_channel")
    )
    return builder.as_markup()

def get_branding_inline_kb(filter_mode: int) -> InlineKeyboardMarkup:
    """Inline settings for channel, signature, and link-stripping."""
    builder = InlineKeyboardBuilder()
    strip_status = "ON (Clean) ✅" if filter_mode == 1 else "OFF (Keep All) ⚪"

    builder.row(InlineKeyboardButton(text="📢 Set Target Channel", callback_data="set_channel"))
    builder.row(InlineKeyboardButton(text="✍️ Edit VIP Signature", callback_data="set_signature"))
    builder.row(InlineKeyboardButton(text=f"🧹 Link Stripping: {strip_status}", callback_data="toggle_strip"))
    return builder.as_markup()

def get_interval_selection_kb() -> InlineKeyboardMarkup:
    """Interval selector for Auto-Sync."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏱️ Every 30m", callback_data="sync_int:30"),
        InlineKeyboardButton(text="⏱️ Every 1h", callback_data="sync_int:60"),
        InlineKeyboardButton(text="⏱️ Every 2h", callback_data="sync_int:120")
    )
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="sync_cancel"))
    return builder.as_markup()

def get_source_item_kb(source_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Controls for a single linked source pair."""
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸️ Pause" if is_active else "▶️ Resume"
    builder.row(
        InlineKeyboardButton(text=toggle_text, callback_data=f"src_toggle:{source_id}"),
        InlineKeyboardButton(text="🗑️ Delete Pair", callback_data=f"src_del:{source_id}")
    )
    return builder.as_markup()

