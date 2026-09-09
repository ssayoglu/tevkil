from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from bot.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=20,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


from sqlalchemy import text


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE bridge_sessions ADD COLUMN IF NOT EXISTS creator_agreed BOOLEAN DEFAULT FALSE;"))
            await conn.execute(text("ALTER TABLE bridge_sessions ADD COLUMN IF NOT EXISTS applicant_agreed BOOLEAN DEFAULT FALSE;"))
        except Exception as e:
            print(f"[DB] Migration uyarısı: {e}")


async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session
