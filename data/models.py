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
    """
    Two-Stage State Machine for Scraped Items:
    status='DISCOVERED' -> status='COMPLETED' (posted) or status='FAILED'
    """
    __tablename__ = "seen_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), default="x", index=True)
    content_id = Column(String(128), nullable=False, index=True) # tweet_id
    user_id = Column(BigInteger, nullable=False, index=True)
    status = Column(String(32), default="DISCOVERED")            # DISCOVERED, COMPLETED, FAILED
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HarvestTask(Base):
    """Tracks batch operations and conveyor belt queue status."""
    __tablename__ = "harvest_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    target = Column(String(128), nullable=False)
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
    """Monitored accounts with diagnostics (Mister_Channels gold standard)."""
    __tablename__ = "scheduled_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    platform = Column(String(32), default="x")
    target = Column(String(128), nullable=False)                # e.g. DailyLoud
    destination_channel_id = Column(String(128), nullable=False)
    interval_minutes = Column(Integer, default=120)             # 30, 120, 360, 720, 1440
    is_active = Column(Boolean, default=True)
    total_delivered = Column(Integer, default=0)
    last_check = Column(DateTime, nullable=True)
    next_check = Column(DateTime, nullable=True)
    last_posted_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
