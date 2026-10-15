from typing import Optional, List
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from .models import UserSetting, SeenItem, HarvestTask, ScheduledSource
from core.time_utils import now_wat

class Repository:
    """The Vault: Pure database access layer."""

    @staticmethod
    async def get_or_create_settings(session: AsyncSession, user_id: int) -> UserSetting:
        stmt = select(UserSetting).where(UserSetting.user_id == user_id)
        result = await session.execute(stmt)
        settings = result.scalar_one_or_none()
        if not settings:
            settings = UserSetting(user_id=user_id)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings

    @staticmethod
    async def update_settings(session: AsyncSession, user_id: int, **kwargs) -> UserSetting:
        settings = await Repository.get_or_create_settings(session, user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        await session.commit()
        await session.refresh(settings)
        return settings

    @staticmethod
    async def is_duplicate(session: AsyncSession, user_id: int, platform: str, content_id: str) -> bool:
        """True ONLY if the item has already been successfully COMPLETED (posted)."""
        stmt = select(SeenItem).where(
            SeenItem.user_id == user_id,
            SeenItem.platform == platform,
            SeenItem.content_id == str(content_id),
            SeenItem.status == "COMPLETED"
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def mark_as_discovered(session: AsyncSession, user_id: int, platform: str, content_id: str) -> SeenItem:
        stmt = select(SeenItem).where(
            SeenItem.user_id == user_id,
            SeenItem.platform == platform,
            SeenItem.content_id == str(content_id)
        )
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()
        if not item:
            item = SeenItem(user_id=user_id, platform=platform, content_id=str(content_id), status="DISCOVERED")
            session.add(item)
            await session.commit()
            await session.refresh(item)
        return item

    @staticmethod
    async def get_pending_items(session: AsyncSession, user_id: int, platform: str = "x", limit: int = 10) -> List[SeenItem]:
        """Fetch discovered/pending items that have not yet been marked completed or failed."""
        stmt = (
            select(SeenItem)
            .where(
                SeenItem.user_id == user_id,
                SeenItem.platform == platform,
                SeenItem.status.in_(["DISCOVERED", "PENDING", "QUEUED"])
            )
            .order_by(SeenItem.created_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_pending_count(session: AsyncSession, user_id: int, platform: str = "x") -> int:
        from sqlalchemy import func
        stmt = (
            select(func.count(SeenItem.id))
            .where(
                SeenItem.user_id == user_id,
                SeenItem.platform == platform,
                SeenItem.status.in_(["DISCOVERED", "PENDING", "QUEUED"])
            )
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def mark_as_completed(
        session: AsyncSession,
        user_id: int,
        platform: str,
        content_id: str,
        telegram_file_id: Optional[str] = None,
        media_type: str = "video",
        clean_caption: Optional[str] = None
    ) -> None:
        stmt = select(SeenItem).where(
            SeenItem.user_id == user_id,
            SeenItem.platform == platform,
            SeenItem.content_id == str(content_id)
        )
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            item.status = "COMPLETED"
            item.error_message = None
            if telegram_file_id:
                item.telegram_file_id = telegram_file_id
            if media_type:
                item.media_type = media_type
            if clean_caption:
                item.clean_caption = clean_caption
        else:
            item = SeenItem(
                user_id=user_id,
                platform=platform,
                content_id=str(content_id),
                status="COMPLETED",
                telegram_file_id=telegram_file_id,
                media_type=media_type,
                clean_caption=clean_caption
            )
            session.add(item)
        await session.commit()

    @staticmethod
    async def mark_as_failed(session: AsyncSession, user_id: int, platform: str, content_id: str, error_msg: str) -> None:
        stmt = select(SeenItem).where(
            SeenItem.user_id == user_id,
            SeenItem.platform == platform,
            SeenItem.content_id == str(content_id)
        )
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            item.status = "FAILED"
            item.retry_count = (item.retry_count or 0) + 1
            item.error_message = error_msg
        else:
            item = SeenItem(user_id=user_id, platform=platform, content_id=str(content_id), status="FAILED", error_message=error_msg, retry_count=1)
            session.add(item)
        await session.commit()

    @staticmethod
    async def update_source_stats(session: AsyncSession, source_id: int, delivered_increment: int = 0, last_error: Optional[str] = None) -> None:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id)
        result = await session.execute(stmt)
        src = result.scalar_one_or_none()
        if src:
            if delivered_increment > 0:
                src.total_delivered = (src.total_delivered or 0) + delivered_increment
                src.last_posted_at = now_wat()
            if last_error is not None:
                src.last_error = last_error
            await session.commit()

    @staticmethod
    async def create_harvest_job(
        session: AsyncSession,
        user_id: int,
        source_profile: str,
        destination_channel_id: str,
        platform: str = "x"
    ) -> HarvestTask:
        """Initializes a new two-phase harvest job (Link Hunter -> Delivery Engine)."""
        clean_target = source_profile.lstrip("@").strip()
        task = HarvestTask(
            user_id=user_id,
            target=clean_target,
            source_profile=clean_target,
            destination_channel_id=destination_channel_id,
            platform=platform,
            status="HUNTING",
            total_found=0,
            delivered_count=0,
            failed_count=0
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

    @staticmethod
    async def bulk_insert_discovered_links(
        session: AsyncSession,
        task_id: int,
        user_id: int,
        source_profile: str,
        items: List[dict],
        platform: str = "x"
    ) -> int:
        """
        Inserts harvested links into seen_items idempotently.
        Items: [{'id': '198...', 'url': '...', 'is_repost': False, 'position': 1}, ...]
        Returns count of newly inserted items.
        """
        from datetime import datetime
        clean_target = source_profile.lstrip("@").strip()
        new_count = 0

        for it in items:
            tid = str(it.get("id"))
            # Check duplicate
            stmt = select(SeenItem).where(
                SeenItem.user_id == user_id,
                SeenItem.platform == platform,
                SeenItem.content_id == tid
            )
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()
            if not existing:
                item = SeenItem(
                    task_id=task_id,
                    user_id=user_id,
                    platform=platform,
                    source_profile=clean_target,
                    content_id=tid,
                    url=it.get("url") or f"https://x.com/{clean_target}/status/{tid}",
                    is_repost=it.get("is_repost", False),
                    position=it.get("position", 0),
                    status="DISCOVERED"
                )
                session.add(item)
                new_count += 1

        if new_count > 0:
            stmt_task = select(HarvestTask).where(HarvestTask.id == task_id)
            res_task = await session.execute(stmt_task)
            t = res_task.scalar_one_or_none()
            if t:
                t.total_found = (t.total_found or 0) + new_count
                t.total_items = t.total_found

        await session.commit()
        return new_count

    @staticmethod
    async def get_next_harvest_item(session: AsyncSession, task_id: int) -> Optional[SeenItem]:
        """Fetches the next queued item for delivery ordered oldest-to-newest by Snowflake ID."""
        from sqlalchemy import cast, BigInteger
        stmt = (
            select(SeenItem)
            .where(
                SeenItem.task_id == task_id,
                SeenItem.status.in_(["DISCOVERED", "PENDING"])
            )
            .order_by(cast(SeenItem.content_id, BigInteger).asc())
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def create_task(session: AsyncSession, user_id: int, target: str, platform: str = "x") -> HarvestTask:
        task = HarvestTask(user_id=user_id, target=target, platform=platform)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task

    @staticmethod
    async def update_task(session: AsyncSession, task_id: int, **kwargs) -> Optional[HarvestTask]:
        stmt = select(HarvestTask).where(HarvestTask.id == task_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if task:
            for k, v in kwargs.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            await session.commit()
            await session.refresh(task)
        return task

    @staticmethod
    async def add_scheduled_source(session: AsyncSession, user_id: int, target: str, destination_channel: str, interval_minutes: int = 60) -> ScheduledSource:
        source = ScheduledSource(
            user_id=user_id,
            target=target,
            destination_channel_id=destination_channel,
            interval_minutes=interval_minutes
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        return source

    @staticmethod
    async def get_active_sources(session: AsyncSession) -> List[ScheduledSource]:
        stmt = select(ScheduledSource).where(ScheduledSource.is_active == True)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_user_sources(session: AsyncSession, user_id: int) -> List[ScheduledSource]:
        stmt = select(ScheduledSource).where(ScheduledSource.user_id == user_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def toggle_source(session: AsyncSession, source_id: int, user_id: int) -> Optional[ScheduledSource]:
        stmt = select(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == user_id)
        result = await session.execute(stmt)
        src = result.scalar_one_or_none()
        if src:
            src.is_active = not src.is_active
            await session.commit()
            await session.refresh(src)
        return src

    @staticmethod
    async def delete_source(session: AsyncSession, source_id: int, user_id: int) -> bool:
        stmt = delete(ScheduledSource).where(ScheduledSource.id == source_id, ScheduledSource.user_id == user_id)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0
