"""Shared conversation-turn execution and persistence for patient channels."""
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.graph import get_agent_graph
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository
from src.data.repositories.outbound_call_repository import OutboundCallRepository
from src.observability.metrics import (
    conversation_turn_duration_seconds,
    voice_turn_duration_seconds,
    voice_turn_total,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationTurnResult:
    speech: str
    completed: bool
    handoff_required: bool
    state: dict[str, Any]
    error_stage: Optional[str] = None


class ConversationTurnService:
    """Runs one agent turn and persists the complete turn consistently."""

    _PERSISTED_FIELDS = (
        "intent", "pending_intent", "is_verified", "is_new_patient",
        "awaiting_identity_verification", "patient_id", "patient_name",
        "patient_dob", "patient_email", "patient_phone", "verify_attempts",
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
        "awaiting_cancel_confirmation", "awaiting_change_action_choice",
        "preferred_language", "language_confirmed", "language_confidence",
        "handoff_required", "handoff_reason", "awaiting_handoff_contact", "handoff_completed",
        "frontdesk_alert_sent",
        "is_emergency",
        "is_completed", "booking_confirmed",
    )

    @staticmethod
    def _conversation_state(result: dict[str, Any]) -> ConversationState | None:
        if result.get("handoff_required"):
            return ConversationState.HANDED_TO_FRONT_DESK
        intent = str(result.get("intent") or "").lower()
        if intent == "close":
            return None  # end_call has already recorded the final state
        if result.get("booking_confirmed"):
            return {"book": ConversationState.BOOKED, "reschedule": ConversationState.RESCHEDULED,
                    "cancel": ConversationState.CANCELLED}.get(intent)
        if result.get("target_slot_id"):
            return ConversationState.SLOT_RESERVED
        if result.get("is_verified"):
            return ConversationState.COLLECTING_DETAILS
        if result.get("awaiting_identity_verification") or result.get("pending_intent"):
            return ConversationState.IDENTIFYING_PATIENT
        return None

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): ConversationTurnService._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [ConversationTurnService._json_safe(item) for item in value]
        if isinstance(value, (uuid.UUID,)):
            return str(value)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    async def save_message(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID | str,
        *,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Single entry point for persisting patient/agent transcript messages."""
        await ConversationRepository(db).append_message(
            uuid.UUID(str(conversation_id)),
            role=role,
            content=content,
            metadata=self._json_safe(metadata or {}),
        )

    async def annotate_last_agent_message(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID | str,
        metadata: dict[str, Any],
    ) -> None:
        await ConversationRepository(db).update_last_agent_message_metadata(
            uuid.UUID(str(conversation_id)), self._json_safe(metadata)
        )

    async def run_turn(
        self,
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID | str,
        thread_id: str,
        channel: str,
        patient_text: str,
        input_state: dict[str, Any],
        patient_metadata: Optional[dict[str, Any]] = None,
        patient_message_saved: bool = False,
        response_transform: Optional[Callable[[str], Awaitable[str]]] = None,
        invoke: Optional[Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = None,
    ) -> ConversationTurnResult:
        """Execute and persist one full turn for chat and all voice transports."""
        started_at = time.perf_counter()
        convo_id = uuid.UUID(str(conversation_id))
        repo = ConversationRepository(db)
        error_stage: Optional[str] = None
        result: dict[str, Any]

        try:
            if not patient_message_saved:
                await self.save_message(
                    db, convo_id, role="patient", content=patient_text,
                    metadata=patient_metadata,
                )
            conversation = await repo.get(convo_id)
            input_state = {
                **input_state,
                "conversation_id": str(convo_id),
                "channel": channel,
                "latest_user_speech": input_state.get("latest_user_speech") or patient_text,
                # PostgreSQL transcript is the canonical turn history restored
                # on every request, including after a process restart.
                "messages": list(conversation.messages or []) if conversation else [],
            }
        except Exception:
            error_stage = "persistence"
            logger.exception("Conversation turn failed: error_stage=persistence conversation_id=%s channel=%s", convo_id, channel)
            await db.rollback()
        if error_stage is None:
            try:
                if invoke:
                    result = await invoke(input_state)
                else:
                    result = await get_agent_graph().ainvoke(
                        input_state,
                        config={"configurable": {"thread_id": thread_id, "db": db}},
                    )
            except Exception:
                error_stage = "graph"
                logger.exception("Conversation turn failed: error_stage=graph conversation_id=%s channel=%s", convo_id, channel)
                await db.rollback()
        if error_stage is not None:
            result = {
                "latest_agent_speech": "I am sorry, I had trouble processing that. Please try again or contact the front desk.",
                "is_completed": False,
                "handoff_required": False,
            }

        speech = result.get("latest_agent_speech") or "How can I help you?"
        if response_transform and error_stage is None:
            try:
                speech = await response_transform(speech)
                if not speech:
                    raise ValueError("Response translation returned empty text")
            except Exception:
                error_stage = "response_translation"
                logger.exception("Conversation turn failed: error_stage=response_translation conversation_id=%s channel=%s", convo_id, channel)
                speech = result.get("latest_agent_speech") or "I am sorry, I could not translate my reply. Please try again."
        result["latest_agent_speech"] = speech

        try:
            metadata = {"event_type": f"{error_stage}_error"} if error_stage else None
            await self.save_message(db, convo_id, role="agent", content=speech, metadata=metadata)

            state_to_save = {
                field: self._json_safe(result[field])
                for field in self._PERSISTED_FIELDS
                if field in result
            }
            if "target_slot_id" in result and result["target_slot_id"] is None:
                state_to_save["target_slot_details"] = None
            if state_to_save:
                await repo.update_collected_details(convo_id, state_to_save)
            patient_id = result.get("patient_id")
            if patient_id:
                try:
                    await repo.set_patient(convo_id, uuid.UUID(str(patient_id)))
                except (ValueError, TypeError):
                    logger.warning("Invalid patient id returned for conversation %s", convo_id)
            if result.get("is_verified"):
                await repo.mark_identity_verified(convo_id)
            await repo.persist_turn_progress(
                convo_id, state=self._conversation_state(result),
                step={"at": datetime.now(timezone.utc).isoformat(), "channel": channel,
                      "intent": result.get("intent"), "error_stage": error_stage},
            )
            if result.get("booking_confirmed"):
                await repo.record_action_outcome(convo_id, result.get("intent"))
            await db.commit()
        except Exception:
            logger.exception("Conversation turn failed: error_stage=persistence conversation_id=%s", convo_id)
            await db.rollback()
            # Keep the generated response usable even when the transcript write fails.

        elapsed = time.perf_counter() - started_at
        voice_turn_duration_seconds.observe(elapsed)
        conversation_turn_duration_seconds.labels(channel).observe(elapsed)
        voice_turn_total.labels("completed" if result.get("is_completed") else "continued").inc()
        return ConversationTurnResult(
            speech=speech,
            completed=bool(result.get("is_completed", False)),
            handoff_required=bool(result.get("handoff_required", False)),
            state=result,
            error_stage=error_stage,
        )

    async def run_outbound_turn(
        self,
        db: AsyncSession,
        *,
        call_sid: str,
        patient_text: str,
        patient_phone: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ConversationTurnResult:
        turn_started_at = time.perf_counter()
        call_record = None
        if conversation_id:
            conversation_uuid = uuid.UUID(conversation_id)
            stored_phone = patient_phone or ""
        else:
            lookup_started_at = time.perf_counter()
            call_record = await OutboundCallRepository(db).get_by_provider_call_id(call_sid)
            if not call_record:
                raise LookupError("Outbound call was not found.")
            conversation_uuid = call_record.conversation_id
            stored_phone = call_record.number_called
            logger.info(
                "Outbound turn lookup for %s completed in %.3fs",
                call_sid,
                time.perf_counter() - lookup_started_at,
            )

        conversation_repo = ConversationRepository(db)
        conversation = await conversation_repo.get(conversation_uuid)
        if not conversation:
            raise LookupError("Outbound conversation was not found.")

        input_state: dict[str, Any] = {
            "call_sid": call_sid,
            "conversation_id": str(conversation_uuid),
            "patient_phone": stored_phone,
            "channel": "outbound_call",
            "latest_user_speech": patient_text,
            "is_verified": bool(conversation.identity_verified_at),
        }
        if conversation.patient_id:
            input_state["patient_id"] = str(conversation.patient_id)
        if conversation.collected_details:
            for key, value in conversation.collected_details.items():
                input_state.setdefault(key, value)

        turn = await self.run_turn(
            db,
            conversation_id=conversation_uuid,
            thread_id=call_sid,
            channel="outbound_call",
            patient_text=patient_text,
            input_state=input_state,
        )
        logger.info("Outbound conversation turn finished: call_sid=%s duration=%.3fs", call_sid, time.perf_counter() - turn_started_at)
        return turn


conversation_turn_service = ConversationTurnService()

