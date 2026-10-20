"""Browser voice-assistant endpoints, separate from Twilio outbound calls."""
from src.constants.enums import ChannelType
import base64
import logging
import time
from html import escape
from uuid import uuid4

from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from src.config.settings import settings
from src.control.agents.graph import agent_graph
from src.control.agents.tools.registration_tools import is_greeting
from src.data.clients.postgres import AsyncSessionLocal
from src.data.repositories.conversation_repository import ConversationRepository
from src.services.gemini_service import GeminiService
from src.services.sarvam_service import SarvamService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice-assistant", tags=["Browser Voice Assistant"])
sarvam_service = SarvamService()
gemini_service = GeminiService()
_audio_cache: dict[str, tuple[bytes, float]] = {}
_SUPPORTED_LANGUAGES = {"en-IN", "ta-IN", "te-IN"}


def _normalize_language(language: str) -> str:
    language = (language or "").lower().replace("_", "-")
    if language.startswith("ta"):
        return "ta-IN"
    if language.startswith("te"):
        return "te-IN"
    return "en-IN"


async def _translate(text: str, target_language: str) -> str:
    if not text or target_language == "en-IN":
        return text
    prompt = (
        f"Translate the following clinic assistant message into {_normalize_language(target_language)}. "
        "Preserve doctor names, branch names, dates, times, and appointment details. "
        "Return only the translation.\n\n"
        f"Message: {text}"
    )
    return await gemini_service.generate_content(prompt, temperature=0.0)


async def _to_english(text: str, language: str) -> str:
    if not text or language == "en-IN":
        return text
    prompt = (
        f"Translate the following patient message from {_normalize_language(language)} into English. "
        "Return only the translation and preserve names, dates, times, doctors, and locations.\n\n"
        f"Message: {text}"
    )
    return await gemini_service.generate_content(prompt, temperature=0.0)


@router.post("/session")
async def create_voice_session():
    session_id = f"browser_voice_{uuid4().hex}"
    return {
        "session_id": session_id,
        "preferred_language": "en-IN",
        "language_confirmed": False,
        "greeting": f"Hello! Welcome to {settings.CLINIC_NAME}. How can I help you today?",
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

    audio_bytes = await audio.read()
    if not audio_bytes:
        async with AsyncSessionLocal() as session:
            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get_by_call_sid(session_id)
            if conversation:
                await conversation_repo.append_message(
                    conversation.id,
                    role="patient",
                    content="[Voice input was empty]",
                    metadata={"event_type": "voice_input_error"},
                )
        raise HTTPException(status_code=400, detail="Audio input is empty.")

    transcript, detected_language, confidence = await sarvam_service.speech_to_text(
        audio_bytes,
        filename=audio.filename or "voice.webm",
        language_code="unknown",
        content_type=audio.content_type,
    )
    language = _normalize_language(detected_language)
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
        async with AsyncSessionLocal() as session:
            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get_by_call_sid(session_id)
            if conversation:
                await conversation_repo.append_message(
                    conversation.id,
                    role="patient",
                    content="[Voice input could not be transcribed]",
                    metadata={"event_type": "stt_error", "language": language},
                )
        raise HTTPException(status_code=422, detail="Could not understand the audio.")

    async with AsyncSessionLocal() as session:
        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.get_by_call_sid(session_id)
        if conversation:
            await conversation_repo.append_message(
                conversation.id,
                role="patient",
                content=transcript,
                metadata={"language": language, "confidence": confidence},
            )

    agent_input = await _to_english(transcript, language)
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
            "is_verified": bool(saved_details.get("is_verified", False)),
            "is_new_patient": bool(saved_details.get("is_new_patient")),
            "awaiting_identity_verification": bool(saved_details.get("awaiting_identity_verification")),
            "pending_intent": saved_details.get("pending_intent"),
            "intent": saved_details.get("intent"),
            "preferred_language": language,
            "language_confirmed": True,
            "language_confidence": confidence,
        }
        for field in (
            "patient_id",
            "target_slot_id",
            "target_slot_details",
            "active_appointment_id",
            "active_appointment_details",
            "preferred_specialty",
            "preferred_location",
            "preferred_doctor",
            "preferred_date",
            "awaiting_preferred_date",
            "awaiting_patient_email",
        ):
            if field in saved_details:
                input_state[field] = saved_details[field]

        try:
            result = await agent_graph.ainvoke(
                input_state,
                config={"configurable": {"thread_id": session_id, "db": session}},
            )
        except Exception:
            logger.exception("Browser voice agent turn failed for session %s", session_id)
            reply = "I’m sorry, I had trouble processing that. Please repeat your request or contact the front desk."
            await conversation_repo.append_message(
                existing_conversation.id,
                role="agent",
                content=reply,
                metadata={"event_type": "turn_error"},
            )
            return {
                "session_id": session_id,
                "transcript": transcript,
                "language": language,
                "language_confidence": confidence,
                "reply": reply,
                "audio_url": None,
                "is_completed": False,
                "target_slot": None,
                "booking_confirmed": False,
            }

        reply_english = result.get("latest_agent_speech") or "How can I help you with your appointment today?"
        reply = await _translate(reply_english, language)
        if result.get("booking_confirmed"):
            await conversation_repo.record_action_outcome(
                existing_conversation.id,
                result.get("intent"),
            )
        await conversation_repo.append_message(
            existing_conversation.id,
            role="agent",
            content=reply,
        )

        persisted_fields = {
            field: result[field]
            for field in (
                "patient_id",
                "patient_name",
                "target_slot_id",
                "target_slot_details",
                "active_appointment_id",
                "active_appointment_details",
                "preferred_specialty",
                "preferred_location",
                "preferred_doctor",
                "preferred_date",
                "awaiting_preferred_date",
                "awaiting_patient_email",
                "intent",
            )
            if field in result and result[field] is not None
        }
        if "target_slot_id" in result and result["target_slot_id"] is None:
            persisted_fields["target_slot_id"] = None
            persisted_fields["target_slot_details"] = None
        if "awaiting_preferred_date" in result:
            persisted_fields["awaiting_preferred_date"] = result["awaiting_preferred_date"]
        if "awaiting_patient_email" in result:
            persisted_fields["awaiting_patient_email"] = result["awaiting_patient_email"]
        if "awaiting_identity_verification" in result:
            persisted_fields["awaiting_identity_verification"] = result["awaiting_identity_verification"]
        if "pending_intent" in result:
            persisted_fields["pending_intent"] = result["pending_intent"]
        if result.get("patient_phone"):
            persisted_fields["patient_phone"] = result["patient_phone"]
        if result.get("patient_email"):
            persisted_fields["patient_email"] = result["patient_email"]
        if result.get("patient_name"):
            persisted_fields["patient_name"] = result["patient_name"]
            persisted_fields["registration_name"] = result["patient_name"]
        if result.get("patient_dob") is not None:
            persisted_fields["patient_dob"] = str(result["patient_dob"])
            persisted_fields["registration_dob"] = str(result["patient_dob"])
        if result.get("is_new_patient") is not None:
            persisted_fields["is_new_patient"] = result["is_new_patient"]
        if "is_verified" in result:
            persisted_fields["is_verified"] = result["is_verified"]
        if persisted_fields:
            await conversation_repo.update_collected_details(
                existing_conversation.id,
                persisted_fields,
            )
        if result.get("patient_id"):
            try:
                import uuid
                await conversation_repo.update_patient(
                    existing_conversation.id,
                    uuid.UUID(str(result["patient_id"])),
                )
            except Exception:
                pass
        await session.commit()
    audio_url = None
    if settings.VOICE_ASSISTANT_TTS_ENABLED:
        generated_audio = await sarvam_service.text_to_speech(reply, target_language_code=language)
        if generated_audio:
            audio_id = uuid4().hex
            _audio_cache[audio_id] = (generated_audio, time.time() + 900)
            audio_url = f"/api/voice-assistant/audio/{audio_id}"

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


class TTSRequest(BaseModel):
    text: str
    language: Optional[str] = "en-IN"


@router.post("/tts")
async def generate_voice_assistant_tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    generated_audio = await sarvam_service.text_to_speech(req.text.strip(), target_language_code=req.language)
    if not generated_audio:
        raise HTTPException(status_code=500, detail="Failed to synthesize speech.")
    audio_id = uuid4().hex
    _audio_cache[audio_id] = (generated_audio, time.time() + 900)
    return {"audio_url": f"/api/voice-assistant/audio/{audio_id}"}


@router.get("/audio/{audio_id}")
async def get_voice_audio(audio_id: str):
    cached = _audio_cache.get(audio_id)
    if not cached or cached[1] <= time.time():
        _audio_cache.pop(audio_id, None)
        raise HTTPException(status_code=404, detail="Audio expired or not found.")
    return Response(content=cached[0], media_type="audio/wav")
