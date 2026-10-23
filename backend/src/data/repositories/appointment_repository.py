"""Appointment repository — create, query, and update appointments."""
import uuid
from datetime import datetime, timedelta
from typing import Optional

# pyrefly: ignore[missing-import]
from sqlalchemy import select, update
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore[missing-import]
from sqlalchemy.orm import selectinload

from src.constants.enums import AppointmentStatus, ChannelType
from src.config.settings import settings
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.appointment_cancellation import AppointmentCancellation
from src.data.models.postgres.appointment_reschedule import AppointmentReschedule
from src.data.models.postgres.provider import Provider
from src.data.models.postgres.slot import Slot


class AppointmentRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_active_for_patient(self, patient_id: uuid.UUID) -> Optional[Appointment]:
        """Get the single active (booked or rescheduled) appointment for a patient."""
        result = await self.db.scalars(
            select(Appointment)
            .options(
                selectinload(Appointment.slot)
                .selectinload(Slot.provider)
                .selectinload(Provider.location)
            )
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED]),
            )
            .order_by(Appointment.created_at.desc())
        )
        return result.first()

    async def get_all_active_for_patient(self, patient_id: uuid.UUID) -> list[Appointment]:
        """All active appointments for the patient (for disambiguation)."""
        result = await self.db.scalars(
            select(Appointment)
            .options(
                selectinload(Appointment.slot)
                .selectinload(Slot.provider)
                .selectinload(Provider.location)
            )
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED]),
            )
            .order_by(Appointment.created_at.desc())
        )
        return list(result.all())

    async def get_recent_completed_for_patient(
        self, patient_id: uuid.UUID, *, limit: int = 5
    ) -> list[Appointment]:
        """Get completed visits with provider, branch, and appointment type for follow-up selection."""
        result = await self.db.scalars(
            select(Appointment)
            .options(
                selectinload(Appointment.slot)
                .selectinload(Slot.provider)
                .selectinload(Provider.location),
                selectinload(Appointment.appointment_type),
            )
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status == AppointmentStatus.COMPLETED,
            )
            .order_by(Appointment.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    async def get_by_id(self, appointment_id: uuid.UUID) -> Optional[Appointment]:
        result = await self.db.scalars(
            select(Appointment)
            .options(selectinload(Appointment.slot).selectinload(Slot.provider))
            .where(Appointment.id == appointment_id)
        )
        return result.one_or_none()

    # ── Mutations ─────────────────────────────────────────────────────────────

    async def create_appointment(
        self,
        *,
        patient_id: uuid.UUID,
        slot_id: uuid.UUID,
        appointment_type_id: uuid.UUID,
        conversation_id: uuid.UUID,
        channel: ChannelType = ChannelType.OUTBOUND_CALL,
        reason: Optional[str] = None,
    ) -> Appointment:
        """Insert a new booked appointment."""
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

    async def cancel_appointment(
        self,
        appointment_id: uuid.UUID,
        conversation_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> AppointmentCancellation:
        """
        Cancel an appointment:
        1. Update appointment status → CANCELLED
        2. Insert appointment_cancellations row
        Note: slot is freed in AppointmentService (atomic transaction).
        """
        await self.db.execute(
            update(Appointment)
            .where(Appointment.id == appointment_id)
            .values(status=AppointmentStatus.CANCELLED)
        )
        cancellation = AppointmentCancellation(
            id=uuid.uuid4(),
            appointment_id=appointment_id,
            conversation_id=conversation_id,
            reason=reason,
        )
        self.db.add(cancellation)
        await self.db.flush()
        await self.db.refresh(cancellation)
        return cancellation

    async def reschedule_appointment(
        self,
        *,
        old_appointment_id: uuid.UUID,
        new_appointment_id: uuid.UUID,
        conversation_id: uuid.UUID,
        reason: Optional[str] = None,
    ) -> AppointmentReschedule:
        """
        Record a reschedule:
        1. Update old appointment status → RESCHEDULED
        2. Insert appointment_reschedules row
        Note: slot swaps happen in AppointmentService (atomic transaction).
        """
        await self.db.execute(
            update(Appointment)
            .where(Appointment.id == old_appointment_id)
            .values(status=AppointmentStatus.RESCHEDULED)
        )
        record = AppointmentReschedule(
            id=uuid.uuid4(),
            old_appointment_id=old_appointment_id,
            new_appointment_id=new_appointment_id,
            conversation_id=conversation_id,
            reason=reason,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    # ── Business rules ────────────────────────────────────────────────────────

    def is_within_cutoff(self, appointment: Appointment, slot_start_time: datetime) -> bool:
        """
        Returns True if appointment is within the 24h cancel/reschedule cutoff.
        The slot start time must be passed in (loaded from the slot relation).
        """
        cutoff = timedelta(hours=settings.RESCHEDULE_CANCEL_CUTOFF_HOURS)
        return slot_start_time - datetime.utcnow() < cutoff
