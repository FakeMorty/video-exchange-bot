import asyncio
from app.db import async_session, init_db
from app.services import get_user, get_or_create_user
from app.models import User

async def test_db():
    try:
        await init_db()
        async with async_session() as session:
            # Try to get or create a test user
            user, is_new = await get_or_create_user(session, 123456789, "test_user", "Test", "User")
            print(f"User: {user.username}, New: {is_new}, Balance: {user.balance}")
            print("DB check successful!")
    except Exception as e:
        print(f"DB check failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_db())
