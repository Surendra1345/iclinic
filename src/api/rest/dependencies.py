from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.clients.postgres import get_db

# Type alias for use in endpoint parameters: db: DBSessionDep
DBSessionDep = Annotated[AsyncSession, Depends(get_db)]

__all__ = ["get_db", "DBSessionDep"]
