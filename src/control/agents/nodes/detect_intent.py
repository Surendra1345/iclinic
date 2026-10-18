"""Intent detection node — classifies caller intent using Gemini 2.0 Flash."""
import logging
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.prompts import INTENT_DETECTION_PROMPT
from src.control.agents.state import CallState
from src.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)


async def detect_intent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip()
    if not user_speech:
        return {"intent": "unknown"}

    lower = user_speech.lower()

    # Fast path 1: If slot was offered and patient is confirming, declining, or asking details
    if state.get("target_slot_id"):
        if any(w in lower for w in ["yes", "confirm", "sure", "book it", "please", "go ahead", "okay", "fine", "yep", "correct"]):
            return {"intent": "book"}
        if any(w in lower for w in ["no", "cancel", "don't", "different", "another", "change"]):
            return {"intent": "book"}
        if any(w in lower for w in ["location", "locations", "where", "address", "branch", "place", "area", "hospital", "clinic"]):
            return {"intent": "book"}
        if any(w in lower for w in ["i already said", "already told", "i said", "like i said", "as i said"]):
            return {"intent": "book"}

    # Fast path 2: Direct keyword patterns (0ms latency, eliminates Twilio timeout risks)
    if any(w in lower for w in ["reschedule", "change appointment", "postpone", "move appointment", "different time", "different day", "reschedule appointment"]):
        return {"intent": "reschedule"}
    if any(w in lower for w in ["cancel appointment", "drop appointment", "delete appointment", "cancel my appointment", "don't want the appointment"]):
        return {"intent": "cancel"}
    if any(w in lower for w in ["operator", "human", "representative", "front desk", "speak to receptionist", "speak to someone", "transfer me"]):
        return {"intent": "handoff"}
    # Medical advice check according to clinical protocol (transfer to triage nurse / front desk)
    if any(w in lower for w in ["prescribe", "what medicine", "which tablet", "medical diagnosis", "diagnose me"]):
        return {
            "intent": "handoff",
            "handoff_required": True,
            "handoff_reason": "Medical advice request",
            "latest_agent_speech": "I cannot provide medical advice. Let me transfer you to our triage nurse and front desk team right away.",
        }
    # Location and branch inquiries fast path
    if any(w in lower for w in ["location", "locations", "where are you", "where is", "address", "branch", "branches"]):
        return {"intent": "book"}
    # Patient reiteration
    if any(w in lower for w in ["i already said", "already told", "i said", "like i said", "as i said"]):
        return {"intent": "book"}
    # Booking & symptoms fast path
    if any(w in lower for w in [
        "book", "appointment", "doctor", "doc", "physician", "consult", "consultation", "see a doctor", "assist", "stomach",
        "pain", "belly", "abdominal", "fever", "cold", "cough", "headache", "chest", "heart", "skin", "rash",
        "orthopedic", "orthopaedic", "orthopedics", "orthopaedics",
        "shoulder", "knee", "back", "joint", "bone", "muscle", "fracture",
        "ankle", "wrist", "elbow", "hip", "leg", "arm", "foot", "neck",
        "spine", "arthritis", "sprain", "strain", "ligament", "tendon",
        "stiffness", "swelling", "sports injury", "sports injuries",
        "throat", "ear", "infection", "sick", "unwell", "ill", "visit"
    ]):
        return {"intent": "book"}


    # Fallback to Gemini 2.0 Flash for complex/ambiguous phrasing
    gemini = GeminiService()
    prompt = INTENT_DETECTION_PROMPT.format(user_speech=user_speech)

    try:
        raw_response = await gemini.generate_content(prompt, temperature=0.0)
        cleaned = raw_response.strip().upper()
        if "BOOK" in cleaned:
            intent = "book"
        elif "RESCHEDULE" in cleaned:
            intent = "reschedule"
        elif "CANCEL" in cleaned:
            intent = "cancel"
        elif "FAQ" in cleaned:
            intent = "faq"
        elif "HANDOFF" in cleaned:
            intent = "handoff"
        else:
            intent = "unknown"
    except Exception as e:
        logger.error(f"Intent detection failed: {e}")
        # Rule-based fallback
        lower_speech = user_speech.lower()
        if any(w in lower_speech for w in ["reschedule", "change", "postpone", "move"]):
            intent = "reschedule"
        elif any(w in lower_speech for w in ["cancel", "drop"]):
            intent = "cancel"
        elif any(w in lower_speech for w in ["book", "new", "schedule", "appointment", "see a doctor"]):
            intent = "book"
        elif any(w in lower_speech for w in ["operator", "human", "representative", "front desk", "speak to someone"]):
            intent = "handoff"
        else:
            intent = "unknown"

    return {"intent": intent}
