from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import DATABASE_URL
from app.models import Base
# ПРИНУДИТЕЛЬНЫЙ ИМПОРТ МОДЕЛЕЙ для регистрации в Base.metadata

def _fix_url(url: str) -> str:
    if not url:
        return "sqlite+aiosqlite:///bot.db"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

# Настройки для Render PostgreSQL (обязателен SSL)
connect_args = {}
if "postgresql" in DATABASE_URL:
    connect_args = {"ssl": "require"}

engine = create_async_engine(
    _fix_url(DATABASE_URL),
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
