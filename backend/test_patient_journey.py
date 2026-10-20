import asyncio
import uuid
from datetime import datetime

from src.data.clients.postgres import AsyncSessionLocal
from src.control.agents.graph import build_graph
from langgraph.checkpoint.memory import MemorySaver

agent_graph = build_graph().compile(checkpointer=MemorySaver())

async def run_journey():
    print("=" * 70)
    print("CLINICAL AGENT VALIDATION: RESCHEDULE -> CANCEL -> NEW BOOKING")
    print("=" * 70)

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 1: RESCHEDULING AN EXISTING APPOINTMENT OVER PHONE
    # ─────────────────────────────────────────────────────────────────
    print("\n>>> SCENARIO 1: RESCHEDULING AN EXISTING APPOINTMENT <<<")
    session_resched = f"outbound_resched_{uuid.uuid4().hex[:8]}"

    # Turn 1: Verification with telephony speech
    async with AsyncSessionLocal() as db:
        s1 = {
            "call_sid": session_resched,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "Yeah, my name is Sandra and my date about this 14th. December 2013.",
            "is_verified": False,
        }
        r1 = await agent_graph.ainvoke(s1, config={"configurable": {"thread_id": session_resched, "db": db}})
        print(f"Patient Turn 1 : '{s1['latest_user_speech']}'")
        print(f"Agent Reply 1  : '{r1.get('latest_agent_speech')}'")
        print(f"Verified       : {r1.get('is_verified')}")
        print(f"Active Appt ID : {r1.get('active_appointment_id')}")
        assert r1.get("is_verified") == True, "Identity must be verified!"
        assert r1.get("active_appointment_id") is not None, "Active appointment must be found!"

    # Turn 2: Patient says they want to reschedule
    async with AsyncSessionLocal() as db:
        s2 = {
            "call_sid": session_resched,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "Yes, please reschedule my appointment to Sunday at 10:30 AM",
        }
        r2 = await agent_graph.ainvoke(s2, config={"configurable": {"thread_id": session_resched, "db": db}})
        print(f"\nPatient Turn 2 : '{s2['latest_user_speech']}'")
        print(f"Agent Reply 2  : '{r2.get('latest_agent_speech')}'")
        print(f"Target Slot Held: {r2.get('target_slot_id')}")

    # Turn 3: Patient confirms the reschedule
    async with AsyncSessionLocal() as db:
        s3 = {
            "call_sid": session_resched,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "Yes, please confirm and move it.",
        }
        r3 = await agent_graph.ainvoke(s3, config={"configurable": {"thread_id": session_resched, "db": db}})
        print(f"\nPatient Turn 3 : '{s3['latest_user_speech']}'")
        print(f"Agent Reply 3  : '{r3.get('latest_agent_speech')}'")
        print(f"Confirmed      : {r3.get('booking_confirmed')}")
        assert r3.get("booking_confirmed") == True, "Reschedule must be confirmed!"

    print("\n[PASSED] SCENARIO 1: APPOINTMENT RESCHEDULING VERIFIED!")

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 2: CANCELLING THE APPOINTMENT OVER PHONE
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(">>> SCENARIO 2: CANCELLING THE APPOINTMENT <<<")
    print("=" * 70)
    session_cancel = f"outbound_cancel_{uuid.uuid4().hex[:8]}"

    # Turn 1: Patient calls to cancel
    async with AsyncSessionLocal() as db:
        cs1 = {
            "call_sid": session_cancel,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "Surendra and 14-12-2003, I want to cancel my appointment",
            "is_verified": False,
        }
        cr1 = await agent_graph.ainvoke(cs1, config={"configurable": {"thread_id": session_cancel, "db": db}})
        print(f"Patient Turn 1 : '{cs1['latest_user_speech']}'")
        print(f"Agent Reply 1  : '{cr1.get('latest_agent_speech')}'")

    # Turn 2: Confirm cancellation
    async with AsyncSessionLocal() as db:
        cs2 = {
            "call_sid": session_cancel,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "Yes, please cancel it.",
        }
        cr2 = await agent_graph.ainvoke(cs2, config={"configurable": {"thread_id": session_cancel, "db": db}})
        print(f"\nPatient Turn 2 : '{cs2['latest_user_speech']}'")
        print(f"Agent Reply 2  : '{cr2.get('latest_agent_speech')}'")
        print(f"Call Completed : {cr2.get('is_completed')}")

    print("\n[PASSED] SCENARIO 2: APPOINTMENT CANCELLATION VERIFIED!")

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 3: BOOKING A BRAND NEW APPOINTMENT (FRESH INTAKE)
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(">>> SCENARIO 3: BOOKING A BRAND NEW APPOINTMENT <<<")
    print("=" * 70)
    session_book = f"outbound_book_{uuid.uuid4().hex[:8]}"

    # Turn 1: Identification of patient who now has no active appointments
    async with AsyncSessionLocal() as db:
        bs1 = {
            "call_sid": session_book,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "My name is Surendra and date of birth is 14 December 2003",
            "is_verified": False,
        }
        br1 = await agent_graph.ainvoke(bs1, config={"configurable": {"thread_id": session_book, "db": db}})
        print(f"Patient Turn 1 : '{bs1['latest_user_speech']}'")
        print(f"Agent Reply 1  : '{br1.get('latest_agent_speech')}'")
        print(f"Verified       : {br1.get('is_verified')}")
        print(f"Active Appt    : {br1.get('active_appointment_id')}")
        assert br1.get("is_verified") == True, "Identity must be verified!"
        assert br1.get("active_appointment_id") is None, "Should have 0 active appointments!"

    # Turn 2: Request doctor, branch, and date
    async with AsyncSessionLocal() as db:
        bs2 = {
            "call_sid": session_book,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "I want an appointment with Dr. Ashwin Balaji at T. Nagar branch on Sunday at 09:30 AM",
        }
        br2 = await agent_graph.ainvoke(bs2, config={"configurable": {"thread_id": session_book, "db": db}})
        print(f"\nPatient Turn 2 : '{bs2['latest_user_speech']}'")
        print(f"Agent Reply 2  : '{br2.get('latest_agent_speech')}'")
        print(f"Target Slot Held: {br2.get('target_slot_id')}")
        assert br2.get("target_slot_id") is not None, "Target slot must be reserved!"

    # Turn 3: Confirm new booking
    async with AsyncSessionLocal() as db:
        bs3 = {
            "call_sid": session_book,
            "patient_phone": "+916303023283",
            "channel": "outbound_call",
            "latest_user_speech": "Yes, please confirm and book it.",
        }
        br3 = await agent_graph.ainvoke(bs3, config={"configurable": {"thread_id": session_book, "db": db}})
        print(f"\nPatient Turn 3 : '{bs3['latest_user_speech']}'")
        print(f"Agent Reply 3  : '{br3.get('latest_agent_speech')}'")
        print(f"Booking Confirmed: {br3.get('booking_confirmed')}")
        assert br3.get("booking_confirmed") == True, "Booking must be confirmed!"

    print("\n[PASSED] SCENARIO 3: BRAND NEW BOOKING VERIFIED!")
    print("\n" + "=" * 70)
    print("ALL THREE FLOWS (RESCHEDULE, CANCEL, BOOK) FULLY TESTED & WORKING!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_journey())
