import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath("."))
import uuid
import httpx
from sqlalchemy import select
from src.data.clients.postgres import AsyncSessionLocal
from src.data.models.postgres.notification import Notification
from src.data.models.postgres.appointment import Appointment
from src.data.models.postgres.slot import Slot
from src.constants.enums import SlotStatus, AppointmentStatus

async def main():
    session_id = f"test_email_{uuid.uuid4().hex[:8]}"
    print(f"=== Testing Multi-Turn Booking with Patient Email for session: {session_id} ===")

    # First clean up any booked slots for Arjun on 20 Oct so slot is available
    async with AsyncSessionLocal() as session:
        # Check active appointments for test phone
        pass

    test_phone = f"+91987{uuid.uuid4().int % 10000000:07d}"
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30.0) as client:
        # Turn 1: Ask for slot
        r1 = await client.post("/api/chat", json={
            "session_id": session_id,
            "message": "I want an appointment with Dr. Priya Nair at T. Nagar on 25 Oct",
            "patient_phone": test_phone,
            "patient_name": "Surendra Patient",
        })
        print("\n--- Turn 1 Response ---")
        data1 = r1.json()
        print("Reply:", data1.get("reply"))
        print("Target Slot:", data1.get("target_slot"))

        # Turn 2: Confirm slot without email
        r2 = await client.post("/api/chat", json={
            "session_id": session_id,
            "message": "Yes, please confirm",
            "patient_phone": test_phone,
            "patient_name": "Test Patient",
        })
        print("\n--- Turn 2 Response (should ask for email) ---")
        data2 = r2.json()
        print("Reply:", data2.get("reply"))

        # Turn 3: Provide email
        test_patient_email = "patient.recipient.test@gmail.com"
        r3 = await client.post("/api/chat", json={
            "session_id": session_id,
            "message": f"my email is {test_patient_email}",
            "patient_phone": test_phone,
            "patient_name": "Test Patient",
        })
        print("\n--- Turn 3 Response (should confirm and deliver email) ---")
        data3 = r3.json()
        print("Reply:", data3.get("reply"))
        print("Is Completed:", data3.get("is_completed"))
        print("Booking Confirmed:", data3.get("booking_confirmed"))

    # Now verify database notifications table
    async with AsyncSessionLocal() as session:
        stmt = select(Notification).order_by(Notification.created_at.desc()).limit(5)
        res = await session.execute(stmt)
        notifs = res.scalars().all()
        print("\n--- Latest Notifications in DB ---")
        for n in notifs:
            print(f"ID: {n.id} | Channel: {n.channel} | Recipient: {n.recipient} | Status: {n.status} | Created: {n.created_at}")

if __name__ == "__main__":
    asyncio.run(main())
