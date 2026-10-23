"""Voice routes ??? Twilio telecom-grade outbound flow with Sarvam AI voice and LangGraph agent.
Clean, non-duplicated architecture matching test reference project.
"""
import logging
import asyncio
import time
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

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
from src.services.audio_storage_service import audio_storage_service
from src.observability.context import call_id_context

logger = logging.getLogger(__name__)

sarvam_service = SarvamService()


async def _run_outbound_turn_in_isolated_session(*, call_sid: str, patient_text: str):
    """Keep a timed-out Twilio turn from committing partial DB work."""
    async with AsyncSessionLocal() as turn_session:
        try:
            return await conversation_turn_service.run_outbound_turn(
                turn_session,
                call_sid=call_sid,
                patient_text=patient_text,
            )
        except BaseException:
            await turn_session.rollback()
            raise


async def _persist_outbound_timeout_reply(call_sid: str, reply: str) -> None:
    """Persist a timeout reply after the cancelled action session is gone."""
    async with AsyncSessionLocal() as session:
        call = await OutboundCallRepository(session).get_by_provider_call_id(call_sid)
        if not call:
            return
        await conversation_turn_service.save_message(
            session,
            call.conversation_id,
            role="agent",
            content=reply,
            metadata={"event_type": "timeout", "stage": "agent_turn"},
        )
twilio_service = TwilioService()

# ?????? 1. In-Memory 8kHz WAV Cache & Call Metadata Store ???????????????????????????????????????????????????????????????????????????
def _get_clean_domain() -> str:
    configured = (settings.PUBLIC_DOMAIN or settings.NGROK_URL or "").strip()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Public voice webhook domain is not configured.",
        )
    parsed = urlsplit(configured if "://" in configured else f"https://{configured}")
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(
            status_code=503,
            detail="Public voice webhook domain must be a reachable HTTPS host without a path.",
        )
    return parsed.netloc


async def _create_sarvam_audio_url(text: str, language_code: str = "en-IN") -> Optional[str]:
    """Generate a short-lived public WAV URL for Twilio <Play> using Sarvam Bulbul TTS (8kHz)."""
    if not settings.SARVAM_TTS_ENABLED or not text or not text.strip():
        return None

    try:
        audio = await asyncio.wait_for(
            sarvam_service.text_to_speech(text.strip(), target_language_code=language_code),
            timeout=settings.OUTBOUND_TTS_TIMEOUT_SECONDS,
        )
        if not audio:
            logger.warning("Sarvam TTS returned empty audio; will use Twilio Polly fallback.")
            return None

        audio_id = await audio_storage_service.store(audio)
        clean_domain = _get_clean_domain()
        return f"https://{clean_domain}/twilio/audio/{audio_id}"
    except Exception as exc:
        logger.error(f"Sarvam TTS audio generation error: {exc}")
        return None


def _speech_xml(text: str, audio_url: Optional[str]) -> str:
    """Format speech XML: prefers Sarvam audio URL, falls back to high quality Polly voice."""
    if audio_url:
        return f"<Play>{escape(audio_url)}</Play>"
    # Polly has no male en-IN voice; Brian is a supported male English voice.
    return f'<Say voice="Polly.Brian" language="en-GB">{escape(text)}</Say>'


def _twilio_webhook_url(request: Request, host: str, scheme: str = "https") -> str:
    """Build the externally visible URL used by Twilio when signing a webhook."""
    query = request.url.query
    return urlunsplit((scheme, host, request.url.path, query, ""))


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
    configured_url = _twilio_webhook_url(request, _get_clean_domain())
    candidate_urls = [configured_url]

    # Reverse proxies and tunnels can preserve the public host in forwarded
    # headers while Uvicorn sees an internal host/scheme. Try those exact
    # externally supplied URL forms too; the Twilio signature remains the
    # authentication check for every candidate.
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    request_host = request.headers.get("host", "").split(",", 1)[0].strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "https").split(",", 1)[0].strip().lower()
    for host in (forwarded_host, request_host):
        if host:
            for scheme in dict.fromkeys((forwarded_proto if forwarded_proto in ("http", "https") else "https", "https")):
                candidate = _twilio_webhook_url(request, host, scheme)
                if candidate not in candidate_urls:
                    candidate_urls.append(candidate)

    valid = bool(signature) and any(
        validator.validate(candidate_url, form_data, signature)
        for candidate_url in candidate_urls
    )
    call_control_path = request.url.path in {"/twilio/voice", "/twilio/agent-turn"}
    if not signature and call_control_path:
        # Some call-control requests arrive unsigned. The route performs a
        # second, provider-backed check against our own call record.
        request.state.provider_verified_voice_webhook = True
        return
    if not valid:
        if call_control_path:
            # A valid Twilio call can still fail URL-signature validation when
            # a tunnel/proxy rewrites the public URL. Keep the webhook behind
            # the authenticated Twilio API verification below instead of
            # dropping the entire call transcript or accepting it blindly.
            logger.warning(
                "Twilio call-control signature mismatch; attempting provider verification: path=%s configured_host=%s request_host=%s forwarded_host=%s",
                request.url.path,
                _get_clean_domain(),
                request_host or "<missing>",
                forwarded_host or "<missing>",
            )
            request.state.provider_verified_voice_webhook = True
            return
        logger.warning(
            "Rejected Twilio webhook signature: path=%s signature_present=%s configured_host=%s request_host=%s forwarded_host=%s content_type=%s parameter_keys=%s",
            request.url.path,
            bool(signature),
            _get_clean_domain(),
            request_host or "<missing>",
            forwarded_host or "<missing>",
            request.headers.get("content-type", "<missing>"),
            sorted(form_data.keys()),
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio webhook signature.")


async def _verify_unsigned_voice_call(request: Request, form_data: dict) -> None:
    """Allow call-control only when signed correctly or verified by Twilio's API."""
    call_sid = form_data.get("CallSid") or request.query_params.get("call_sid")
    account_sid = form_data.get("AccountSid")
    if isinstance(call_sid, list):
        call_sid = call_sid[-1]
    if isinstance(account_sid, list):
        account_sid = account_sid[-1]
    if not call_sid or account_sid != settings.TWILIO_ACCOUNT_SID:
        raise HTTPException(status_code=403, detail="Unverified Twilio call.")

    call_record = None
    # Twilio may fetch the webhook before the REST call-creation response is
    # committed locally. Retry briefly so the valid call is not discarded.
    for attempt in range(10):
        async with AsyncSessionLocal() as session:
            call_record = await OutboundCallRepository(session).get_by_provider_call_id(str(call_sid))
        if call_record:
            break
        if attempt < 9:
            await asyncio.sleep(0.2)
    if not call_record:
        raise HTTPException(status_code=403, detail="Unknown outbound call.")

    try:
        provider_call = await asyncio.to_thread(
            lambda: twilio_service.client.calls(str(call_sid)).fetch()
        )
    except Exception as exc:
        logger.warning("Could not verify unsigned Twilio call %s: %s", call_sid, exc)
        raise HTTPException(status_code=503, detail="Could not verify call with Twilio.") from exc

    to_number = form_data.get("To")
    from_number = form_data.get("From")
    if isinstance(to_number, list):
        to_number = to_number[-1]
    if isinstance(from_number, list):
        from_number = from_number[-1]

    allowed_statuses = {"queued", "ringing", "in-progress"}
    provider_from = getattr(provider_call, "from_", None)
    if (
        provider_call.account_sid != settings.TWILIO_ACCOUNT_SID
        or provider_call.sid != str(call_sid)
        or provider_call.status not in allowed_statuses
        or not to_number
        or normalize_phone(str(to_number)) != normalize_phone(call_record.number_called)
        or (from_number and provider_from and normalize_phone(str(from_number)) != normalize_phone(provider_from))
    ):
        logger.warning("Unsigned Twilio webhook did not match an active clinic call: call_sid=%s", call_sid)
        raise HTTPException(status_code=403, detail="Unverified Twilio call.")

    logger.warning("Accepted call-control webhook after Twilio API verification: call_sid=%s path=%s", call_sid, request.url.path)


async def _read_twilio_form(request: Request) -> dict:
    """Read form parameters without silently turning parse errors into bad signatures."""
    try:
        parsed = await request.form()
    except Exception as exc:
        logger.exception("Could not parse Twilio webhook form data")
        raise HTTPException(status_code=400, detail="Invalid Twilio webhook form data.") from exc

    params: dict = {}
    for key, value in parsed.multi_items():
        if key not in params:
            params[key] = value
        elif isinstance(params[key], list):
            params[key].append(value)
        else:
            params[key] = [params[key], value]
    return params


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


# ?????? 2. Outbound Call Trigger Router (POST /api/calls/trigger) ??????????????????????????????????????????????????????
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
            expires_at=datetime.now(timezone.utc) + timedelta(
                minutes=max(
                    15,
                    settings.OUTBOUND_CALL_RETRY_DELAY_MINUTES
                    * max(1, settings.OUTBOUND_CALL_MAX_ATTEMPTS - 1)
                    + 10,
                )
            ),
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


# ?????? 3. Twilio Conversational Webhooks Router (/twilio/...) ????????????????????????????????????????????????????????????
twiml_router = APIRouter(prefix="/twilio", tags=["Twilio Voice Webhooks"])


@twiml_router.get("/audio/{audio_id}")
async def get_sarvam_audio(audio_id: str):
    """Serves Sarvam generated 8kHz WAV audio to Twilio telephone line."""
    audio = await audio_storage_service.get(audio_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio expired or not found.")

    return Response(
        content=audio,
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
    form_data = await _read_twilio_form(request)
    _validate_twilio_webhook(request, form_data)
    if getattr(request.state, "provider_verified_voice_webhook", False):
        await _verify_unsigned_voice_call(request, form_data)

    call_sid = (
        form_data.get("CallSid")
        or request.query_params.get("CallSid")
        or request.query_params.get("call_sid")
        or "CALL"
    )
    call_id_context.set(call_sid)
    call_record = None
    for attempt in range(10):
        async with AsyncSessionLocal() as session:
            outbound_repo = OutboundCallRepository(session)
            call_record = await outbound_repo.get_by_provider_call_id(call_sid)
        if call_record:
            break
        if attempt < 9:
            await asyncio.sleep(0.2)
    if not call_record:
        logger.error("Outbound call record was not available after retry: call_sid=%s", call_sid)
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
            await conversation_turn_service.save_message(
                session, call_record.conversation_id,
                role="agent", content=greeting_text,
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
    {_speech_xml(greeting_text, greeting_audio_url)}
    <Gather input="speech" language="en-IN" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="auto">
    </Gather>
    <Gather input="speech" language="en-IN" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="auto">
        <Pause length="1"/>
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
    form_data = await _read_twilio_form(request)
    _validate_twilio_webhook(request, form_data)
    if getattr(request.state, "provider_verified_voice_webhook", False):
        await _verify_unsigned_voice_call(request, form_data)

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
    <Gather input="speech" language="en-IN" speechModel="experimental_conversations" actionOnEmptyResult="false" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="auto">
        {_speech_xml("Take your time! I'm right here on the line whenever you're ready.", None)}
    </Gather>
    <Gather input="speech" language="en-IN" speechModel="experimental_conversations" actionOnEmptyResult="true" action="{escape(gather_url)}" method="POST" timeout="8" speechTimeout="auto">
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
    logger.info(
        "Patient utterance received: call_sid=%s length=%d confidence=%s",
        call_sid,
        len(user_utterance),
        confidence,
    )

    # 2. Run the shared agent-turn service used by all voice transports.
    turn_started_at = time.perf_counter()
    try:
        turn = await asyncio.wait_for(
            _run_outbound_turn_in_isolated_session(
                call_sid=call_sid,
                patient_text=user_utterance,
            ),
            timeout=settings.OUTBOUND_CALL_TURN_TIMEOUT_SECONDS,
        )
        agent_speech = turn.speech
        is_completed = turn.completed
        handoff_required = turn.handoff_required
    except LookupError as e:
        logger.error("Unable to load outbound conversation for %s: %s", call_sid, e)
        raise HTTPException(status_code=404, detail=str(e)) from e
    except asyncio.TimeoutError:
        logger.warning("Outbound turn timed out: call_sid=%s", call_sid)
        agent_speech = "I am sorry, this is taking longer than expected. Let me connect you with our front desk."
        await _persist_outbound_timeout_reply(call_sid, agent_speech)
        is_completed = True
        handoff_required = True
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
    <Gather input="speech" language="en-IN" speechModel="experimental_conversations" actionOnEmptyResult="true" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="auto">
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
    {_speech_xml(agent_speech, reply_audio_url)}
    <Gather input="speech" language="en-IN" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="auto">
    </Gather>
    <Gather input="speech" language="en-IN" action="{escape(gather_url)}" method="POST" timeout="10" speechTimeout="auto">
        <Pause length="1"/>
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
    form_data = await _read_twilio_form(request)
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
                    will_retry = bool(
                        normalized_status in {"no-answer", "busy"}
                        and call_record.next_retry_at
                    )
                    next_state = ConversationState.RETRY_SCHEDULED if will_retry else {
                        "no-answer": ConversationState.NO_ANSWER,
                        "busy": ConversationState.BUSY,
                        "failed": ConversationState.FAILED,
                        "canceled": ConversationState.ABANDONED,
                    }[normalized_status]
                    convo = await session.get(Conversation, call_record.conversation_id)
                    if convo and convo.ended_at is None:
                        history = list(convo.state_history or [])
                        history.append({"state": next_state.value, "at": datetime.now(timezone.utc).isoformat()})
                        update_values = {"current_state": next_state, "state_history": history}
                        if not will_retry:
                            update_values.update(
                                ended_at=datetime.now(timezone.utc),
                                outcome=(
                                    OutcomeType.NOT_REACHED
                                    if normalized_status in {"no-answer", "busy"}
                                    else OutcomeType.FAILED
                                ),
                            )
                        await session.execute(
                            update(Conversation)
                            .where(Conversation.id == call_record.conversation_id)
                            .values(**update_values)
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

