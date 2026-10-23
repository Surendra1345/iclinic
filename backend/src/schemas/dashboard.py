"""Request / response schemas for the chat and front-desk dashboard endpoints."""
from typing import Optional

from pydantic import BaseModel


class ChatMessageRequest(BaseModel):
    message: str
    patient_phone: Optional[str] = None
    patient_name: Optional[str] = None
    patient_email: Optional[str] = None
    session_id: Optional[str] = None
    generate_audio: Optional[bool] = False


class AppointmentResponse(BaseModel):
    id: str
    patient_name: str
    patient_phone: str
    doctor_name: str
    specialty: str
    location_name: str
    location_address: str
    start_time: str
    end_time: str
    status: str
    created_at: str


class UpdateForwardedRequest(BaseModel):
    status: str = "contacted"  # "pending", "contacted", "resolved"
    notes: Optional[str] = None
