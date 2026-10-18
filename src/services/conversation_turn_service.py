"""Shared conversation-turn execution for Twilio voice transports."""
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.graph import agent_graph
from src.data.repositories.conversation_repository import ConversationRepository
from src.data.repositories.outbound_call_repository import OutboundCallRepository
from src.observability.metrics import (
    database_operation_duration_seconds,
    voice_turn_duration_seconds,
    voice_turn_total,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationTurnResult:
    speech: str
    completed: bool
    handoff_required: bool


class ConversationTurnService:
    """Runs one agent turn and persists the complete turn consistently."""

    _PERSISTED_FIELDS = (
        "target_slot_id",
        "target_slot_details",
        "active_appointment_id",
        "patient_name",
        "patient_id",
        "preferred_specialty",
        "preferred_location",
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

        persistence_started_at = time.perf_counter()
        db_started = time.perf_counter()
        await conversation_repo.append_message(
            conversation_uuid,
            role="patient",
            content=patient_text,
        )
        logger.info(
            "Persisted patient message for %s in %.3fs",
            call_sid,
            time.perf_counter() - persistence_started_at,
        )
        database_operation_duration_seconds.labels("append_patient_message").observe(
            time.perf_counter() - db_started
        )

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

        graph_started_at = time.perf_counter()
        try:
            result = await agent_graph.ainvoke(
                input_state,
                config={"configurable": {"thread_id": call_sid, "db": db}},
            )
        except Exception:
            logger.exception("Agent turn failed for call %s", call_sid)
            fallback = "I apologize, let me connect you with our front desk receptionist."
            await conversation_repo.append_message(
                conversation_uuid,
                role="agent",
                content=fallback,
            )
            return ConversationTurnResult(
                speech=fallback,
                completed=True,
                handoff_required=True,
            )
        logger.info(
            "Agent graph for %s completed in %.3fs",
            call_sid,
            time.perf_counter() - graph_started_at,
        )
        commit_started = time.perf_counter()
        await db.commit()
        database_operation_duration_seconds.labels("turn_commit").observe(
            time.perf_counter() - commit_started
        )

        speech = result.get("latest_agent_speech") or "Thank you."
        response_persistence_started_at = time.perf_counter()
        await conversation_repo.append_message(
            conversation_uuid,
            role="agent",
            content=speech,
        )

        state_to_save = {
            field: result[field]
            for field in self._PERSISTED_FIELDS
            if field in result
        }
        if state_to_save:
            await conversation_repo.update_collected_details(
                conversation_uuid,
                state_to_save,
            )
        logger.info(
            "Persisted agent response for %s in %.3fs; total service time %.3fs",
            call_sid,
            time.perf_counter() - response_persistence_started_at,
            time.perf_counter() - turn_started_at,
        )
        voice_turn_duration_seconds.observe(time.perf_counter() - turn_started_at)
        voice_turn_total.labels("completed" if result.get("is_completed") else "continued").inc()

        return ConversationTurnResult(
            speech=speech,
            completed=bool(result.get("is_completed", False)),
            handoff_required=bool(result.get("handoff_required", False)),
        )


conversation_turn_service = ConversationTurnService()
