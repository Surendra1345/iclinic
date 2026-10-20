import asyncio
from src.data.clients.postgres import AsyncSessionLocal
from sqlalchemy import select
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.slot import Slot
from src.data.models.postgres.patient import Patient
from src.data.models.postgres.provider import Provider
from src.data.models.postgres.location import Location

async def check():
    async with AsyncSessionLocal() as db:
        p = (await db.execute(select(Patient).where(Patient.phone == '+916303023283'))).scalar_one_or_none()
        print('Patient:', p.full_name if p else None, p.id if p else None)
        if p:
            appts = (await db.execute(select(Appointment).where(Appointment.patient_id == p.id))).scalars().all()
            for a in appts:
                s = (await db.execute(select(Slot).where(Slot.id == a.slot_id))).scalar_one_or_none()
                d = (await db.execute(select(Provider).where(Provider.id == s.provider_id))).scalar_one_or_none() if s else None
                print(f'Appt: {a.id}, Status: {a.status}, Doctor: {d.full_name if d else None}, Slot: {s.start_time if s else None}')
        
        # Check available slots
        slots = (await db.execute(select(Slot).where(Slot.status == 'available').order_by(Slot.start_time).limit(10))).scalars().all()
        print('\nAvailable slots:')
        for sl in slots:
            doc = (await db.execute(select(Provider).where(Provider.id == sl.provider_id))).scalar_one_or_none()
            loc = (await db.execute(select(Location).where(Location.id == sl.location_id))).scalar_one_or_none()
            print(f'Slot {sl.id}: {sl.start_time} with {doc.full_name if doc else None} at {loc.name if loc else None}')

if __name__ == '__main__':
    asyncio.run(check())
