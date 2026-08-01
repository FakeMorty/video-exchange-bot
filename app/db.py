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


async def ensure_model_columns(target_engine=None) -> list[str]:
    """Догоняет схему СУЩЕСТВУЮЩИХ таблиц до моделей: добавляет недостающие колонки.

    init_db()/create_all НЕ изменяет существующие таблицы, а историческая
    цепочка alembic не покрывает все изменения моделей (пример: колонка
    users.lootbox_pity_counter есть в модели, но ни одна миграция её не
    добавляет) — из-за такого дрейфа бот падает с UndefinedColumnError на
    любой запрос.

    Для каждой недостающей колонки выполняется ADD COLUMN IF NOT EXISTS
    (без NOT NULL, чтобы не упасть на таблицах с данными) и бэкфилл
    скалярным дефолтом из модели. Возвращает список добавленных колонок.
    Идемпотентна — безопасно вызывать на каждом старте.
    """
    eng = target_engine or engine
    sync_eng = getattr(eng, "sync_engine", eng)
    if "sqlite" in str(sync_eng.url):
        return []  # локальный SQLite: полагаемся на create_all

    from sqlalchemy import inspect as sa_inspect, text
    from sqlalchemy.schema import CreateColumn

    dialect = sync_eng.dialect

    def _existing_columns(sync_conn) -> dict[str, set[str]]:
        inspector = sa_inspect(sync_conn)
        return {
            name: {c["name"] for c in inspector.get_columns(name)}
            for name in Base.metadata.tables.keys()
            if inspector.has_table(name)
        }

    added: list[str] = []
    async with eng.begin() as conn:
        existing = await conn.run_sync(_existing_columns)
        for table in Base.metadata.sorted_tables:
            cols_in_db = existing.get(table.name)
            if cols_in_db is None:
                continue  # таблицы нет — её создаст create_all
            for col in table.columns:
                if col.name in cols_in_db:
                    continue
                ddl = str(CreateColumn(col).compile(dialect=dialect))
                # NOT NULL опускаем: на непустой таблице добавление NOT NULL
                # колонки без server_default упало бы. Дефолт бэкфиллим ниже.
                ddl = ddl.replace(" NOT NULL", "")
                await conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS {ddl}')
                )
                added.append(f"{table.name}.{col.name}")
                # Бэкфилл Python-side скалярного дефолта (default=0, default=False,
                # default="active" и т.п.) — CreateColumn его в DDL не рендерит.
                default = col.default
                if default is not None and getattr(default, "is_scalar", False):
                    await conn.execute(
                        text(
                            f'UPDATE "{table.name}" SET "{col.name}" = :v '
                            f'WHERE "{col.name}" IS NULL'
                        ),
                        {"v": default.arg},
                    )
    return added


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
