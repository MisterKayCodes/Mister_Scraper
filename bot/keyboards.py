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
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)

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
    """Extended Interval selector for Auto-Sync."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏱️ 30m", callback_data="sync_int:30"),
        InlineKeyboardButton(text="⏱️ 2h", callback_data="sync_int:120"),
        InlineKeyboardButton(text="⏱️ 6h", callback_data="sync_int:360")
    )
    builder.row(
        InlineKeyboardButton(text="⏱️ 12h", callback_data="sync_int:720"),
        InlineKeyboardButton(text="⏱️ 24h (Daily)", callback_data="sync_int:1440")
    )
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="sync_cancel"))
    return builder.as_markup()

def get_source_item_kb(source_id: int, is_active: bool, has_pending: bool = False) -> InlineKeyboardMarkup:
    """Controls for a single linked source pair: instant Fast Refresh, Stealth Check Now, and Deliver Next."""
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸️ Pause Feed" if is_active else "▶️ Resume Feed"
    
    # Row 1: Fast Refresh vs Deep Scan
    builder.row(
        InlineKeyboardButton(text="🔄 Refresh", callback_data=f"src_refresh:{source_id}"),
        InlineKeyboardButton(text="⚡ Check Now", callback_data=f"src_check:{source_id}")
    )
    
    # Row 2: Deliver Next (if pending posts exist)
    if has_pending:
        builder.row(
            InlineKeyboardButton(text="▶️ Deliver Next Now", callback_data=f"src_deliver_next:{source_id}")
        )

    # Row 3: Pause and Delete
    builder.row(
        InlineKeyboardButton(text=toggle_text, callback_data=f"src_toggle:{source_id}"),
        InlineKeyboardButton(text="🗑️ Unlink Source", callback_data=f"src_del:{source_id}")
    )
    return builder.as_markup()

def get_delivery_action_deck_kb(
    author: str = "",
    content_id: str = "",
    batch_key: str = "",
    batch_count: int = 0,
    has_channel: bool = False
) -> InlineKeyboardMarkup:
    """Action deck attached to successful deliveries for instant, frictionless follow-up."""
    builder = InlineKeyboardBuilder()
    
    # Primary CTA: Grab another link
    builder.row(InlineKeyboardButton(text="⚡ Grab Another Link", callback_data="qg_next"))
    
    if has_channel:
        if batch_key and batch_count > 1:
            builder.row(
                InlineKeyboardButton(text=f"📢 Post All ({batch_count}) to Channel", callback_data=f"qg_b_all:{batch_key}"),
                InlineKeyboardButton(text="🧪 Test 1 to Channel", callback_data=f"qg_b_test:{batch_key}")
            )
        elif content_id:
            builder.row(InlineKeyboardButton(text="📢 Post to Channel", callback_data=f"qg_repost:{content_id}"))

    if author:
        builder.row(InlineKeyboardButton(text=f"🔄 Auto-Sync @{author}", callback_data=f"qg_sync_author:{author}"))
        
    return builder.as_markup()



