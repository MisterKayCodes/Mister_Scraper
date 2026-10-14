from typing import Optional, List
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from .models import UserSetting, SeenItem, HarvestTask, ScheduledSource

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
        stmt = select(SeenItem).where(
            SeenItem.user_id == user_id,
            SeenItem.platform == platform,
            SeenItem.content_id == str(content_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def mark_as_seen(session: AsyncSession, user_id: int, platform: str, content_id: str) -> None:
        if not await Repository.is_duplicate(session, user_id, platform, content_id):
            item = SeenItem(user_id=user_id, platform=platform, content_id=str(content_id))
            session.add(item)
            await session.commit()

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
