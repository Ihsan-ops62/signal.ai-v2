"""
infrastructure/database/postgres.py – PostgreSQL async connection.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from core.config import settings

# Convert to asyncpg compatible URL
dsn = settings.MONGODB_URI  # For now using MongoDB only; placeholder for future Postgres
# In a real implementation, you'd have a separate POSTGRES_DSN
# This file is a placeholder for future relational data needs
engine = None
AsyncSessionLocal = None
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Placeholder for PostgreSQL session."""
    # For now, the app uses MongoDB only; this is for future expansion
    raise NotImplementedError("PostgreSQL not yet configured. Use MongoDB.")