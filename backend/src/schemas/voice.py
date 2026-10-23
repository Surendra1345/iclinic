"""Request schemas for the browser voice assistant endpoints."""
from typing import Optional

from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "en-IN"
