"""Appointment service — atomic database transactions for booking, rescheduling, and cancelling."""
import uuid
from datetime import datetime, timedelta
from typing import Optional

# pyrefly: ignore[missing-import]
from sqlalchemy import select
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.constants.enums import AppointmentStatus, ChannelType, ConfirmationStatusType, ConversationState, SlotStatus
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.appointment_cancellation import AppointmentCancellation
from src.data.models.postgres.appointment_reschedule import AppointmentReschedule
from src.data.models.postgres.conversation import Conversation
from src.core.exceptions import AppointmentServiceError
from src.data.models.postgres.slot import Slot


class AppointmentService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def book_appointment_atomic(
        self,
        *,
        patient_id: uuid.UUID,
        slot_id: uuid.UUID,
        appointment_type_id: uuid.UUID,
        conversation_id: uuid.UUID,
        channel: ChannelType = ChannelType.OUTBOUND_CALL,
        reason: Optional[str] = None,
    ) -> Appointment:
        """
        Atomically book a slot for a patient:
        1. Check if patient already has an active booked appointment (one patient one slot).
        2. Lock and verify the slot is available (or reserved for this session).
        3. Transition slot status to 'booked'.
        4. Insert appointment record.
        """
        # 1. One active appointment per patient check
        existing_appt = await self.db.scalar(
            select(Appointment).where(
                Appointment.patient_id == patient_id,
                Appointment.status == AppointmentStatus.BOOKED,
            )
        )
        if existing_appt:
            raise AppointmentServiceError(
                "Patient already has an active appointment. Multiple active appointments are not allowed."
            )

        # 2. Lock slot with FOR UPDATE
        slot_query = select(Slot).where(Slot.id == slot_id).with_for_update()
        slot = await self.db.scalar(slot_query)
        if not slot:
            raise AppointmentServiceError(f"Slot {slot_id} does not exist.")

        # Check slot start time is in the future
        now = datetime.now(slot.start_time.tzinfo) if slot.start_time.tzinfo else datetime.utcnow()
        if slot.start_time <= now:
            raise AppointmentServiceError("Cannot book a slot in the past.")

        if slot.status == SlotStatus.BOOKED:
            raise AppointmentServiceError("Slot is already booked.")

        # 3. Mark slot as booked
        slot.status = SlotStatus.BOOKED
        slot.reserved_until = None

        # 4. Create appointment
        appt = Appointment(
            id=uuid.uuid4(),
            patient_id=patient_id,
            slot_id=slot_id,
            appointment_type_id=appointment_type_id,
            conversation_id=conversation_id,
            channel=channel,
            reason=reason,
            status=AppointmentStatus.BOOKED,
        )
        self.db.add(appt)
        await self.db.flush()
        await self.db.refresh(appt)
        return appt

    async def reschedule_appointment_atomic(
        self,
        *,
        appointment_id: uuid.UUID,
        new_slot_id: uuid.UUID,
        conversation_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> tuple[Appointment, AppointmentReschedule]:
        """
        Atomically reschedule an appointment to a new slot:
        1. Lock appointment and current slot.
        2. Verify 24-hour cutoff policy.
        3. Verify new slot is different from old slot.
        4. Lock new slot and verify it is available and in future.
        5. Release old slot (set available).
        6. Book new slot (set booked).
        7. Update appointment to point to new slot.
        8. Record in appointment_reschedules audit table.
        """
        # 1. Lock appointment
        appt = await self.db.scalar(
            select(Appointment).where(Appointment.id == appointment_id).with_for_update()
        )
        if not appt:
            raise AppointmentServiceError(f"Appointment {appointment_id} not found.")

        if appt.status not in (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED):
            raise AppointmentServiceError(
                f"Only active appointments can be rescheduled. Current status: {appt.status.value}."
            )

        if appt.slot_id == new_slot_id:
            raise AppointmentServiceError("Cannot reschedule to the exact same slot you already have.")

        # 2. Lock current slot and check 24h cutoff
        current_slot = await self.db.scalar(
            select(Slot).where(Slot.id == appt.slot_id).with_for_update()
        )
        if current_slot:
            now_curr = datetime.now(current_slot.start_time.tzinfo) if current_slot.start_time.tzinfo else datetime.utcnow()
            hours_until = (current_slot.start_time - now_curr).total_seconds() / 3600
            if hours_until < settings.RESCHEDULE_CANCEL_CUTOFF_HOURS:
                raise AppointmentServiceError(
                    f"Appointments less than {settings.RESCHEDULE_CANCEL_CUTOFF_HOURS} hours away cannot be modified online. Please contact front desk."
                )

        # 4. Lock new slot
        new_slot = await self.db.scalar(
            select(Slot).where(Slot.id == new_slot_id).with_for_update()
        )
        if not new_slot:
            raise AppointmentServiceError(f"New slot {new_slot_id} does not exist.")

        now_new = datetime.now(new_slot.start_time.tzinfo) if new_slot.start_time.tzinfo else datetime.utcnow()
        if new_slot.start_time <= now_new:
            raise AppointmentServiceError("Cannot reschedule to a slot in the past.")

        if new_slot.status == SlotStatus.BOOKED:
            raise AppointmentServiceError("The requested new slot is already booked.")

        old_slot_id = appt.slot_id

        # 5. Release old slot
        if current_slot:
            current_slot.status = SlotStatus.AVAILABLE
            current_slot.reserved_until = None

        # 6. Book new slot
        new_slot.status = SlotStatus.BOOKED
        new_slot.reserved_until = None

        # 7. Update appointment
        appt.slot_id = new_slot_id
        appt.status = AppointmentStatus.RESCHEDULED

        # 8. Record audit entry
        convo = await self.db.get(Conversation, conversation_id)
        if not convo:
            convo = Conversation(
                id=conversation_id,
                channel=ChannelType.CHAT,
                current_state=ConversationState.BOOKED,
                confirmation_status=ConfirmationStatusType.PENDING,
            )
            self.db.add(convo)
            await self.db.flush()

        reschedule_log = AppointmentReschedule(
            id=uuid.uuid4(),
            old_appointment_id=appointment_id,
            new_appointment_id=appointment_id,
            old_slot_id=old_slot_id,
            new_slot_id=new_slot_id,
            conversation_id=conversation_id,
            reason=reason,
        )
        self.db.add(reschedule_log)

        await self.db.flush()
        await self.db.refresh(appt)
        await self.db.refresh(reschedule_log)

        return appt, reschedule_log

    async def cancel_appointment_atomic(
        self,
        *,
        appointment_id: uuid.UUID,
        conversation_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> tuple[Appointment, AppointmentCancellation]:
        """
        Atomically cancel an appointment:
        1. Lock appointment and current slot.
        2. Verify 24h cutoff.
        3. Update appointment status -> CANCELLED.
        4. Release slot -> AVAILABLE.
        5. Record audit entry in appointment_cancellations.
        """
        appt = await self.db.scalar(
            select(Appointment).where(Appointment.id == appointment_id).with_for_update()
        )
        if not appt:
            raise AppointmentServiceError(f"Appointment {appointment_id} not found.")

        if appt.status not in (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED):
            raise AppointmentServiceError(
                f"Only active appointments can be cancelled. Current status: {appt.status.value}."
            )

        slot = await self.db.scalar(
            select(Slot).where(Slot.id == appt.slot_id).with_for_update()
        )
        if slot:
            now_slot = datetime.now(slot.start_time.tzinfo) if slot.start_time.tzinfo else datetime.utcnow()
            hours_until = (slot.start_time - now_slot).total_seconds() / 3600
            if hours_until < settings.RESCHEDULE_CANCEL_CUTOFF_HOURS:
                raise AppointmentServiceError(
                    f"Appointments less than {settings.RESCHEDULE_CANCEL_CUTOFF_HOURS} hours away cannot be cancelled online. Please contact front desk."
                )
            slot.status = SlotStatus.AVAILABLE
            slot.reserved_until = None

        appt.status = AppointmentStatus.CANCELLED

        convo = await self.db.get(Conversation, conversation_id)
        if not convo:
            convo = Conversation(
                id=conversation_id,
                channel=ChannelType.CHAT,
                current_state=ConversationState.BOOKED,
                confirmation_status=ConfirmationStatusType.PENDING,
            )
            self.db.add(convo)
            await self.db.flush()

        cancellation_log = AppointmentCancellation(
            id=uuid.uuid4(),
            appointment_id=appointment_id,
            conversation_id=conversation_id,
            reason=reason,
        )
        self.db.add(cancellation_log)

        await self.db.flush()
        await self.db.refresh(appt)
        await self.db.refresh(cancellation_log)

        return appt, cancellation_log
