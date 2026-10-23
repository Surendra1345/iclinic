"""Slot repository — query available slots and manage reservations."""
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Optional

# pyrefly: ignore[missing-import]
from sqlalchemy import Time, select, update, and_, func
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore[missing-import]
from sqlalchemy.orm import selectinload

from src.constants.enums import SlotStatus
from src.config.settings import settings
from src.data.models.postgres.slot import Slot


class SlotUnavailableError(ValueError):
    """Raised when a slot selected from stale availability is no longer free."""


class SlotRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_available_slots(self, limit: int = 5) -> list[Slot]:
        """Return next N available future slots ordered by start_time."""
        from src.data.models.postgres.provider import Provider
        result = await self.db.scalars(
            select(Slot)
            .options(selectinload(Slot.provider).selectinload(Provider.location))
            .where(Slot.status == SlotStatus.AVAILABLE, Slot.start_time > datetime.utcnow())
            .order_by(Slot.start_time)
            .limit(limit)
        )
        return list(result.all())

    async def get_slots_by_specialty(self, specialty: str, limit: int = 5) -> list[Slot]:
        """Slots filtered by provider specialty (future only)."""
        from src.data.models.postgres.provider import Provider
        result = await self.db.scalars(
            select(Slot)
            .options(selectinload(Slot.provider).selectinload(Provider.location))
            .join(Slot.provider)
            .where(
                Slot.status == SlotStatus.AVAILABLE,
                Slot.start_time > datetime.utcnow(),
                Provider.specialty.ilike(f"%{specialty}%"),
                Provider.is_active == True,
            )
            .order_by(Slot.start_time)
            .limit(limit)
        )
        return list(result.all())

    async def get_slots_by_doctor_name(self, doctor_name: str, limit: int = 5) -> list[Slot]:
        """Slots for a provider whose name matches (case-insensitive fuzzy)."""
        from src.data.models.postgres.provider import Provider
        result = await self.db.scalars(
            select(Slot)
            .options(selectinload(Slot.provider).selectinload(Provider.location))
            .join(Slot.provider)
            .where(
                Slot.status == SlotStatus.AVAILABLE,
                Slot.start_time > datetime.utcnow(),
                Provider.full_name.ilike(f"%{doctor_name}%"),
                Provider.is_active == True,
            )
            .order_by(Slot.start_time)
            .limit(limit)
        )
        return list(result.all())

    async def get_slots_by_location(self, location_name: str, limit: int = 5) -> list[Slot]:
        """Slots filtered by location name."""
        from src.data.models.postgres.provider import Provider
        from src.data.models.postgres.location import Location
        result = await self.db.scalars(
            select(Slot)
            .options(selectinload(Slot.provider).selectinload(Provider.location))
            .join(Slot.provider)
            .join(Provider.location)
            .where(
                Slot.status == SlotStatus.AVAILABLE,
                Slot.start_time > datetime.utcnow(),
                Location.name.ilike(f"%{location_name}%"),
                Provider.is_active == True,
            )
            .order_by(Slot.start_time)
            .limit(limit)
        )
        return list(result.all())

    async def get_slots_by_specialty_and_location(self, specialty: str, location_name: str, limit: int = 5) -> list[Slot]:
        """Slots filtered by both specialty and location name."""
        from src.data.models.postgres.provider import Provider
        from src.data.models.postgres.location import Location
        result = await self.db.scalars(
            select(Slot)
            .options(selectinload(Slot.provider).selectinload(Provider.location))
            .join(Slot.provider)
            .join(Provider.location)
            .where(
                Slot.status == SlotStatus.AVAILABLE,
                Slot.start_time > datetime.utcnow(),
                Provider.specialty.ilike(f"%{specialty}%"),
                Location.name.ilike(f"%{location_name}%"),
                Provider.is_active == True,
            )
            .order_by(Slot.start_time)
            .limit(limit)
        )
        return list(result.all())

    async def get_slots_by_datetime_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 5,
    ) -> list[Slot]:
        """Slots within a datetime window (future only)."""
        now = datetime.utcnow()
        result = await self.db.scalars(
            select(Slot)
            .where(
                Slot.status == SlotStatus.AVAILABLE,
                Slot.start_time >= max(start, now),
                Slot.start_time <= end,
            )
            .order_by(Slot.start_time)
            .limit(limit)
        )
        return list(result.all())

    async def get_slots_by_criteria(
        self,
        *,
        start_time_gte: Optional[datetime] = None,
        start_time_lte: Optional[datetime] = None,
        specialty: Optional[str] = None,
        location_name: Optional[str] = None,
        doctor_name: Optional[str] = None,
        clinic_time_gte: Optional[time] = None,
        clinic_time_lte: Optional[time] = None,
        limit: int = 5,
    ) -> list[Slot]:
        """Query available slots filtered by date range, specialty, location, and doctor."""
        from src.data.models.postgres.provider import Provider
        from src.data.models.postgres.location import Location
        now = datetime.now(timezone.utc)
        stmt = (
            select(Slot)
            .options(selectinload(Slot.provider).selectinload(Provider.location))
            .join(Slot.provider)
            .join(Provider.location)
            .where(Slot.status == SlotStatus.AVAILABLE, Provider.is_active == True)
        )
        if start_time_gte:
            if start_time_gte.tzinfo is None:
                start_time_gte = start_time_gte.replace(tzinfo=timezone.utc)
            stmt = stmt.where(Slot.start_time >= max(start_time_gte, now))
        else:
            stmt = stmt.where(Slot.start_time > now)
        if start_time_lte:
            if start_time_lte.tzinfo is None:
                start_time_lte = start_time_lte.replace(tzinfo=timezone.utc)
            stmt = stmt.where(Slot.start_time <= start_time_lte)
        if specialty:
            stmt = stmt.where(Provider.specialty.ilike(f"%{specialty}%"))
        if location_name:
            stmt = stmt.where(Location.name.ilike(f"%{location_name}%"))
        if doctor_name:
            stmt = stmt.where(Provider.full_name.ilike(f"%{doctor_name}%"))

        # Appointment times are stored in UTC. Filter requested clock times in
        # the clinic timezone in SQL so no out-of-range slot can be offered by
        # a later in-memory fallback.
        if clinic_time_gte or clinic_time_lte:
            local_time = func.timezone("Asia/Kolkata", Slot.start_time).cast(Time)
            if clinic_time_gte:
                stmt = stmt.where(local_time >= clinic_time_gte)
            if clinic_time_lte:
                stmt = stmt.where(local_time <= clinic_time_lte)

        stmt = stmt.order_by(Slot.start_time).limit(limit)
        result = await self.db.scalars(stmt)
        return list(result.all())

    async def get_slot_by_id(self, slot_id: uuid.UUID) -> Optional[Slot]:
        return await self.db.get(Slot, slot_id)

    # ── Mutations ─────────────────────────────────────────────────────────────

    async def reserve_slot(self, slot_id: uuid.UUID, patient_id: Optional[uuid.UUID] = None) -> Slot:
        """
        Mark slot as RESERVED (with FOR UPDATE lock).
        Raises ValueError if slot is not available.
        """
        result = await self.db.scalars(
            select(Slot).where(Slot.id == slot_id).with_for_update()
        )
        slot = result.one_or_none()
        if not slot:
            raise SlotUnavailableError(f"Slot {slot_id} not found")
        if slot.status != SlotStatus.AVAILABLE:
            raise SlotUnavailableError(f"Slot {slot_id} is no longer available (status={slot.status})")

        slot.status = SlotStatus.RESERVED
        slot.reserved_until = datetime.utcnow() + timedelta(
            minutes=settings.SLOT_RESERVATION_TIMEOUT_MINUTES
        )
        await self.db.flush()
        await self.db.refresh(slot)
        return slot

    async def release_slot(self, slot_id: uuid.UUID) -> None:
        """Release a reserved slot back to AVAILABLE."""
        await self.db.execute(
            update(Slot)
            .where(Slot.id == slot_id)
            .values(status=SlotStatus.AVAILABLE, reserved_until=None)
        )
        await self.db.flush()

    async def mark_slot_booked(self, slot_id: uuid.UUID) -> None:
        """Mark slot as BOOKED (called inside reschedule/book transaction)."""
        await self.db.execute(
            update(Slot)
            .where(Slot.id == slot_id)
            .values(status=SlotStatus.BOOKED, reserved_until=None)
        )
        await self.db.flush()

    async def cleanup_expired_reservations(self) -> int:
        """
        Release all slots whose reserved_until has passed.
        Called by background scheduler every 60 seconds.
        Returns number of slots released.
        """
        result = await self.db.execute(
            update(Slot)
            .where(
                and_(
                    Slot.status == SlotStatus.RESERVED,
                    Slot.reserved_until < datetime.utcnow(),
                )
            )
            .values(status=SlotStatus.AVAILABLE, reserved_until=None)
            .returning(Slot.id)
        )
        await self.db.flush()
        rows = result.fetchall()
        return len(rows)

    # ── Reservation timer helpers ─────────────────────────────────────────────

    def seconds_until_expiry(self, slot: Slot) -> Optional[float]:
        """Return seconds remaining on a reservation, or None if not reserved."""
        if slot.reserved_until is None:
            return None
        delta = slot.reserved_until - datetime.utcnow()
        return max(delta.total_seconds(), 0)
