from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger
from .database import Base

class UserSetting(Base):
    """Stores per-user channel routing, custom branding signature, and filter modes."""
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    destination_channel_id = Column(String(128), nullable=True) # e.g. -10012345678 or @my_vip
    custom_signature = Column(Text, nullable=True)             # e.g. "🚀 Join VIP: t.me/vip"
    filter_mode = Column(Integer, default=1)                   # 0=Keep, 1=Strip links/handles, 2=Replace, 3=Nuke
    media_filter = Column(String(32), default="any")           # any, video, photo
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SeenItem(Base):
    """Tracks seen post/tweet IDs to prevent duplicate downloads and reposts."""
    __tablename__ = "seen_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), default="x", index=True)      # x, youtube, etc.
    content_id = Column(String(128), nullable=False, index=True) # e.g. tweet_id or video_id
    user_id = Column(BigInteger, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class HarvestTask(Base):
    """Tracks batch operations and conveyor belt queue status."""
    __tablename__ = "harvest_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    target = Column(String(128), nullable=False)                # e.g. @CryptoWhale
    platform = Column(String(32), default="x")
    status = Column(String(32), default="ACTIVE")               # ACTIVE, PAUSED, STOPPED, COMPLETED
    total_items = Column(Integer, default=0)
    processed_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    last_msg_id = Column(Integer, nullable=True)
    next_post_time = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduledSource(Base):
    """Monitored accounts that the scheduler checks periodically."""
    __tablename__ = "scheduled_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    platform = Column(String(32), default="x")
    target = Column(String(128), nullable=False)                # e.g. @CryptoWhale
    destination_channel_id = Column(String(128), nullable=False)
    interval_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    last_check = Column(DateTime, nullable=True)
    next_check = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
