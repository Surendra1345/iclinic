"""Voice routes — Twilio telecom-grade outbound flow with Sarvam AI voice and LangGraph agent.
Clean, non-duplicated architecture matching test reference project.
"""
import logging
import asyncio
import time
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import update
from twilio.request_validator import RequestValidator

from src.config.settings import settings
from src.constants.enums import (
    CallStatus,
    ChannelType,
    ConversationState,
    OutboundCallRequestStatus,
    OutcomeType,
)
from src.data.clients.postgres import AsyncSessionLocal
from src.data.models.postgres.conversation import Conversation
from src.data.models.postgres.outbound_call_request import OutboundCallRequest
from src.data.repositories.conversation_repository import ConversationRepository
from src.data.repositories.outbound_call_repository import OutboundCallRepository
from src.data.repositories.patient_repository import PatientRepository
from src.services.sarvam_service import SarvamService
from src.services.conversation_turn_service import conversation_turn_service
from src.services.twilio_service import TwilioService
from src.observability.context import call_id_context

logger = logging.getLogger(__name__)

sarvam_service = SarvamService()
twilio_service = TwilioService()

# ── 1. In-Memory 8kHz WAV Cache & Call Metadata Store ─────────────────────────
_audio_cache: dict[str, tuple[bytes, float]] = {}
_AUDIO_TTL_SECONDS = 15 * 60  # 15 minutes TTL


def _get_clean_domain() -> str:
    domain = settings.PUBLIC_DOMAIN or settings.NGROK_URL or "foam-jury-quality.ngrok-free.dev"
    domain = domain.replace("https://", "").replace("http://", "").replace("wss://", "").replace("ws://", "").rstrip("/")
    return domain


async def _create_sarvam_audio_url(text: str, language_code: str = "en-IN") -> Optional[str]:
    """Generate a short-lived public WAV URL for Twilio <Play> using Sarvam Bulbul TTS (8kHz)."""
    if not settings.SARVAM_TTS_ENABLED or not text or not text.strip():
        return None

    try:
        audio = await sarvam_service.text_to_speech(text.strip(), target_language_code=language_code)
        if not audio:
            logger.warning("Sarvam TTS returned empty audio; will use Twilio Polly fallback.")
            return None

        audio_id = uuid4().hex
        _audio_cache[audio_id] = (audio, time.time() + _AUDIO_TTL_SECONDS)
        clean_domain = _get_clean_domain()
        return f"https://{clean_domain}/twilio/audio/{audio_id}"
    except Exception as exc:
        logger.error(f"Sarvam TTS audio generation error: {exc}")
        return None


def _speech_xml(text: str, audio_url: Optional[str]) -> str:
    """Format speech XML: prefers Sarvam audio URL, falls back to high quality Polly voice."""
    if audio_url:
        return f"<Play>{escape(audio_url)}</Play>"
    return f'<Say voice="Polly.Aditi" language="en-IN">{escape(text)}</Say>'


def _validate_twilio_webhook(request: Request, form_data: dict) -> None:
    """Reject forged Twilio callbacks when credentials are configured."""
    auth_token = settings.TWILIO_AUTH_TOKEN
    if not auth_token:
        if settings.APP_ENV.lower() == "production":
            raise HTTPException(status_code=503, detail="Twilio webhook validation is not configured.")
        logger.warning("TWILIO_AUTH_TOKEN is not configured; accepting webhook in non-production.")
        return

    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(auth_token)
    public_url = f"https://{_get_clean_domain()}{request.url.path}"
    if request.url.query:
        public_url = f"{public_url}?{request.url.query}"
    if not signature or not validator.validate(public_url, dict(form_data), signature):
        logger.warning(
            "Rejected Twilio webhook signature for path=%s; expected public URL=%s",
            request.url.path,
            public_url,
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio webhook signature.")


def normalize_phone(phone: Optional[str]) -> str:
    """Normalize phone input into standard E.164 format (+91XXXXXXXXXX or +1XXXXXXXXXX)."""
    import re
    if not phone:
        return ""
    cleaned = re.sub(r"[^\d+]", "", str(phone).strip())
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned
    if len(cleaned) == 10 and cleaned[0] in "6789":
        return f"+91{cleaned}"
    if len(cleaned) == 11 and cleaned.startswith("0") and cleaned[1] in "6789":
        return f"+91{cleaned[1:]}"
    if len(cleaned) == 12 and cleaned.startswith("91"):
        return f"+{cleaned}"
    return f"+{cleaned}"


# ── 2. Outbound Call Trigger Router (POST /api/calls/trigger) ──────────────────
calls_router = APIRouter(prefix="/api", tags=["Outbound Calls"])


class TriggerCallRequest(BaseModel):
    """Request body for starting an outbound patient call."""

    to_phone: str = Field(
        ...,
        description="Patient phone number. Use E.164 format, for example +919876543210.",
        examples=["+919876543210"],
    )


@calls_router.post("/calls/trigger")
async def trigger_outbound_call(payload: TriggerCallRequest):
    """
    SINGLE OUTBOUND CALL TRIGGER ENDPOINT.
    Dials patient phone number and connects the answered call to the AI agent.
    """
    clean_phone = normalize_phone(payload.to_phone)
    if not clean_phone:
        raise HTTPException(status_code=400, detail="A valid to_phone is required.")

    patient_id = None
    conversation_id = None
    call_request_id = None

    async with AsyncSessionLocal() as session:
        repo = PatientRepository(session)
        p = await repo.get_by_phone(clean_phone)
        if p:
            patient_id = str(p.id)
        outbound_repo = OutboundCallRepository(session)
        active_request = await outbound_repo.get_active_request(clean_phone)
        if active_request:
            active_call = await outbound_repo.get_by_request_id(active_request.id)
            provider_status = ""
            if active_call and active_call.provider_call_id:
                try:
                    provider_status = await asyncio.to_thread(
                        twilio_service.get_call_status,
                        active_call.provider_call_id,
                    )
                except Exception:
                    logger.exception(
                        "Unable to reconcile active Twilio call %s",
                        active_call.provider_call_id,
                    )

            terminal_statuses = {"completed", "canceled", "failed", "busy", "no-answer"}
            if active_call and provider_status in terminal_statuses:
                mapped_status = {
                    "completed": CallStatus.ANSWERED,
                    "canceled": CallStatus.FAILED,
                    "failed": CallStatus.FAILED,
                    "busy": CallStatus.BUSY,
                    "no-answer": CallStatus.NO_ANSWER,
                }[provider_status]
                await outbound_repo.update_status(
                    call_sid=active_call.provider_call_id,
                    call_status=mapped_status,
                    event_type=provider_status,
                )
                await session.commit()
                active_request = None

            if active_request:
                raise HTTPException(
                    status_code=409,
                    detail="An outbound call is already active for this phone number.",
                )

        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.create(
            channel=ChannelType.OUTBOUND_CALL,
            patient_id=p.id if p else None,
        )
        conversation_id = conversation.id
        call_request = await outbound_repo.create_request(
            conversation_id=conversation.id,
            phone=clean_phone,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        call_request_id = call_request.id
        await session.commit()

    clean_domain = _get_clean_domain()
    # Webhook Twilio fetches when patient answers
    webhook_url = f"https://{clean_domain}/twilio/voice"
    status_callback_url = f"https://{clean_domain}/twilio/call-status"

    try:
        call_sid = twilio_service.initiate_outbound_call(
            to_phone=clean_phone,
            webhook_url=webhook_url,
            status_callback_url=status_callback_url,
        )
        async with AsyncSessionLocal() as session:
            outbound_repo = OutboundCallRepository(session)
            await outbound_repo.create_call(
                request_id=call_request_id,
                conversation_id=conversation_id,
                provider_call_id=call_sid,
                phone=clean_phone,
            )
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    collected_details={
                        "call_sid": call_sid,
                        "patient_phone": clean_phone,
                    }
                )
            )
            await session.commit()
        return {
            "status": "success",
            "message": f"AI Outbound call initiated to {clean_phone}",
            "call_sid": call_sid,
            "to": clean_phone,
            "patient_id": patient_id,
            "conversation_id": str(conversation_id),
        }
    except Exception as e:
        logger.error(f"Failed to initiate outbound call to {clean_phone}: {e}")
        async with AsyncSessionLocal() as session:
            outbound_repo = OutboundCallRepository(session)
            await session.execute(
                update(OutboundCallRequest)
                .where(OutboundCallRequest.id == call_request_id)
                .values(
                    status=OutboundCallRequestStatus.FAILED,
                    status_reason=str(e),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        raise HTTPException(status_code=502, detail="Unable to initiate outbound call.")


# ── 3. Twilio Conversational Webhooks Router (/twilio/...) ────────────────────
twiml_router = APIRouter(prefix="/twilio", tags=["Twilio Voice Webhooks"])


@twiml_router.get("/audio/{audio_id}")
async def get_sarvam_audio(audio_id: str):
    """Serves Sarvam generated 8kHz WAV audio to Twilio telephone line."""
    now = time.time()
    for cached_id, (_, expires_at) in list(_audio_cache.items()):
        if expires_at <= now:
            _audio_cache.pop(cached_id, None)

    cached = _audio_cache.get(audio_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Audio expired or not found.")

    return Response(
        content=cached[0],
        media_type="audio/wav",
        headers={
            "Cache-Control": "public, max-age=600",
            "Content-Disposition": "inline; filename=speech.wav",
        },
    )


@twiml_router.post("/voice")
async def initial_call_webhook(request: Request):
    """
    Called when patient answers the outbound call.
    Instantly returns personalized greeting with Sarvam Bulbul 8kHz audio and opens Gather.
    """
    request_started_at = time.perf_counter()
    form_data = {}
    try:
        form_data = await request.form()
    except Exception:
        pass
    _validate_twilio_webhook(request, form_data)

    call_sid = (
        form_data.get("CallSid")
        or request.query_params.get("CallSid")
        or request.query_params.get("call_sid")
        or "CALL"
    )
    call_id_context.set(call_sid)
    async with AsyncSessionLocal() as session:
        outbound_repo = OutboundCallRepository(session)
        call_record = await outbound_repo.get_by_provider_call_id(call_sid)
        if not call_record:
            raise HTTPException(status_code=404, detail="Outbound call was not found.")
        to_phone = call_record.number_called

    greeting_text = (
        f"Hello! Thank you for answering. This is {settings.AGENT_NAME} calling from {settings.CLINIC_NAME}. "
        f"For your medical privacy and security, could you please confirm your full name and date of birth?"
    )

    persistence_started = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            convo_repo = ConversationRepository(session)
            await convo_repo.update_collected_details(
                call_record.conversation_id,
                {"call_sid": call_sid, "patient_phone": to_phone},
            )
            await convo_repo.append_message(
                call_record.conversation_id,
                role="agent",
                content=greeting_text,
            )
        logger.info(
            "Persisted initial greeting for call_sid=%s conversation_id=%s in %.3fs",
            call_sid,
            call_record.conversation_id,
            time.perf_counter() - persistence_started,
        )
    except Exception as exc:
        logger.exception(
            "Failed to persist initial greeting for call_sid=%s conversation_id=%s",
            call_sid,
            call_record.conversation_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to persist the outbound conversation greeting.",
        ) from exc

    logger.info(f"Generating outbound greeting for {call_sid} ({to_phone}): '{greeting_text}'")
    greeting_audio_url = await _create_sarvam_audio_url(greeting_text)

    clean_domain = _get_clean_domain()
    gather_url = f"https://{clean_domain}/twilio/agent-turn?call_sid={call_sid}"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="1">
        {_speech_xml(greeting_text, greeting_audio_url)}
    </Gather>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="12" speechTimeout="1">
        <Pause length="2"/>
        {_speech_xml("Take your time, I'm right here whenever you're ready.", None)}
    </Gather>
    {_speech_xml(f"We didn't hear a response. Please call {settings.CLINIC_NAME} whenever you are available. Goodbye!", None)}
    <Hangup />
</Response>
"""
    logger.info(
        "Outbound initial TwiML response for %s completed in %.3fs",
        call_sid,
        time.perf_counter() - request_started_at,
    )
    return Response(content=twiml, media_type="application/xml")


@twiml_router.post("/agent-turn")
async def handle_agent_turn(request: Request):
    """
    Handles transcribed patient speech from Twilio:
    - Runs LangGraph agent with PostgreSQL database session
    - Synthesizes reply with Sarvam Bulbul AI (8kHz)
    - Returns next Gather or concludes call cleanly.
    """
    request_started_at = time.perf_counter()
    form_data = {}
    try:
        form_data = await request.form()
    except Exception:
        pass
    _validate_twilio_webhook(request, form_data)

    call_sid = (
        form_data.get("CallSid")
        or request.query_params.get("call_sid")
        or "CALL"
    )
    call_id_context.set(call_sid)
    speech_result = form_data.get("SpeechResult") or request.query_params.get("SpeechResult")
    confidence = form_data.get("Confidence") or request.query_params.get("Confidence")

    clean_domain = _get_clean_domain()
    gather_url = f"https://{clean_domain}/twilio/agent-turn?call_sid={call_sid}"

    # 1. Handle Silence / No Speech without abruptly cutting the call
    if not speech_result or not str(speech_result).strip():
        logger.info(f"Silence detected on {call_sid}. Prompting patient to take their time.")
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Pause length="1"/>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="1">
        {_speech_xml("Take your time! I'm right here on the line whenever you're ready.", None)}
    </Gather>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="8" speechTimeout="1">
        <Pause length="2"/>
    </Gather>
    {_speech_xml(f"I couldn't hear your response. Please call {settings.CLINIC_NAME} back anytime. Goodbye!", None)}
    <Hangup />
</Response>
"""
        logger.info(
            "Outbound silence response for %s completed in %.3fs",
            call_sid,
            time.perf_counter() - request_started_at,
        )
        return Response(content=twiml, media_type="application/xml")

    user_utterance = str(speech_result).strip()
    logger.info(f"Patient ({call_sid}) said: '{user_utterance}' (confidence: {confidence})")

    # 2. Run the shared agent-turn service used by all voice transports.
    turn_started_at = time.perf_counter()
    async with AsyncSessionLocal() as session:
        try:
            turn = await conversation_turn_service.run_outbound_turn(
                session,
                call_sid=call_sid,
                patient_text=user_utterance,
            )
            agent_speech = turn.speech
            is_completed = turn.completed
            handoff_required = turn.handoff_required

        except LookupError as e:
            logger.error("Unable to load outbound conversation for %s: %s", call_sid, e)
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Outbound turn execution error: {e}")
            agent_speech = "I apologize, let me connect you with our front desk receptionist."
            is_completed = True
            handoff_required = True

    logger.info(f"Agent replied for {call_sid}: '{agent_speech}' (completed: {is_completed}, handoff: {handoff_required})")
    logger.info(
        "Outbound turn for %s completed in %.3fs",
        call_sid,
        time.perf_counter() - turn_started_at,
    )

    # 3. Synthesize reply audio via Sarvam AI Bulbul (8000Hz)
    tts_started_at = time.perf_counter()
    reply_audio_url = await _create_sarvam_audio_url(agent_speech)
    logger.info(
        "Outbound response audio for %s completed in %.3fs (sarvam_enabled=%s)",
        call_sid,
        time.perf_counter() - tts_started_at,
        settings.SARVAM_TTS_ENABLED,
    )

    # 4. Return appropriate TwiML
    if handoff_required:
        front_desk_phone = getattr(settings, "FRONT_DESK_PHONE", "")
        if front_desk_phone and not front_desk_phone.startswith("+91xxxx"):
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {_speech_xml(agent_speech, reply_audio_url)}
    <Dial>{escape(front_desk_phone)}</Dial>
</Response>
"""
        else:
            # If no live transfer line configured, open Gather so patient is not abruptly dropped
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="1">
        {_speech_xml(agent_speech, reply_audio_url)}
    </Gather>
    {_speech_xml(f"Thank you for contacting {settings.CLINIC_NAME}. Goodbye!", None)}
    <Hangup />
</Response>
"""
    elif is_completed:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {_speech_xml(agent_speech, reply_audio_url)}
    <Hangup />
</Response>
"""
    else:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="1">
        {_speech_xml(agent_speech, reply_audio_url)}
    </Gather>
    <Gather input="speech" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="1">
        <Pause length="2"/>
        {_speech_xml("Take your time, let me know when you're ready.", None)}
    </Gather>
    {_speech_xml(f"Thank you for speaking with {settings.CLINIC_NAME}. Have a wonderful day, goodbye!", None)}
    <Hangup />
</Response>
"""

    logger.info(
        "Outbound TwiML response for %s completed in %.3fs",
        call_sid,
        time.perf_counter() - request_started_at,
    )
    return Response(content=twiml, media_type="application/xml")


@twiml_router.post("/call-status")
async def call_status_callback(request: Request):
    """Twilio call status callback (initiated, ringing, in-progress, completed, failed)."""
    form_data = {}
    try:
        form_data = await request.form()
    except Exception:
        pass
    _validate_twilio_webhook(request, form_data)

    call_sid = form_data.get("CallSid") or request.query_params.get("CallSid")
    call_status = form_data.get("CallStatus") or request.query_params.get("CallStatus")
    duration = form_data.get("CallDuration") or request.query_params.get("CallDuration")

    status_map = {
        "queued": CallStatus.DIALING,
        "initiated": CallStatus.DIALING,
        "ringing": CallStatus.DIALING,
        "in-progress": CallStatus.ANSWERED,
        "answered": CallStatus.ANSWERED,
        "completed": CallStatus.ANSWERED,
        "no-answer": CallStatus.NO_ANSWER,
        "busy": CallStatus.BUSY,
        "failed": CallStatus.FAILED,
        "canceled": CallStatus.FAILED,
    }
    normalized_status = str(call_status or "").lower()
    mapped_status = status_map.get(normalized_status)
    if call_sid and mapped_status:
        try:
            async with AsyncSessionLocal() as session:
                outbound_repo = OutboundCallRepository(session)
                call_record = await outbound_repo.update_status(
                    call_sid=call_sid,
                    call_status=mapped_status,
                    event_type=normalized_status,
                    event_id=form_data.get("SequenceNumber"),
                    duration_seconds=int(duration) if duration else None,
                    provider_response={
                        "call_status": normalized_status,
                        "from": form_data.get("From"),
                        "to": form_data.get("To"),
                    },
                )
                if call_record and normalized_status in {"no-answer", "busy", "failed", "canceled"}:
                    terminal_state = {
                        "no-answer": ConversationState.NO_ANSWER,
                        "busy": ConversationState.BUSY,
                        "failed": ConversationState.FAILED,
                        "canceled": ConversationState.ABANDONED,
                    }[normalized_status]
                    terminal_outcome = (
                        OutcomeType.NOT_REACHED
                        if normalized_status in {"no-answer", "busy"}
                        else OutcomeType.FAILED
                    )
                    await session.execute(
                        update(Conversation)
                        .where(
                            Conversation.id == call_record.conversation_id,
                            Conversation.ended_at.is_(None),
                        )
                        .values(
                            ended_at=datetime.now(timezone.utc),
                            current_state=terminal_state,
                            outcome=terminal_outcome,
                        )
                    )
                await session.commit()
        except (TypeError, ValueError):
            logger.warning("Invalid Twilio call duration for %s: %s", call_sid, duration)
        except Exception:
            logger.exception("Failed to persist Twilio status for %s", call_sid)

    logger.info(f"Twilio call status callback: {call_sid} -> {call_status} (duration: {duration}s)")
    return {"status": "ok", "call_sid": call_sid, "call_status": call_status}


# Alias for backwards compatibility
router = twiml_router
