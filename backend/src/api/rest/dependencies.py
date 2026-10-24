from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.services.auth_service import verify_token
from src.data.clients.postgres import get_db

# Type alias for use in endpoint parameters: db: DBSessionDep
DBSessionDep = Annotated[AsyncSession, Depends(get_db)]


async def require_frontdesk(authorization: Annotated[Optional[str], Header()] = None) -> str:
    """Allow a request only with a valid front desk token ("Authorization: Bearer <token>")."""
    scheme, _, token = (authorization or "").partition(" ")
    email = verify_token(token.strip()) if scheme.lower() == "bearer" else None
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Please log in to the front desk dashboard.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return email


__all__ = ["get_db", "DBSessionDep", "require_frontdesk"]
