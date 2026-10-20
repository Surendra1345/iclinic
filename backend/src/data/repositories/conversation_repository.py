"""Conversation repository — manage conversation lifecycle and message history."""
import uuid
from datetime import datetime
from typing import Any, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import select, update
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import (
    ChannelType,
    ConfirmationStatusType,
    ConversationState,
    OutcomeType,
)
from src.data.models.postgres.conversation import Conversation


class ConversationRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        channel: ChannelType,
        call_sid: Optional[str] = None,
        patient_id: Optional[uuid.UUID] = None,
    ) -> Conversation:
        """Create a new conversation row at the start of a call/session."""
        convo = Conversation(
            id=uuid.uuid4(),
            channel=channel,
            patient_id=patient_id,
            current_state=ConversationState.STARTED,
            confirmation_status=ConfirmationStatusType.PENDING,
            started_at=datetime.utcnow(),
            collected_details={"call_sid": call_sid} if call_sid else {},
            state_history=[],
            messages=[],
            step_logs=[],
        )
        self.db.add(convo)
        await self.db.commit()
        await self.db.refresh(convo)
        return convo

    async def get(self, conversation_id: uuid.UUID) -> Optional[Conversation]:
        return await self.db.get(Conversation, conversation_id)

    async def get_by_call_sid(self, call_sid: str) -> Optional[Conversation]:
        """Find conversation record by Twilio CallSid."""
        res = await self.db.execute(
            select(Conversation)
            .where(Conversation.collected_details["call_sid"].astext == call_sid)
            .order_by(Conversation.started_at.desc())
            .limit(1)
        )
        return res.scalars().first()

    async def update_state(
        self,
        conversation_id: uuid.UUID,
        new_state: ConversationState,
    ) -> None:
        """Update the current_state field and append to state_history."""
        convo = await self.db.get(Conversation, conversation_id)
        if convo:
            history: list = list(convo.state_history or [])
            history.append({"state": new_state.value, "at": datetime.utcnow().isoformat()})
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(current_state=new_state, state_history=history)
            )
            await self.db.commit()

    async def set_patient(self, conversation_id: uuid.UUID, patient_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(patient_id=patient_id)
        )
        await self.db.commit()

    async def mark_identity_verified(self, conversation_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(identity_verified_at=datetime.utcnow())
        )
        await self.db.commit()

    async def append_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Append a turn message to conversation.messages (turn-by-turn storage) and commit."""
        convo = await self.db.get(Conversation, conversation_id)
        if convo:
            messages: list = list(convo.messages or [])
            messages.append(
                {
                    "role": role,       # "patient" | "agent"
                    "content": content,
                    "at": datetime.utcnow().isoformat(),
                    **(metadata or {}),
                }
            )
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(messages=messages)
            )
            await self.db.commit()

    async def update_collected_details(
        self,
        conversation_id: uuid.UUID,
        details: dict[str, Any],
    ) -> None:
        """Merge new key-value pairs into conversation.collected_details and commit."""
        convo = await self.db.get(Conversation, conversation_id)
        if convo:
            merged = {**(convo.collected_details or {}), **details}
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(collected_details=merged)
            )
            await self.db.commit()

    async def update_confirmation_status(
        self,
        conversation_id: uuid.UUID,
        status: ConfirmationStatusType,
    ) -> None:
        """Update confirmation_status on conversation."""
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(confirmation_status=status)
        )
        await self.db.commit()

    async def record_action_outcome(
        self,
        conversation_id: uuid.UUID,
        intent: Optional[str],
    ) -> None:
        """Record a successfully completed booking, reschedule, or cancellation."""
        outcomes = {
            "book": (ConversationState.BOOKED, OutcomeType.BOOKED),
            "reschedule": (ConversationState.RESCHEDULED, OutcomeType.RESCHEDULED),
            "cancel": (ConversationState.CANCELLED, OutcomeType.CANCELLED),
        }
        action = (intent or "").lower()
        if action not in outcomes:
            return
        state, outcome = outcomes[action]
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(current_state=state, outcome=outcome, updated_at=datetime.utcnow())
        )
        await self.db.commit()

    async def close(
        self,
        conversation_id: uuid.UUID,
        outcome: OutcomeType,
        handoff_reason: Optional[str] = None,
        confirmation_status: ConfirmationStatusType = ConfirmationStatusType.SENT,
    ) -> None:
        """Mark a conversation as ended with final outcome."""
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                ended_at=datetime.utcnow(),
                current_state=ConversationState.BOOKED
                if outcome == OutcomeType.BOOKED
                else ConversationState.RESCHEDULED
                if outcome == OutcomeType.RESCHEDULED
                else ConversationState.CANCELLED
                if outcome == OutcomeType.CANCELLED
                else ConversationState.HANDED_TO_FRONT_DESK
                if outcome == OutcomeType.HANDED_TO_FRONT_DESK
                else ConversationState.ABANDONED,
                outcome=outcome,
                handoff_reason=handoff_reason,
                confirmation_status=confirmation_status,
            )
        )
        await self.db.commit()
