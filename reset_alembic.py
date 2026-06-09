
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import DATABASE_URL

async def main():
    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        print("Dropping alembic_version table to allow fresh migration...")
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE;"))
        
        # If user permits full DB reset, we can uncomment this:
        # await conn.run_sync(Base.metadata.drop_all)
        
asyncio.run(main())
