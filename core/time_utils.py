from datetime import datetime, timezone, timedelta

# West Africa Time (WAT) = UTC+1
# All Mister_Scraper timestamps use WAT for display and scheduling logic.
WAT = timezone(timedelta(hours=1))


def now_wat() -> datetime:
    """Returns the current time in WAT (UTC+1). Use everywhere instead of datetime.utcnow()."""
    return datetime.now(WAT).replace(tzinfo=None)  # naive datetime, WAT wall-clock


def snowflake_to_datetime(snowflake_id: int | str) -> datetime:
    """
    Decodes a Twitter/X Snowflake ID into its UTC creation datetime.
    Twitter epoch begins at 1288834974657 ms (Nov 4, 2010 01:42:54.657 UTC).
    """
    sid = int(snowflake_id)
    timestamp_ms = (sid >> 22) + 1288834974657
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
