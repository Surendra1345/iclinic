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
    awaiting_identity_verification: bool
    pending_intent: Optional[str]

    # ── Intent ────────────────────────────────────────────────────────────────
    # One of: "book", "reschedule", "cancel", "faq", "handoff", "unknown", "greet", "identity", "register", "close"
    intent: Optional[str]
    semantic_label: Optional[str]
    last_repeat_speech: Optional[str]
    availability_context: Optional[Dict[str, Any]]

    # ── Dialogue / LLM Context ────────────────────────────────────────────────
    messages: List[Dict[str, str]]  # list of {"role": "user"|"assistant"|"system", "content": "..."}
    latest_user_speech: str
    latest_agent_speech: str
    preferred_language: str
    language_confirmed: bool
    language_confidence: float

    # ── Slot & Appointment Context ────────────────────────────────────────────
    active_appointment_id: Optional[str]
    active_appointment_details: Optional[Dict[str, Any]]
    target_slot_id: Optional[str]
    target_slot_details: Optional[Dict[str, Any]]
    offered_slots: Optional[List[Dict[str, Any]]]
    preferred_specialty: Optional[str]
    preferred_location: Optional[str]
    preferred_doctor: Optional[str]
    preferred_date: Optional[str]
    preferred_appointment_type: Optional[str]
    awaiting_followup_visit: bool
    followup_candidates: Optional[List[Dict[str, Any]]]
    awaiting_followup_decision: bool
    awaiting_preferred_date: bool
    awaiting_patient_email: bool
    awaiting_cancel_confirmation: bool
    awaiting_change_action_choice: bool
    slot_reserved_at: Optional[str]
    booking_confirmed: bool

    # ── Control Flow & Error Flags ────────────────────────────────────────────
    silence_count: int
    low_confidence_count: int
    handoff_required: bool
    handoff_reason: Optional[str]
    awaiting_handoff_contact: bool
    handoff_completed: bool
    frontdesk_alert_sent: bool
    is_emergency: bool
    is_completed: bool
