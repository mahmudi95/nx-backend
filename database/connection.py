import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL") or \
    f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'neuraplex')}:{os.getenv('POSTGRES_PASSWORD', 'neuraplex')}@db:5432/{os.getenv('POSTGRES_DB', 'neuraplex')}"

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=True)

# Session factory
async_session = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# Base for models
Base = declarative_base()


async def get_db():
    """Dependency for getting database session"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def test_connection():
    """Test database connection"""
    try:
        async with async_session() as session:
            result = await session.execute(text("SELECT 1"))
            return {"status": "connected", "result": result.scalar()}
    except Exception as e:
        return {"status": "error", "error": str(e)}
