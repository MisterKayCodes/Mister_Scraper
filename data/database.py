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

        await conn.run_sync(run_migrations)
