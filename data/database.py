from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import config

class Base(DeclarativeBase):
    pass

engine = create_async_engine(config.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Auto-migration for SQLite: add new diagnostic columns if missing
        def run_migrations(connection):
            res = connection.exec_driver_sql("PRAGMA table_info(scheduled_sources)").fetchall()
            existing = [r[1] for r in res]

            if "total_delivered" not in existing:
                connection.exec_driver_sql("ALTER TABLE scheduled_sources ADD COLUMN total_delivered INTEGER DEFAULT 0")
            if "last_posted_at" not in existing:
                connection.exec_driver_sql("ALTER TABLE scheduled_sources ADD COLUMN last_posted_at TIMESTAMP NULL")
            if "last_error" not in existing:
                connection.exec_driver_sql("ALTER TABLE scheduled_sources ADD COLUMN last_error TEXT NULL")

            seen_res = connection.exec_driver_sql("PRAGMA table_info(seen_items)").fetchall()
            seen_cols = [r[1] for r in seen_res]
            if "status" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN status VARCHAR(32) DEFAULT 'DISCOVERED'")
            if "retry_count" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN retry_count INTEGER DEFAULT 0")
            if "error_message" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN error_message TEXT NULL")
            if "telegram_file_id" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN telegram_file_id VARCHAR(256) NULL")
            if "media_type" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN media_type VARCHAR(32) DEFAULT 'video'")
            if "clean_caption" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN clean_caption TEXT NULL")
            if "updated_at" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN updated_at TIMESTAMP NULL")
            if "task_id" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN task_id INTEGER NULL")
            if "source_profile" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN source_profile VARCHAR(128) NULL")
            if "url" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN url VARCHAR(512) NULL")
            if "is_repost" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN is_repost BOOLEAN DEFAULT 0")
            if "position" not in seen_cols:
                connection.exec_driver_sql("ALTER TABLE seen_items ADD COLUMN position INTEGER DEFAULT 0")

            # harvest_tasks migrations
            ht_res = connection.exec_driver_sql("PRAGMA table_info(harvest_tasks)").fetchall()
            ht_cols = [r[1] for r in ht_res]
            if "source_profile" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN source_profile VARCHAR(128) NULL")
            if "destination_channel_id" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN destination_channel_id VARCHAR(128) NULL")
            if "total_found" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN total_found INTEGER DEFAULT 0")
            if "delivered_count" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN delivered_count INTEGER DEFAULT 0")
            if "failed_count" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN failed_count INTEGER DEFAULT 0")
            if "last_error" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN last_error TEXT NULL")
            if "next_post_at" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN next_post_at TIMESTAMP NULL")
            if "started_at" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            if "hunt_finished_at" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN hunt_finished_at TIMESTAMP NULL")
            if "finished_at" not in ht_cols:
                connection.exec_driver_sql("ALTER TABLE harvest_tasks ADD COLUMN finished_at TIMESTAMP NULL")

        await conn.run_sync(run_migrations)
