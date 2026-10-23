"""Handoff node — escalates call to front desk and notifies staff."""
import logging
import uuid
from typing import Any, Dict
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.config.settings import settings
from src.constants.enums import OutcomeType
from src.data.repositories.conversation_repository import ConversationRepository
from src.control.agents.tools.registration_tools import extract_email, extract_phone
from src.core.services.notification_service import NotificationService
from src.core.services.medical_safety_service import is_emergency_report

logger = logging.getLogger(__name__)


async def handoff_to_front_desk_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    reason = state.get("handoff_reason") or "Patient requested front desk transfer"
    convo_id = state.get("conversation_id")
    call_sid = state.get("call_sid")
    channel = state.get("channel", "outbound_call")
    speech = state.get("latest_agent_speech")

    web_channel = channel in ("chat", "voice_assistant")
    # The chat UI may populate patient_phone from a configured demo default.
    # For web conversations, only trust a stored phone after verification or
    # a number explicitly supplied in this callback turn.
    stored_phone = state.get("patient_phone") if not web_channel or state.get("is_verified") else None
    patient_phone = stored_phone or extract_phone(state.get("latest_user_speech", ""))
    identity_verified = bool(state.get("is_verified"))
    stored_email = state.get("patient_email") if not web_channel or identity_verified else None
    patient_email = stored_email or extract_email(state.get("latest_user_speech", ""))
    # Do not present an unverified chat utterance as a confirmed patient name.
    patient_name = state.get("patient_name") if identity_verified else None
    contact_refusal = any(
        phrase in (state.get("latest_user_speech", "").lower())
        for phrase in ("skip", "no contact", "rather not", "prefer not", "don't share", "do not share", "can't provide")
    )
    contact_refusal = contact_refusal or state.get("latest_user_speech", "").strip().lower() in {
        "no", "no thanks", "no thank you", "i prefer not", "i don't want to share that"
    }

    user_speech_lower = (state.get("latest_user_speech") or "").lower()
    is_emergency_case = (
        bool(state.get("is_emergency"))
        or reason == "medical_emergency"
        or is_emergency_report(state.get("latest_user_speech", ""))
    )

    if is_emergency_case:
        emergency_speech = (
            "This sounds like a serious medical emergency. Please call emergency services (112 or 108) "
            "or go to the nearest hospital emergency room immediately. "
            "Do not wait for a clinic appointment or callback."
        )
        # Guard: only send the emergency alert once, even if the patient
        # sends additional messages while the emergency state is active.
        already_alerted = bool(state.get("frontdesk_alert_sent"))
        if convo_id and not already_alerted:
            try:
                repo = ConversationRepository(db)
                await repo.update_collected_details(
                    uuid.UUID(convo_id),
                    {
                        "is_emergency": True,
                        "handoff_reason": "medical_emergency",
                        "awaiting_handoff_contact": False,
                        "handoff_completed": True,
                    },
                )
                await repo.close(
                    conversation_id=uuid.UUID(convo_id),
                    outcome=OutcomeType.HANDED_TO_FRONT_DESK,
                    handoff_reason="medical_emergency",
                )
                notif_service = NotificationService(db)
                await notif_service.send_frontdesk_alert_email(
                    reason="URGENT MEDICAL EMERGENCY REPORTED",
                    call_details={
                        "call_sid": call_sid,
                        "conversation_id": convo_id,
                        "channel": channel,
                        "patient_phone": patient_phone,
                        "patient_email": patient_email,
                        "patient_name": patient_name,
                        "patient_id": state.get("patient_id"),
                        "identity_verified": identity_verified,
                        "emergency": True,
                    },
                )
                already_alerted = True
            except Exception as e:
                logger.error(f"Error executing emergency handoff DB operations: {e}")

        return {
            "is_emergency": True,
            "handoff_required": True,
            "awaiting_handoff_contact": False,
            "handoff_completed": True,
            "frontdesk_alert_sent": already_alerted,
            "is_completed": True,
            "latest_agent_speech": emergency_speech,
        }

    # Chat and browser voice have no caller ID. Ask once for a callback method
    # before promising that staff can follow up.
    if web_channel and not (patient_phone or patient_email) and not contact_refusal:
        if state.get("awaiting_handoff_contact"):
            prompt = "Please provide a callback phone number or email address, or say 'skip' if you don't want to share one."
        else:
            prompt = "I can send this to our front desk. What phone number or email should they use to reach you? If giving a phone number, please say the digits one at a time. You can say 'skip' if you don't want to share one."
        return {
            "handoff_required": False,
            "handoff_reason": reason,
            "awaiting_handoff_contact": True,
            "handoff_completed": False,
            "is_completed": False,
            "latest_agent_speech": prompt,
        }

    contact_available = bool(patient_phone or patient_email)

    if convo_id:
        try:
            repo = ConversationRepository(db)
            await repo.update_collected_details(
                uuid.UUID(convo_id),
                {
                    "patient_name": patient_name,
                    "patient_phone": patient_phone,
                    "patient_email": patient_email,
                    "identity_verified": identity_verified,
                    "callback_contact_unavailable": not contact_available,
                    "awaiting_handoff_contact": False,
                    "handoff_completed": True,
                    "handoff_reason": reason,
                },
            )
            await repo.close(
                conversation_id=uuid.UUID(convo_id),
                outcome=OutcomeType.HANDED_TO_FRONT_DESK,
                handoff_reason=reason,
            )

            email_sent = bool(state.get("frontdesk_alert_sent"))
            if not email_sent:
                notif_service = NotificationService(db)
                email_sent = await notif_service.send_frontdesk_alert_email(
                    reason=reason,
                    call_details={
                        "call_sid": call_sid,
                        "conversation_id": convo_id,
                        "channel": channel,
                        "patient_phone": patient_phone,
                        "patient_email": patient_email,
                        "patient_name": patient_name,
                        "patient_id": state.get("patient_id") if identity_verified else None,
                        "identity_verified": identity_verified,
                    },
                )
            await repo.update_collected_details(
                uuid.UUID(convo_id), {"frontdesk_alert_sent": email_sent}
            )
        except Exception as e:
            logger.error(f"Error executing handoff DB operations: {e}")
            email_sent = False
    else:
        email_sent = False

    if web_channel:
        front_desk_phone = (settings.FRONT_DESK_PHONE or "").strip()
        if email_sent and contact_available:
            speech = "I've notified our front desk team. They can follow up using the contact details you provided."
        elif email_sent:
            speech = "I've notified our front desk team, but I don't have a callback method for you."
        elif front_desk_phone:
            speech = (
                "Your request is recorded, but I couldn't notify the front desk directly. You can reach them at "
                f"{front_desk_phone}."
            )
        else:
            speech = "Your request is saved, but I couldn't confirm that the front desk was notified. Please contact the clinic directly."
    else:
        front_desk_phone = (settings.FRONT_DESK_PHONE or "").strip()
        can_transfer = front_desk_phone and not front_desk_phone.startswith("+91xxxx")
        if can_transfer:
            speech = "Please hold while I transfer you to our front desk team."
        elif email_sent:
            speech = "I couldn't connect a live transfer, but I've notified our front desk team and recorded your callback number."
        else:
            speech = "I couldn't connect a live transfer. Your call number is recorded for the front desk, but I couldn't confirm a staff notification."

    return {
        "handoff_required": True,
        "awaiting_handoff_contact": False,
        "handoff_completed": True,
        "frontdesk_alert_sent": bool(email_sent),
        # Return the contact extracted on this turn as graph state too. The
        # turn service persists final graph state after this node; omitting
        # these values allowed stale empty details to overwrite the callback
        # contact written above.
        "patient_name": patient_name,
        "patient_phone": patient_phone or "",
        "patient_email": patient_email,
        "is_completed": True,
        "latest_agent_speech": speech,
    }
