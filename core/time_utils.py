from datetime import datetime, timezone, timedelta

# West Africa Time (WAT) = UTC+1
# All Mister_Scraper timestamps use WAT for display and scheduling logic.
WAT = timezone(timedelta(hours=1))


def now_wat() -> datetime:
    """Returns the current time in WAT (UTC+1). Use everywhere instead of datetime.utcnow()."""
    return datetime.now(WAT).replace(tzinfo=None)  # naive datetime, WAT wall-clock
