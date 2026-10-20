import asyncio
import uuid
from src.data.clients.postgres import AsyncSessionLocal
from sqlalchemy import select
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.slot import Slot
from src.data.models.postgres.patient import Patient
from src.constants.enums import AppointmentStatus, SlotStatus

async def reset():
    async with AsyncSessionLocal() as db:
        # Surendra's appointment ID
        appt_id = uuid.UUID('0a923b14-4a94-4aae-8794-df2212dfa889')
        slot_930am_id = uuid.UUID('cf59f612-3742-4dfb-9a1b-ad3a39aa5ff4') # 09:30 AM IST
        slot_1030am_id = uuid.UUID('7bd69ba1-56d0-4f35-a997-b48b5689a56e') # 10:30 AM IST

        appt = await db.get(Appointment, appt_id)
        slot_930 = await db.get(Slot, slot_930am_id)
        slot_1030 = await db.get(Slot, slot_1030am_id)

        # Free 10:30 slot
        slot_1030.status = SlotStatus.AVAILABLE
        slot_1030.reserved_until = None

        # Book 9:30 slot
        slot_930.status = SlotStatus.BOOKED
        slot_930.reserved_until = None

        # Reset appointment to 9:30 slot
        appt.status = AppointmentStatus.BOOKED
        appt.slot_id = slot_930am_id

        await db.commit()
        print('Reset complete! Surendra booked at Sunday 09:30 AM IST, Sunday 10:30 AM IST is available.')

if __name__ == '__main__':
    asyncio.run(reset())
