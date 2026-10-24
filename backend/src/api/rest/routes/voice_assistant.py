"""Browser voice-assistant endpoints, separate from Twilio outbound calls."""
from src.constants.enums import ChannelType
import asyncio
import base64
import logging
import re
import time
from html import escape
from uuid import uuid4

from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from src.config.settings import settings
from src.control.agents.tools.registration_tools import is_greeting
from src.data.clients.postgres import AsyncSessionLocal
from src.data.repositories.conversation_repository import ConversationRepository
from src.handlers.http_clients.gemini_service import GeminiService
from src.handlers.http_clients.sarvam_service import SarvamService
from src.core.services.conversation_turn_service import conversation_turn_service
from src.utils.indic_lexicon import quick_english
from src.handlers.http_clients.audio_storage_service import audio_storage_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice-assistant", tags=["Browser Voice Assistant"])
from src.schemas.voice import TTSRequest
sarvam_service = SarvamService()
gemini_service = GeminiService()
_SUPPORTED_LANGUAGES = {"en-IN", "ta-IN", "te-IN"}

_VOICE_RETRY_MESSAGES = {
    "en-IN": "I could not hear that clearly. Please try speaking again.",
    "ta-IN": "உங்கள் குரலை தெளிவாகக் கேட்க முடியவில்லை. தயவுசெய்து மீண்டும் பேசவும்.",
    "te-IN": "మీ మాటలను స్పష్టంగా వినలేకపోయాను. దయచేసి మళ్లీ మాట్లాడండి.",
}
_VOICE_TRANSFER_MESSAGES = {
    "en-IN": "I'm sorry, I'm having trouble hearing you. If you like, say 'front desk' and I will connect you to our team, or try speaking again.",
    "ta-IN": "மன்னிக்கவும், உங்கள் குரலைக் கேட்பதில் சிரமம் இருக்கிறது. விரும்பினால் 'முன் மேசை' என்று சொல்லுங்கள், எங்கள் குழுவுடன் இணைக்கிறேன், அல்லது மீண்டும் பேசுங்கள்.",
    "te-IN": "క్షమించండి, మీ మాట వినడంలో ఇబ్బంది ఉంది. కావాలంటే 'ఫ్రంట్ డెస్క్' అని చెప్పండి, మా బృందానికి కనెక్ట్ చేస్తాను, లేదా మళ్లీ మాట్లాడండి.",
}
STT_FAILURES_BEFORE_TRANSFER_OFFER = 2
_VOICE_PROCESSING_MESSAGES = {
    "en-IN": "I am sorry, this is taking longer than expected. Please try again.",
    "ta-IN": "மன்னிக்கவும், இது எதிர்பார்த்ததை விட அதிக நேரம் எடுக்கிறது. தயவுசெய்து மீண்டும் முயற்சிக்கவும்.",
    "te-IN": "క్షమించండి, దీనికి ఊహించిన దానికంటే ఎక్కువ సమయం పడుతోంది. దయచేసి మళ్లీ ప్రయత్నించండి.",
}


def _normalize_language(language: str) -> str:
    language = (language or "").lower().replace("_", "-")
    if language.startswith("ta"):
        return "ta-IN"
    if language.startswith("te"):
        return "te-IN"
    return "en-IN"


async def _gemini_translate(prompt: str) -> str:
    """One translation call, retried once; a blip or a slow reply should not fail the whole turn."""
    last_error: Optional[BaseException] = None
    for attempt in range(settings.VOICE_ASSISTANT_TRANSLATION_ATTEMPTS):
        try:
            result = await asyncio.wait_for(
                gemini_service.generate_content(prompt, temperature=0.0),
                timeout=settings.VOICE_ASSISTANT_TRANSLATION_TIMEOUT_SECONDS,
            )
            if result and result.strip():
                return result.strip()
            last_error = ValueError("empty translation")
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 - any failure is retried then reported
            last_error = exc
            logger.warning("Translation attempt %d failed: %s", attempt + 1, exc)
    raise RuntimeError("translation unavailable") from last_error


_LANGUAGE_DETAILS = {
    "ta-IN": ("Tamil", "\u0ba4\u0bae\u0bbf\u0bb4\u0bcd", re.compile(r"[\u0B80-\u0BFF]")),
    "te-IN": ("Telugu", "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41", re.compile(r"[\u0C00-\u0C7F]")),
}


async def _translate(text: str, target_language: str) -> str:
    if not text or target_language == "en-IN":
        return text
    code = _normalize_language(target_language)
    name, native, script = _LANGUAGE_DETAILS[code]
    # Naming the language and its script matters: Chennai place names pull some models toward Tamil even when
    # Telugu was asked for, so the reply is also checked for the right script and asked again once if it is wrong.
    prompt = (
        f"Translate the following clinic assistant message into {name} ({native}, language code {code}). "
        f"Write the answer only in {name} script; the other Indian scripts are wrong. "
        "Preserve doctor names, branch names, dates, times, and appointment details. "
        "Return only the translation.\n\n"
        f"Message: {text}"
    )
    translated = await _gemini_translate(prompt)
    if not script.search(translated):
        logger.warning("Translation to %s came back in the wrong script; asking again", code)
        translated = await _gemini_translate(prompt)
        if not script.search(translated):
            raise RuntimeError("translation unavailable")
    return translated


async def _to_english(text: str, language: str) -> str:
    if not text or language == "en-IN":
        return text
    quick = quick_english(text)
    if quick:
        return quick
    prompt = (
        f"Translate the following patient message from {_normalize_language(language)} into English. "
        "Return only the translation and preserve names, dates, times, doctors, and locations.\n\n"
        f"Message: {text}"
    )
    return await _gemini_translate(prompt)


_INDIC_SCRIPT = re.compile(r"[\u0900-\u097F\u0B80-\u0BFF\u0C00-\u0C7F]")


async def _english_from_indic_script(text: str) -> str:
    """Speech recognition sometimes writes English names and phrases in an Indian script, even in an English
    session ("Dr. Rajesh Kannan" as Tamil letters). Turn that back into plain English for the agent."""
    prompt = (
        "The following patient message was transcribed in an Indian script but was spoken in an English "
        "conversation with a clinic. Write it in English: transliterate names and keep dates, times and doctor "
        "names. Return only the English text.\n\n"
        f"Message: {text}"
    )
    return await _gemini_translate(prompt)


async def _run_voice_turn_in_isolated_session(**kwargs):
    """Run a graph turn in a session that is rolled back on cancellation.

    The browser timeout must never reuse a cancelled action session to store a
    fallback response. That would risk committing a partially executed booking
    or reschedule operation.
    """
    async with AsyncSessionLocal() as turn_session:
        try:
            return await conversation_turn_service.run_turn(turn_session, **kwargs)
        except BaseException:
            await turn_session.rollback()
            raise


def _voice_retry_message(language: str) -> str:
    return _VOICE_RETRY_MESSAGES.get(_normalize_language(language), _VOICE_RETRY_MESSAGES["en-IN"])


def _voice_processing_message(language: str) -> str:
    return _VOICE_PROCESSING_MESSAGES.get(_normalize_language(language), _VOICE_PROCESSING_MESSAGES["en-IN"])


@router.post("/session")
async def create_voice_session():
    session_id = f"browser_voice_{uuid4().hex}"
    greeting = f"Hello! Welcome to {settings.CLINIC_NAME}. How can I help you today?"
    async with AsyncSessionLocal() as session:
        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.create(
            channel=ChannelType.VOICE,
            call_sid=session_id,
        )
        await conversation_turn_service.save_message(
            session, conversation.id, role="agent", content=greeting,
        )
    return {
        "session_id": session_id,
        "preferred_language": "en-IN",
        "language_confirmed": False,
        "greeting": greeting,
    }


@router.post("/turn")
async def process_voice_turn(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
):
    # Create the voice conversation before STT so an input that the provider
    # cannot transcribe is still visible in conversation history.
    async with AsyncSessionLocal() as session:
        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.get_by_call_sid(session_id)
        if not conversation:
            conversation = await conversation_repo.create(
                channel=ChannelType.VOICE,
                call_sid=session_id,
            )
            await conversation_turn_service.save_message(
                session, conversation.id, role="agent",
                content=f"Hello! Welcome to {settings.CLINIC_NAME}. How can I assist you today?",
            )
        saved_language = _normalize_language(
            (conversation.collected_details or {}).get("preferred_language", "")
        ) if conversation else "en-IN"
        stt_language = saved_language if saved_language in {"ta-IN", "te-IN"} else "unknown"

    audio_bytes = await audio.read()
    if not audio_bytes:
        async with AsyncSessionLocal() as session:
            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get_by_call_sid(session_id)
            if conversation:
                await conversation_turn_service.save_message(
                    session, conversation.id, role="patient", content="[Voice input was empty]",
                    metadata={"event_type": "voice_input_error", "stage": "stt"},
                )
                await conversation_turn_service.save_message(
                    session, conversation.id, role="agent",
                    content="I did not receive any audio. Please try speaking again.",
                    metadata={"event_type": "stt_error", "stage": "stt"},
                )
        return {
            "session_id": session_id, "transcript": "", "language": "en-IN",
            "language_confidence": 0.0,
            "reply": "I did not receive any audio. Please try speaking again.",
            "audio_url": None, "is_completed": False, "target_slot": None,
            "booking_confirmed": False,
        }

    stt_started = time.perf_counter()
    transcript, detected_language, confidence = await sarvam_service.speech_to_text(
        audio_bytes,
        filename=audio.filename or "voice.webm",
        language_code=stt_language,
        content_type=audio.content_type,
    )
    logger.info(
        "Voice assistant STT completed: session_id=%s language_hint=%s duration=%.3fs transcript=%s",
        session_id, stt_language, time.perf_counter() - stt_started, bool(transcript),
    )
    # Once the patient has used Tamil or Telugu in this session, keep that
    # language stable even if a later provider response omits or mislabels it.
    language = (
        stt_language
        if stt_language in {"ta-IN", "te-IN"}
        else _normalize_language(detected_language)
    )
    if language not in _SUPPORTED_LANGUAGES:
        language = "en-IN"
    elif confidence < settings.VOICE_ASSISTANT_LANGUAGE_CONFIDENCE_THRESHOLD:
        # Keep a supported detected language even when confidence is low; the
        # browser overlay must not silently turn Tamil/Telugu replies into English.
        logger.warning(
            "Low voice language confidence (%.2f) for %s; preserving detected language %s",
            confidence,
            session_id,
            language,
        )
    if not transcript:
        logger.warning("Voice assistant STT produced no transcript: session_id=%s error_stage=stt", session_id)
        failure_language = stt_language if stt_language in _SUPPORTED_LANGUAGES else language
        failure_reply = _voice_retry_message(failure_language)
        async with AsyncSessionLocal() as session:
            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get_by_call_sid(session_id)
            if conversation:
                # Ask again first; after repeated failures offer the front desk instead of looping.
                failures = int((conversation.collected_details or {}).get("stt_failures", 0)) + 1
                await conversation_repo.update_collected_details(conversation.id, {"stt_failures": failures})
                if failures >= STT_FAILURES_BEFORE_TRANSFER_OFFER:
                    failure_reply = _VOICE_TRANSFER_MESSAGES.get(failure_language, _VOICE_TRANSFER_MESSAGES["en-IN"])
                await conversation_turn_service.save_message(
                    session, conversation.id, role="patient",
                    content="[Voice input could not be transcribed]",
                    metadata={"event_type": "stt_error", "stage": "stt", "language": failure_language},
                )
                await conversation_turn_service.save_message(
                    session, conversation.id, role="agent", content=failure_reply,
                    metadata={"event_type": "stt_error", "stage": "stt"},
                )
        return {
            "session_id": session_id, "transcript": "", "language": failure_language,
            "language_confidence": confidence, "reply": failure_reply,
            "audio_url": None, "is_completed": False, "target_slot": None,
            "booking_confirmed": False,
        }

    async with AsyncSessionLocal() as session:
        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.get_by_call_sid(session_id)
        if conversation:
            await conversation_turn_service.save_message(
                session, conversation.id, role="patient", content=transcript,
                metadata={"language": language, "confidence": confidence},
            )
            if (conversation.collected_details or {}).get("stt_failures"):
                await conversation_repo.update_collected_details(conversation.id, {"stt_failures": 0})

    try:
        translation_started = time.perf_counter()
        if language == "en-IN" and _INDIC_SCRIPT.search(transcript):
            agent_input = await _english_from_indic_script(transcript)
        else:
            agent_input = await _to_english(transcript, language)
        logger.info(
            "Voice assistant input translation completed: session_id=%s language=%s duration=%.3fs",
            session_id, language, time.perf_counter() - translation_started,
        )
    except Exception:
        logger.exception("Voice input translation failed: session_id=%s error_stage=input_translation", session_id)
        reply = _voice_retry_message(language)
        async with AsyncSessionLocal() as session:
            failed_conversation = await ConversationRepository(session).get_by_call_sid(session_id)
            if failed_conversation:
                await conversation_turn_service.save_message(
                    session, failed_conversation.id, role="agent", content=reply,
                    metadata={"event_type": "translation_error", "stage": "input_translation"},
                )
        return {
            "session_id": session_id, "transcript": transcript, "language": language,
            "language_confidence": confidence, "reply": reply, "audio_url": None,
            "is_completed": False, "target_slot": None, "booking_confirmed": False,
        }
    async with AsyncSessionLocal() as session:
        conversation_repo = ConversationRepository(session)
        existing_conversation = await conversation_repo.get_by_call_sid(session_id)
        if not existing_conversation:
            existing_conversation = await conversation_repo.create(
                channel=ChannelType.VOICE,
                call_sid=session_id,
            )

        saved_details = (
            dict(existing_conversation.collected_details or {})
            if existing_conversation
            else {}
        )
        patient_name = (
            saved_details.get("patient_name")
            or saved_details.get("registration_name")
            if not is_greeting(saved_details.get("patient_name") or saved_details.get("registration_name", ""))
            else None
        )
        patient_dob = saved_details.get("patient_dob") or saved_details.get("registration_dob")

        input_state = {
            "call_sid": session_id,
            "conversation_id": str(existing_conversation.id),
            "patient_id": str(existing_conversation.patient_id) if existing_conversation and existing_conversation.patient_id else saved_details.get("patient_id"),
            "patient_phone": saved_details.get("patient_phone", ""),
            "patient_name": patient_name,
            "patient_dob": patient_dob,
            "channel": "voice_assistant",
            "latest_user_speech": agent_input,
            "messages": list(existing_conversation.messages or []),
            "is_verified": bool(
                existing_conversation.identity_verified_at
                or saved_details.get("is_verified", False)
            ),
            "is_new_patient": bool(saved_details.get("is_new_patient")),
            "awaiting_identity_verification": bool(saved_details.get("awaiting_identity_verification")),
            "pending_intent": saved_details.get("pending_intent"),
            "intent": saved_details.get("intent"),
            "preferred_language": language,
            "language_confirmed": confidence >= settings.VOICE_ASSISTANT_LANGUAGE_CONFIDENCE_THRESHOLD,
            "language_confidence": confidence,
        }
        for field in (
            "patient_id",
            "patient_phone",
            "patient_email",
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
            "verify_attempts",
            "handoff_required",
            "handoff_reason",
            "awaiting_handoff_contact",
            "handoff_completed",
            "frontdesk_alert_sent",
            "is_emergency",
        ):
            if field in saved_details:
                input_state[field] = saved_details[field]

        input_state["latest_agent_speech"] = next(
            (message.get("content") for message in reversed(existing_conversation.messages or [])
             if message.get("role") == "agent"),
            "",
        )

        try:
            agent_started = time.perf_counter()
            turn = await asyncio.wait_for(
                _run_voice_turn_in_isolated_session(
                    conversation_id=existing_conversation.id,
                    thread_id=session_id,
                    channel="voice_assistant",
                    patient_text=agent_input,
                    patient_message_saved=True,
                    input_state=input_state,
                    response_transform=lambda text: _translate(text, language),
                ),
                timeout=settings.VOICE_ASSISTANT_TURN_TIMEOUT_SECONDS,
            )
            logger.info(
                "Voice assistant agent turn completed: session_id=%s language=%s duration=%.3fs",
                session_id, language, time.perf_counter() - agent_started,
            )
        except asyncio.TimeoutError:
            logger.warning("Voice assistant agent turn timed out: session_id=%s", session_id)
            reply = _voice_processing_message(language)
            await conversation_turn_service.save_message(
                session, existing_conversation.id, role="agent", content=reply,
                metadata={"event_type": "timeout", "stage": "agent_turn", "language": language},
            )
            await session.commit()
            return {
                "session_id": session_id, "transcript": transcript, "language": language,
                "language_confidence": confidence, "reply": reply, "audio_url": None,
                "is_completed": False, "target_slot": None, "booking_confirmed": False,
            }
        result = turn.state
        reply = turn.speech
    # An untranslated English reply must be voiced in English, not read out by a Tamil/Telugu voice.
    tts_language = "en-IN" if turn.error_stage == "response_translation" else language
    audio_url = None
    if settings.VOICE_ASSISTANT_TTS_ENABLED:
        try:
            tts_started = time.perf_counter()
            generated_audio = await sarvam_service.text_to_speech(reply, target_language_code=tts_language)
            if not generated_audio:
                # A transient empty TTS result should not immediately force the
                # browser fallback. Retry once for both Tamil and Telugu.
                generated_audio = await sarvam_service.text_to_speech(reply, target_language_code=tts_language)
            logger.info(
                "Voice assistant TTS completed: session_id=%s language=%s duration=%.3fs audio=%s",
                session_id, language, time.perf_counter() - tts_started, bool(generated_audio),
            )
            if generated_audio:
                audio_id = await audio_storage_service.store(generated_audio)
                audio_url = f"/api/voice-assistant/audio/{audio_id}"
            else:
                logger.warning("Voice assistant TTS returned no audio: session_id=%s error_stage=tts", session_id)
                async with AsyncSessionLocal() as event_session:
                    await conversation_turn_service.annotate_last_agent_message(
                        event_session, existing_conversation.id,
                        {"audio_delivery": "browser_fallback", "tts_error": "empty_audio"},
                    )
        except Exception:
            logger.exception("Voice assistant TTS failed: session_id=%s error_stage=tts", session_id)
            async with AsyncSessionLocal() as event_session:
                await conversation_turn_service.annotate_last_agent_message(
                    event_session, existing_conversation.id,
                    {"audio_delivery": "browser_fallback", "tts_error": "provider_exception"},
                )

    return {
        "session_id": session_id,
        "transcript": transcript,
        "language": language,
        "language_confidence": confidence,
        "reply": reply,
        "audio_url": audio_url,
        "is_completed": result.get("is_completed", False),
        "target_slot": result.get("target_slot_details"),
        "booking_confirmed": result.get("booking_confirmed", False),
    }


@router.post("/tts")
async def generate_voice_assistant_tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    generated_audio = await sarvam_service.text_to_speech(req.text.strip(), target_language_code=req.language)
    if not generated_audio:
        raise HTTPException(status_code=500, detail="Failed to synthesize speech.")
    audio_id = await audio_storage_service.store(generated_audio)
    return {"audio_url": f"/api/voice-assistant/audio/{audio_id}"}


@router.get("/audio/{audio_id}")
async def get_voice_audio(audio_id: str):
    audio = await audio_storage_service.get(audio_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio expired or not found.")
    return Response(content=audio, media_type="audio/wav")
