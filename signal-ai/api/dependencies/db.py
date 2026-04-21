"""
Database dependencies for FastAPI.
Provides database session injection.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from infrastructure.database.postgres import get_db as _get_db


async def get_db() -> AsyncSession:
    """
    Get database session for dependency injection.
    
    Returns:
        AsyncSession
    """
    async for session in _get_db():
        yield session
