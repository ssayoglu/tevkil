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
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tbb_sicil_no VARCHAR(32);"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS baro_verified_at TIMESTAMP;"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS baro_verification_status VARCHAR(32) DEFAULT 'NONE';"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS baro_document_file_id VARCHAR(255);"))
        except Exception as e:
            print(f"[DB] Migration uyarısı: {e}")


async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session
