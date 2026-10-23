"""Dashboard and web chat routes for Frontdesk operations and Patient Portal."""
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# pyrefly: ignore[missing-import]
from fastapi import APIRouter, Query
# pyrefly: ignore[missing-import]
from pydantic import BaseModel
# pyrefly: ignore[missing-import]
from sqlalchemy import func, select, update
# pyrefly: ignore[missing-import]
from sqlalchemy.orm import selectinload

from src.config.settings import settings
from src.constants.enums import AppointmentStatus, ChannelType, ConversationState, OutcomeType, SlotStatus
from src.control.agents.tools.registration_tools import is_greeting, is_name_only_candidate
from src.data.clients.postgres import AsyncSessionLocal
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.conversation import Conversation
from src.data.models.postgres.location import Location
from src.data.models.postgres.patient import Patient
from src.data.models.postgres.provider import Provider
from src.data.models.postgres.slot import Slot
from src.data.repositories.appointment_repository import AppointmentRepository
from src.data.repositories.conversation_repository import ConversationRepository
from src.data.repositories.slot_repository import SlotRepository

from src.services.sarvam_service import SarvamService
from src.services.conversation_turn_service import conversation_turn_service

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/api", tags=["Dashboard & Patient Chat"])
sarvam_service = SarvamService()


def _is_name_only_message(message: str) -> bool:
    """Identify a bare name so an unverified chat never enters booking logic."""
    return is_name_only_candidate(message)


# ?????? Schemas ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????

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


# ?????? Frontdesk Endpoints ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????

@dashboard_router.get("/dashboard/stats")
async def get_dashboard_stats():
    """Returns high-level KPI metrics for the frontdesk dashboard."""
    async with AsyncSessionLocal() as session:
        # Total counts by status
        booked_count = await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.status == AppointmentStatus.BOOKED)
        ) or 0
        cancelled_count = await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.status == AppointmentStatus.CANCELLED)
        ) or 0
        rescheduled_count = await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.status == AppointmentStatus.RESCHEDULED)
        ) or 0
        total_patients = await session.scalar(select(func.count(Patient.id))) or 0
        total_locations = await session.scalar(select(func.count(Location.id))) or 0
        total_providers = await session.scalar(select(func.count(Provider.id))) or 0
        forwarded_count = await session.scalar(
            select(func.count(Conversation.id)).where(
                (Conversation.current_state == ConversationState.HANDED_TO_FRONT_DESK)
                | (Conversation.outcome == OutcomeType.HANDED_TO_FRONT_DESK)
                | (Conversation.handoff_reason.isnot(None))
                | (Conversation.collected_details["handoff_reason"].astext.isnot(None))
            )
        ) or 0

        return {
            "booked_count": booked_count,
            "cancelled_count": cancelled_count,
            "rescheduled_count": rescheduled_count,
            "total_appointments": booked_count + cancelled_count + rescheduled_count,
            "total_patients": total_patients,
            "total_locations": total_locations,
            "total_providers": total_providers,
            "forwarded_count": forwarded_count,
        }


@dashboard_router.get("/dashboard/appointments")
async def list_appointments(
    status: Optional[str] = Query(None, description="Filter by status: booked, cancelled, rescheduled, or all"),
    location: Optional[str] = Query(None, description="Filter by branch location name"),
    search: Optional[str] = Query(None, description="Search by patient name, phone, or doctor name"),
):
    """Returns clinical appointment records with full patient, provider, and branch location details."""
    async with AsyncSessionLocal() as session:
        query = (
            select(Appointment)
            .options(
                selectinload(Appointment.patient),
                selectinload(Appointment.slot)
                .selectinload(Slot.provider)
                .selectinload(Provider.location),
            )
            .order_by(Appointment.created_at.desc())
        )

        if status and status.lower() != "all":
            try:
                status_enum = AppointmentStatus(status.lower())
                query = query.where(Appointment.status == status_enum)
            except ValueError:
                pass

        results = (await session.scalars(query)).all()

        appts = []
        for a in results:
            patient = a.patient
            slot = a.slot
            provider = slot.provider if slot else None
            loc = provider.location if provider else None

            p_name = patient.full_name if patient else "Unknown Patient"
            p_phone = patient.phone if patient else "-"
            doc_name = provider.full_name if provider else "General Doctor"
            spec = provider.specialty if provider else "General"
            loc_name = loc.name if loc else "City Care Clinic"
            loc_addr = loc.address if loc else ""

            # In-memory filter for location if specified
            if location and location.lower() != "all":
                if location.lower() not in loc_name.lower():
                    continue

            # In-memory search filter
            if search:
                s_lower = search.lower()
                matches = (
                    s_lower in p_name.lower()
                    or s_lower in p_phone.lower()
                    or s_lower in doc_name.lower()
                    or s_lower in spec.lower()
                )
                if not matches:
                    continue

            appts.append({
                "id": str(a.id),
                "patient_name": p_name,
                "patient_phone": p_phone,
                "doctor_name": doc_name,
                "specialty": spec,
                "location_name": loc_name,
                "location_address": loc_addr,
                "start_time": slot.start_time.isoformat() if slot else "",
                "end_time": slot.end_time.isoformat() if slot else "",
                "status": a.status.value,
                "created_at": a.created_at.isoformat() if a.created_at else "",
            })

        return {"appointments": appts, "total": len(appts)}


@dashboard_router.get("/dashboard/patients")
async def list_registered_patients(
    search: Optional[str] = Query(None, description="Search by patient name, phone, or email"),
    limit: int = Query(100, ge=1, le=500),
):
    """Returns list of registered patients along with their active appointment status."""
    async with AsyncSessionLocal() as session:
        query = (
            select(Patient)
            .where(Patient.is_active == True)
            .order_by(Patient.created_at.desc())
        )
        if search and search.strip():
            s_term = f"%{search.strip().lower()}%"
            query = query.where(
                (Patient.full_name.ilike(s_term))
                | (Patient.phone.ilike(s_term))
                | (Patient.email.ilike(s_term))
            )
        query = query.limit(limit)
        patients = (await session.scalars(query)).all()

        results = []
        for p in patients:
            # Active appointment (either booked or rescheduled)
            appt_query = (
                select(Appointment)
                .options(
                    selectinload(Appointment.slot)
                    .selectinload(Slot.provider)
                    .selectinload(Provider.location)
                )
                .where(
                    Appointment.patient_id == p.id,
                    Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED]),
                )
                .order_by(Appointment.created_at.desc())
                .limit(1)
            )
            active_appt = (await session.scalars(appt_query)).first()

            total_appts = await session.scalar(
                select(func.count(Appointment.id)).where(Appointment.patient_id == p.id)
            ) or 0

            active_info = None
            if active_appt and active_appt.slot:
                slot = active_appt.slot
                prov = slot.provider
                loc = prov.location if prov else None
                active_info = {
                    "appointment_id": str(active_appt.id),
                    "doctor_name": prov.full_name if prov else "Doctor",
                    "specialty": prov.specialty if prov else "General",
                    "location_name": loc.name if loc else "City Care Clinic",
                    "start_time": slot.start_time.isoformat() if slot else "",
                    "status": active_appt.status.value,
                }

            results.append({
                "id": str(p.id),
                "full_name": p.full_name,
                "phone": p.phone or "",
                "email": p.email or "",
                "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "total_appointments": total_appts,
                "active_appointment": active_info,
            })

        return {"patients": results, "total": len(results)}


@dashboard_router.get("/dashboard/locations")
async def list_clinic_locations():
    """Returns clinic branch locations along with active doctors and specialties."""
    async with AsyncSessionLocal() as session:
        locations = (await session.scalars(select(Location).order_by(Location.name))).all()
        providers = (await session.scalars(select(Provider).where(Provider.is_active == True))).all()

        data = []
        for loc in locations:
            loc_docs = [
                {
                    "id": str(p.id),
                    "full_name": p.full_name,
                    "specialty": p.specialty,
                }
                for p in providers
                if p.location_id == loc.id
            ]
            data.append({
                "id": str(loc.id),
                "name": loc.name,
                "address": loc.address,
                "doctors": loc_docs,
                "total_doctors": len(loc_docs),
            })
        return {"locations": data}


@dashboard_router.get("/dashboard/conversations")
async def list_conversations(
    channel: Optional[str] = Query(None, description="Filter by channel: chat, voice, outbound_call"),
    search: Optional[str] = Query(None, description="Search by patient name, phone, or sid"),
    limit: int = Query(50, ge=1, le=100),
):
    """Returns conversation interaction records with turn messages and patient metadata."""
    async with AsyncSessionLocal() as session:
        query = (
            select(Conversation)
            .options(selectinload(Conversation.patient))
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        if channel and channel.lower() != "all":
            try:
                ch_enum = ChannelType(channel.lower())
                query = query.where(Conversation.channel == ch_enum)
            except ValueError:
                pass

        convos = (await session.scalars(query)).all()
        results = []
        for c in convos:
            details = c.collected_details or {}
            p_name = details.get("patient_name") or details.get("registration_name") or (c.patient.full_name if c.patient else None)
            p_phone = details.get("patient_phone") or (c.patient.phone if c.patient else None)
            call_sid = details.get("call_sid") or str(c.id)

            if search:
                s_lower = search.lower().strip()
                matches = (
                    (p_name and s_lower in p_name.lower())
                    or (p_phone and s_lower in p_phone)
                    or (call_sid and s_lower in call_sid.lower())
                )
                if not matches:
                    continue

            results.append({
                "id": str(c.id),
                "call_sid": call_sid,
                "channel": c.channel.value if hasattr(c.channel, "value") else str(c.channel),
                "patient_name": p_name or "Anonymous / Guest",
                "patient_phone": p_phone or "-",
                "current_state": c.current_state.value if hasattr(c.current_state, "value") else str(c.current_state),
                "outcome": c.outcome.value if c.outcome and hasattr(c.outcome, "value") else (str(c.outcome) if c.outcome else None),
                "messages": c.messages or [],
                "total_messages": len(c.messages or []),
                "started_at": c.started_at.isoformat() if c.started_at else (c.created_at.isoformat() if c.created_at else None),
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "collected_details": details,
            })

        return {"conversations": results, "total": len(results)}


@dashboard_router.get("/dashboard/forwarded-requests")
async def list_forwarded_requests(
    status: Optional[str] = Query(None, description="Filter: pending, contacted, resolved, or all"),
    search: Optional[str] = Query(None, description="Search by patient name, phone, or doctor"),
    limit: int = Query(100, ge=1, le=200),
):
    """
    Returns patients whose conversations were forwarded/escalated to the front desk,
    along with their contact details, active appointments, escalation reason, and chat transcripts.
    """
    async with AsyncSessionLocal() as session:
        query = (
            select(Conversation)
            .options(selectinload(Conversation.patient))
            .where(
                (Conversation.current_state == ConversationState.HANDED_TO_FRONT_DESK)
                | (Conversation.outcome == OutcomeType.HANDED_TO_FRONT_DESK)
                | (Conversation.handoff_reason.isnot(None))
                | (Conversation.collected_details["handoff_reason"].astext.isnot(None))
            )
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
        )
        convos = (await session.scalars(query)).all()

        results = []
        pending_count = 0
        for c in convos:
            details = dict(c.collected_details or {})
            identity_verified = bool(c.identity_verified_at)
            p_name = (
                details.get("patient_name") or details.get("registration_name")
                or (c.patient.full_name if c.patient else "Unknown Patient")
            ) if identity_verified else "Unverified patient"
            p_phone = details.get("patient_phone") or (c.patient.phone if identity_verified and c.patient else "-")
            p_email = details.get("patient_email") or (c.patient.email if identity_verified and c.patient else None)
            p_dob = (
                details.get("patient_dob") or details.get("registration_dob")
                or (c.patient.date_of_birth.isoformat() if (c.patient and c.patient.date_of_birth) else None)
            ) if identity_verified else None
            p_id = (str(c.patient_id) if c.patient_id else details.get("patient_id")) if identity_verified else None

            # Determine escalation status
            escalation_status = details.get("escalation_status", "pending")
            if escalation_status == "pending":
                pending_count += 1

            if status and status.lower() != "all" and escalation_status.lower() != status.lower():
                continue

            # Active appointment resolution:
            active_info = details.get("active_appointment_details")
            if not active_info and p_id:
                try:
                    p_uuid = uuid.UUID(str(p_id))
                    appt_q = (
                        select(Appointment)
                        .options(
                            selectinload(Appointment.slot)
                            .selectinload(Slot.provider)
                            .selectinload(Provider.location)
                        )
                        .where(
                            Appointment.patient_id == p_uuid,
                            Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED]),
                        )
                        .order_by(Appointment.created_at.desc())
                        .limit(1)
                    )
                    appt = (await session.scalars(appt_q)).first()
                    if appt and appt.slot:
                        prov = appt.slot.provider
                        loc = prov.location if prov else None
                        active_info = {
                            "appointment_id": str(appt.id),
                            "doctor_name": prov.full_name if prov else "Assigned Doctor",
                            "specialty": prov.specialty if prov else "General Medicine",
                            "location_name": loc.name if loc else "City Care Clinic",
                            "location_address": loc.address if loc else "",
                            "start_time": appt.slot.start_time.isoformat(),
                            "status": appt.status.value,
                        }
                except Exception:
                    pass

            # Search filter
            if search:
                s_lower = search.lower().strip()
                doc_name = (active_info.get("doctor_name") if active_info else "").lower()
                reason_str = (c.handoff_reason or "").lower()
                matches = (
                    s_lower in p_name.lower()
                    or s_lower in p_phone.lower()
                    or s_lower in doc_name
                    or s_lower in reason_str
                )
                if not matches:
                    continue

            # Format human-friendly reason
            raw_reason = c.handoff_reason or details.get("handoff_reason") or "Patient requested front desk transfer"
            clean_reason = raw_reason
            if "sql" in raw_reason.lower() or "error" in raw_reason.lower() or "current transaction is aborted" in raw_reason.lower():
                clean_reason = "System error during scheduling â€” requires frontdesk resolution"
            elif "24-hour cutoff" in raw_reason.lower():
                clean_reason = "Policy: Reschedule / cancellation within 24-hour cutoff window"
            elif "already has an active appointment" in raw_reason.lower():
                clean_reason = "Policy: Multiple active appointments requested"
            elif "identity" in raw_reason.lower():
                clean_reason = "Security: Failed identity verification"

            forwarded_time = c.ended_at or c.updated_at or c.started_at or c.created_at

            results.append({
                "id": str(c.id),
                "call_sid": details.get("call_sid") or str(c.id),
                "channel": c.channel.value if hasattr(c.channel, "value") else str(c.channel),
                "patient_id": p_id,
                "patient_name": p_name,
                "patient_phone": p_phone,
                "patient_email": p_email,
                "patient_dob": p_dob,
                "identity_verified": identity_verified,
                "callback_contact_unavailable": bool(details.get("callback_contact_unavailable")),
                "awaiting_handoff_contact": bool(details.get("awaiting_handoff_contact")),
                "reason": clean_reason,
                "raw_reason": raw_reason,
                "status": escalation_status,
                "notes": details.get("escalation_notes"),
                "resolved_at": details.get("escalation_resolved_at"),
                "forwarded_at": forwarded_time.isoformat() if forwarded_time else None,
                "active_appointment": active_info,
                "messages": c.messages or [],
                "total_messages": len(c.messages or []),
            })

            if len(results) >= limit:
                break

        return {
            "forwarded_requests": results,
            "total": len(results),
            "pending_count": pending_count,
        }


@dashboard_router.patch("/dashboard/forwarded-requests/{conversation_id}")
async def update_forwarded_request_status(
    conversation_id: str,
    req: UpdateForwardedRequest,
):
    """Updates the status and notes of a forwarded patient request."""
    async with AsyncSessionLocal() as session:
        try:
            convo_uuid = uuid.UUID(conversation_id)
        except ValueError:
            return {"error": "Invalid conversation ID format"}

        convo = await session.get(Conversation, convo_uuid)
        if not convo:
            return {"error": "Conversation record not found"}

        details = dict(convo.collected_details or {})
        details["escalation_status"] = req.status
        if req.notes is not None:
            details["escalation_notes"] = req.notes
        if req.status in ("contacted", "resolved"):
            details["escalation_resolved_at"] = datetime.utcnow().isoformat()
        else:
            details.pop("escalation_resolved_at", None)

        convo.collected_details = details
        await session.commit()
        return {"status": "success", "escalation_status": req.status, "notes": details.get("escalation_notes")}


# ?????? Patient Web Chat Endpoint ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????

@dashboard_router.post("/chat")
async def chat_with_clinic_agent(req: ChatMessageRequest):
    """
    Direct web-chat assistant for patients to query doctors, symptoms,
    available slots, and clinic locations in real-time.
    """
    session_id = req.session_id or f"web_chat_{uuid.uuid4().hex[:12]}"
    if re.search(r"[\u0B80-\u0BFF\u0C00-\u0C7F]", req.message):
        reply = "I currently support English chat only. Please type your request in English or use the Voice Assistant for spoken Tamil or Telugu."
        async with AsyncSessionLocal() as session:
            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get_by_call_sid(session_id)
            if not conversation:
                conversation = await conversation_repo.create(
                    channel=ChannelType.CHAT,
                    call_sid=session_id,
                )
            await conversation_turn_service.save_message(
                session, conversation.id, role="agent", content=(
                    f"Hello! Welcome to {settings.CLINIC_NAME}. How can I help you today? "
                    "You can ask me to book, reschedule, cancel, or ask for available doctors and branches."
                ),
            )
            await conversation_turn_service.save_message(
                session, conversation.id, role="patient", content=req.message.strip()
            )
            await conversation_turn_service.save_message(
                session, conversation.id, role="agent", content=reply,
                metadata={"event_type": "unsupported_chat_language"},
            )
        return {
            "reply": reply,
            "session_id": session_id,
            "is_completed": False,
        }

    async with AsyncSessionLocal() as session:
        phone = (req.patient_phone or "").strip()
        name = (req.patient_name or "").strip()
        conversation_repo = ConversationRepository(session)
        existing_conversation = await conversation_repo.get_by_call_sid(session_id)
        if not existing_conversation:
            existing_conversation = await conversation_repo.create(
                channel=ChannelType.CHAT,
                call_sid=session_id,
            )

        saved_details = (
            dict(existing_conversation.collected_details or {})
            if existing_conversation
            else {}
        )
        linked_patient = (
            await session.get(Patient, existing_conversation.patient_id)
            if existing_conversation and existing_conversation.patient_id
            else None
        )
        patient_phone = phone or saved_details.get("patient_phone") or (
            linked_patient.phone if linked_patient else ""
        )
        patient_email = req.patient_email or saved_details.get("patient_email") or (
            linked_patient.email if linked_patient else None
        )
        patient_name = (
            name
            if name and not is_greeting(name)
            else (
                saved_details.get("patient_name")
                or saved_details.get("registration_name")
                if not is_greeting(saved_details.get("patient_name") or saved_details.get("registration_name", ""))
                else None
            )
        )
        patient_dob = saved_details.get("patient_dob") or saved_details.get("registration_dob")

        input_state = {
            "call_sid": session_id,
            "conversation_id": str(existing_conversation.id),
            "patient_phone": patient_phone,
            "patient_email": patient_email,
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "channel": "chat",
            "latest_user_speech": req.message.strip(),
            "messages": [
                *(existing_conversation.messages or []),
                {
                    "role": "patient",
                    "content": req.message.strip(),
                    "at": datetime.utcnow().isoformat(),
                },
            ],
            # A patient record linked by phone/contact details is not proof of identity.
            # Only the explicit name + DOB verification timestamp may open the gate.
            "is_verified": bool(existing_conversation.identity_verified_at),
            "is_new_patient": bool(saved_details.get("is_new_patient")),
            "awaiting_identity_verification": bool(saved_details.get("awaiting_identity_verification")),
            "pending_intent": saved_details.get("pending_intent"),
            "intent": saved_details.get("intent"),
        }
        last_agent_msg = next((m.get("content") for m in reversed(existing_conversation.messages or []) if m.get("role") == "agent"), "")
        input_state["latest_agent_speech"] = last_agent_msg
        for field in (
            "patient_id",
            "verify_attempts",
            "target_slot_id",
            "target_slot_details",
            "offered_slots",
            "active_appointment_id",
            "active_appointment_details",
            "preferred_specialty",
            "preferred_location",
            "preferred_doctor",
            "preferred_date",
            "preferred_appointment_type",
            "awaiting_followup_visit",
            "followup_candidates",
            "awaiting_followup_decision",
            "awaiting_preferred_date",
            "awaiting_patient_email",
            "awaiting_cancel_confirmation",
            "awaiting_change_action_choice",
            "awaiting_handoff_contact",
            "handoff_completed",
            "frontdesk_alert_sent",
            "handoff_reason",
            "handoff_required",
            "is_emergency",
        ):
            if field in saved_details:
                input_state[field] = saved_details[field]

        try:
            invoke_turn = None
            specialty_branch_reply = False
            if input_state.get("intent") == "faq_response" and input_state.get("preferred_specialty"):
                from src.control.agents.nodes.booking_helpers import _match_branch
                specialty_branch_reply = bool(_match_branch(req.message))

            if (
                not input_state["is_verified"]
                and _is_name_only_message(req.message)
                and not specialty_branch_reply
            ):
                # Preserve the privacy guard while routing persistence through the common turn service.
                from src.control.agents.nodes.identity import identity_agent_node

                async def invoke_turn(state):
                    result = await identity_agent_node({**state, "is_verified": False}, session)
                    result["intent"] = "identity"
                    return result

            turn = await conversation_turn_service.run_turn(
                session,
                conversation_id=existing_conversation.id,
                thread_id=session_id,
                channel="chat",
                patient_text=req.message.strip(),
                input_state=input_state,
                invoke=invoke_turn,
            )
            result = turn.state
            speech = turn.speech
            is_completed = result.get("is_completed", False)
            target_slot = result.get("target_slot_details")

            audio_url = None
            if req.generate_audio:
                try:
                    import time
                    from src.services.audio_storage_service import audio_storage_service
                    generated_audio = await sarvam_service.text_to_speech(speech, target_language_code="en-IN")
                    if generated_audio:
                        audio_id = await audio_storage_service.store(generated_audio)
                        audio_url = f"/api/voice-assistant/audio/{audio_id}"
                    else:
                        logger.warning("Chat TTS returned no audio: session_id=%s stage=tts", session_id)
                        await conversation_turn_service.annotate_last_agent_message(
                            session, existing_conversation.id,
                            {"audio_delivery": "text_only", "tts_error": "empty_audio"},
                        )
                except Exception as e:
                    logger.warning(f"Failed to generate TTS audio for chat response: {e}")
                    await conversation_turn_service.annotate_last_agent_message(
                        session, existing_conversation.id,
                        {"audio_delivery": "text_only", "tts_error": "provider_exception"},
                    )

            return {
                "reply": speech,
                "session_id": session_id,
                "is_completed": is_completed,
                "target_slot": target_slot,
                "booking_confirmed": result.get("booking_confirmed", False),
                "audio_url": audio_url,
            }
        except Exception:
            logger.exception("Web chat execution error")
            try:
                await conversation_turn_service.save_message(
                    session, existing_conversation.id, role="agent",
                    content="I apologize, our appointment assistant is currently updating. Please try again or contact the front desk.",
                    metadata={"event_type": "turn_error", "stage": "chat_route"},
                )
            except Exception:
                logger.exception("Could not persist the web chat error reply")
            return {
                "reply": "I apologize, our appointment assistant is currently updating. Please try calling or reaching our front desk.",
                "session_id": session_id,
                "is_completed": False,
                "audio_url": None,
            }
