import asyncio
from data import init_db, Repository, AsyncSessionLocal

async def test_db():
    print("Testing Database Init...")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        user = await Repository.get_or_create_settings(session, user_id=12345)
        print(f"[OK] DB Vault Initialized! Settings created for User ID: {user.user_id}")
        
        # Test updating settings
        updated = await Repository.update_settings(session, user_id=12345, destination_channel_id="@test_channel")
        print(f"[OK] Settings Updated! Destination: {updated.destination_channel_id}")
        
        # Test duplicate check
        await Repository.mark_as_seen(session, user_id=12345, platform="x", content_id="tweet_999")
        is_dup = await Repository.is_duplicate(session, user_id=12345, platform="x", content_id="tweet_999")
        print(f"[OK] Dedup Check Working! Is Duplicate: {is_dup}")

if __name__ == "__main__":
    asyncio.run(test_db())
