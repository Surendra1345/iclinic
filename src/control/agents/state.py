"""LangGraph CallState definition for patient phone interactions."""
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class CallState(TypedDict, total=False):
    # ── Session Identifiers ───────────────────────────────────────────────────
    conversation_id: str
    call_sid: str
    channel: str
    patient_phone: str

    # ── Patient Identity ──────────────────────────────────────────────────────
    patient_id: Optional[str]
    patient_name: Optional[str]
    patient_dob: Optional[str]
    patient_email: Optional[str]
    is_verified: bool
    verify_attempts: int
    is_new_patient: bool

    # ── Intent ────────────────────────────────────────────────────────────────
    # One of: "book", "reschedule", "cancel", "faq", "handoff", "unknown"
    intent: Optional[str]

    # ── Dialogue / LLM Context ────────────────────────────────────────────────
    messages: List[Dict[str, str]]  # list of {"role": "user"|"assistant"|"system", "content": "..."}
    latest_user_speech: str
    latest_agent_speech: str

    # ── Slot & Appointment Context ────────────────────────────────────────────
    active_appointment_id: Optional[str]
    active_appointment_details: Optional[Dict[str, Any]]
    target_slot_id: Optional[str]
    target_slot_details: Optional[Dict[str, Any]]
    preferred_specialty: Optional[str]
    preferred_location: Optional[str]
    slot_reserved_at: Optional[str]
    booking_confirmed: bool

    # ── Control Flow & Error Flags ────────────────────────────────────────────
    silence_count: int
    low_confidence_count: int
    handoff_required: bool
    handoff_reason: Optional[str]
    is_completed: bool
