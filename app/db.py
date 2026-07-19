from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import DATABASE_URL
from app.models import Base
# ПРИНУДИТЕЛЬНЫЙ ИМПОРТ МОДЕЛЕЙ для регистрации в Base.metadata

def _fix_url(url: str) -> str:
    if not url:
        return "sqlite+aiosqlite:///bot.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    if "sslmode=" in url:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        query_params.pop("sslmode", None)
        new_query = urllib.parse.urlencode(query_params, doseq=True)
        parsed = parsed._replace(query=new_query)
        url = urllib.parse.urlunparse(parsed)
        
    return url

def _is_supabase_pooler(url: str) -> bool:
    """True, если URL указывает на Supabase Supavisor pooler.

    Transaction pooler (порт 6543, pgbouncer-семантика) ломает prepared
    statements в asyncpg — для таких подключений их нужно отключить
    (statement_cache_size=0). Отключение безвредно и для session pooler
    (порт 5432), поэтому матчим по хосту без разбора порта.
    """
    return "pooler.supabase.com" in url


# Настройки для Render PostgreSQL (обязателен SSL)
connect_args = {}
engine_kwargs = {}
if "postgresql" in DATABASE_URL:
    connect_args = {"ssl": "require"}
    if _is_supabase_pooler(DATABASE_URL):
        # Supabase pooler (Supavisor в transaction mode) не поддерживает
        # prepared statements — отключаем их кэш в asyncpg, иначе будет
        # DuplicatePreparedStatementError / InvalidCachedStatementError.
        connect_args["statement_cache_size"] = 0
    # Serverless Postgres (Neon/Render/Supabase) принудительно закрывает
    # простаивающие соединения, поэтому пересоздаём их чуть раньше
    # и держим пул минимальным: лишние открытые коннекты 24/7 зря жгут
    # лимиты бесплатных тарифов (compute-часы Neon, коннекции Supabase/Aiven).
    # (для SQLite-фолбэка — NullPool, эти параметры там не поддерживаются)
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 2,
        "max_overflow": 3,
        "pool_timeout": 10,
    }

engine = create_async_engine(
    _fix_url(DATABASE_URL),
    echo=False,
    connect_args=connect_args,
    **engine_kwargs,
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


# ============================
# ДИАГНОСТИКА СБОЕВ БД
# ============================

# Маркеры исчерпания compute-квоты Neon (serverless Postgres, free tier)
_DB_QUOTA_MARKERS = (
    "compute time quota",
    "upgrade your plan",
)

# Маркеры недоступности БД (сеть, рестарт compute, закрытое соединение и т.п.)
_DB_DOWN_MARKERS = _DB_QUOTA_MARKERS + (
    "connection refused",
    "connection reset",
    "connection closed",
    "server closed the connection",
    "could not connect",
    "timeout expired",
    "connection timed out",
    "name or service not known",
    "no route to host",
    "ssl connection has been closed",
)


def _iter_exception_chain(exc: BaseException):
    """Обходит exc, её __cause__ и __context__ без зацикливания."""
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _chain_matches(exc: BaseException, markers: tuple) -> bool:
    for err in _iter_exception_chain(exc):
        msg = str(err).lower()
        if any(marker in msg for marker in markers):
            return True
    return False


def is_db_quota_error(exc: BaseException) -> bool:
    """True, если ошибка — исчерпание compute-квоты (Neon free tier)."""
    return _chain_matches(exc, _DB_QUOTA_MARKERS)


def is_db_unavailable_error(exc: BaseException) -> bool:
    """True, если БД временно недоступна (квота исчерпана или нет соединения)."""
    return _chain_matches(exc, _DB_DOWN_MARKERS)
