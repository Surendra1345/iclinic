import asyncio
import uuid
from datetime import date
# pyrefly: ignore[missing-import]
from sqlalchemy import text
from src.data.clients.postgres import AsyncSessionLocal
from src.control.agents.graph import agent_graph


async def test_reschedule_flow():
    convo_id = str(uuid.uuid4())
    session_id = f"test_resched_{convo_id[:8]}"

    async with AsyncSessionLocal() as db:
        # Check Hemanth in DB
        res = await db.execute(text("SELECT id, full_name, phone, email, date_of_birth FROM patients WHERE full_name ILIKE 'Hemanth'"))
        hemanth = res.first()
        print("Existing Hemanth in DB:", hemanth)

        # 1. Start conversation: "HI"
        state = {
            "conversation_id": convo_id,
            "patient_phone": "+918919545828",
            "channel": "chat",
            "messages": [],
            "latest_user_speech": "HI",
        }
        out = await agent_graph.ainvoke(state, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 1 (HI) ->", out.get("latest_agent_speech"))

        # 2. "i am new patient"
        out["latest_user_speech"] = "i am new patient"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 2 (i am new patient) ->", out.get("latest_agent_speech"))

        # 3. "Hemanth"
        out["latest_user_speech"] = "Hemanth"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 3 (Hemanth) ->", out.get("latest_agent_speech"))

        # 4. "17-7-2004"
        out["latest_user_speech"] = "17-7-2004"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 4 (17-7-2004) ->", out.get("latest_agent_speech"))

        # 5. "hemanth@gmail.com"
        out["latest_user_speech"] = "hemanth@gmail.com"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 5 (hemanth@gmail.com) ->", out.get("latest_agent_speech"))

        # 6. "8919545828"
        out["latest_user_speech"] = "8919545828"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 6 (8919545828) ->", out.get("latest_agent_speech"))

        # 7. "i want reschedule it"
        out["latest_user_speech"] = "i want reschedule it"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 7 (i want reschedule it) ->", out.get("latest_agent_speech"))

        # 8. "alterantive slot"
        out["latest_user_speech"] = "alterantive slot"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 8 (alterantive slot) ->", out.get("latest_agent_speech"))

        # 9. "book it"
        out["latest_user_speech"] = "book it"
        out = await agent_graph.ainvoke(out, config={"configurable": {"db": db, "thread_id": session_id}})
        print("\nTurn 9 (book it) ->", out.get("latest_agent_speech"))


if __name__ == "__main__":
    asyncio.run(test_reschedule_flow())
