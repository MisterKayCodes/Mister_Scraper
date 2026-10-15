"""
card_formatters.py — Shared card and queue rendering helpers.

Kept in bot/helpers so source_manager, deep_harvest, and sync_setup
can all import without circular dependency.
"""
from core.time_utils import now_wat


def format_source_diagnostic_card(src, failed_count: int = 0, pending_count: int = 0) -> str:
    """Renders the Mister_Channels gold-standard diagnostic feed card."""
    status = "ACTIVE ✅" if src.is_active else "PAUSED ⏸️"

    # Calculate countdown
    countdown_str = "Calculating..."
    if src.next_check:
        now = now_wat()
        if src.next_check > now:
            diff = src.next_check - now
            mins = int(diff.total_seconds() // 60)
            if mins > 60:
                countdown_str = f"In {mins // 60}h {mins % 60}m"
            else:
                countdown_str = f"In {mins} minutes"
        else:
            countdown_str = "Checking soon ⏳"

    # Format interval nicely
    interval_display = f"{src.interval_minutes} mins"
    if src.interval_minutes >= 60:
        hrs = src.interval_minutes / 60
        interval_display = f"{int(hrs) if hrs.is_integer() else hrs} hours"

    error_display = (
        f"<code>{src.last_error}</code>"
        if src.last_error and src.last_error != "None (Healthy)"
        else "None (Healthy) 🟢"
    )

    from services.queue_worker import get_rate_limit_status, get_delivery_status
    rl_status = get_rate_limit_status()
    if rl_status.get("is_limited") and rl_status.get("free_at"):
        now = now_wat()
        remaining_secs = int((rl_status["free_at"] - now).total_seconds())
        if remaining_secs > 0:
            error_display = f"⚠️ Rate Limited (Free in {remaining_secs // 60}m {remaining_secs % 60}s) ⏳"

    # Query live Conveyor delivery state for THIS target specifically
    del_status = get_delivery_status(target=src.target)
    delivery_line = ""
    if del_status.get("is_active"):
        rem = del_status.get("remaining_in_batch", 0)
        drop_secs = del_status.get("next_drop_secs", 0)
        delivery_line = (
            f"🚚 <b>Delivery:</b> DRIPPING ({rem} posts queued)\n"
            f"⏱️ <b>Next Drop:</b> In ~{drop_secs}s (human jitter)\n"
        )
    elif del_status.get("queue_size", 0) > 0:
        delivery_line = f"🚚 <b>Delivery:</b> {del_status['queue_size']} posts queued in Conveyor\n"
    elif pending_count > 0:
        delivery_line = f"🚚 <b>Delivery:</b> ⏳ Auto-Rehydrating ({pending_count} pending in DB)\n"
    else:
        delivery_line = "🚚 <b>Delivery:</b> Idle (Waiting for new posts)\n"

    # Format last posted time
    last_posted_display = "Never yet"
    if src.last_posted_at:
        now = now_wat()
        diff = now - src.last_posted_at
        total_secs = int(diff.total_seconds())
        if total_secs < 60:
            last_posted_display = f"Just now ({max(1, total_secs)}s ago)"
        elif total_secs < 3600:
            last_posted_display = f"{total_secs // 60}m ago"
        elif total_secs < 86400:
            hrs = total_secs // 3600
            mins = (total_secs % 3600) // 60
            last_posted_display = f"{hrs}h {mins}m ago"
        else:
            last_posted_display = src.last_posted_at.strftime("%b %d, %H:%M")

    card = (
        f"🔁 <b>Scraper Feed: @{src.target} ➔ {src.destination_channel_id}</b>\n"
        "───────────────────────────\n"
        f"⚡ <b>Status:</b> {status}\n"
        f"🔗 <b>Source:</b> <code>x.com/{src.target}</code>\n"
        f"📢 <b>Destination:</b> <code>{src.destination_channel_id}</code>\n"
        f"{delivery_line}"
        f"⏱️ <b>Interval:</b> Every {interval_display}\n"
        f"⏳ <b>Next Check:</b> {countdown_str}\n"
        f"📦 <b>Delivered:</b> {src.total_delivered or 0} items\n"
        f"🕒 <b>Last Posted:</b> {last_posted_display}\n"
        f"❌ <b>Failed:</b> {failed_count} items\n"
        f"⚠️ <b>Last Error:</b> {error_display}\n"
        "───────────────────────────"
    )
    return card


def format_queue_preview(pending_items: list, target_username: str, total_count: int = 0) -> str:
    """Renders a readable summary of items waiting in queue to be delivered.

    pending_items: up to 10 rows fetched for display links only.
    total_count: the true DB count — always shown in the header.
    """
    if not pending_items and total_count == 0:
        return ""
    display_total = total_count if total_count > 0 else len(pending_items)
    lines = [f"\n\n📬 <b>Delivery Queue ({display_total} pending):</b>"]
    for i, item in enumerate(pending_items[:10], 1):
        lines.append(f"{i}. <code>x.com/{target_username}/status/{item.content_id}</code>")
    if display_total > len(pending_items):
        lines.append(f"<i>...and {display_total - len(pending_items)} more queued</i>")
    return "\n".join(lines)
