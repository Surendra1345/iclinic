"""Request schemas for outbound call endpoints."""
from pydantic import BaseModel, Field


class TriggerCallRequest(BaseModel):
    """Request body for starting an outbound patient call."""

    to_phone: str = Field(
        ...,
        description="Patient phone number. Use E.164 format, for example +919876543210.",
        examples=["+919876543210"],
    )
