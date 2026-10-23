"""LangGraph compiled agent graph."""
from typing import Any, Callable, Dict
from sqlalchemy.engine import make_url
# pyrefly: ignore[missing-import]
from langchain_core.runnables import RunnableConfig
# pyrefly: ignore[missing-import]
from langgraph.checkpoint.memory import MemorySaver
# pyrefly: ignore[missing-import]
from langgraph.graph import END, START, StateGraph

from src.control.agents.edges import (
    route_after_action,
    route_after_identity,
    route_after_intent,
    route_after_register,
    route_after_start,
)
from src.control.agents.nodes import (
    booking_agent_node,
    cancel_agent_node,
    detect_intent_node,
    end_call_node,
    faq_agent_node,
    greet_patient_node,
    handoff_to_front_desk_node,
    identity_agent_node,
    register_patient_node,
    reschedule_agent_node,
    send_confirmation_node,
    start_conversation_node,
)
from src.control.agents.state import CallState


def _wrap_with_db(node_fn: Callable) -> Callable:
    """Injects the request-scoped database session from RunnableConfig into the node."""
    async def wrapped(state: CallState, config: RunnableConfig) -> Dict[str, Any]:
        db = config.get("configurable", {}).get("db")
        return await node_fn(state, db)
    return wrapped


def build_graph() -> StateGraph:
    builder = StateGraph(CallState)

    # ?????? Register Nodes ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
    builder.add_node("start", _wrap_with_db(start_conversation_node))
    builder.add_node("greet", _wrap_with_db(greet_patient_node))
    builder.add_node("identity", _wrap_with_db(identity_agent_node))
    builder.add_node("register", _wrap_with_db(register_patient_node))
    builder.add_node("detect_intent", _wrap_with_db(detect_intent_node))
    builder.add_node("faq", _wrap_with_db(faq_agent_node))
    builder.add_node("booking", _wrap_with_db(booking_agent_node))
    builder.add_node("reschedule", _wrap_with_db(reschedule_agent_node))
    builder.add_node("cancel", _wrap_with_db(cancel_agent_node))
    builder.add_node("confirmation", _wrap_with_db(send_confirmation_node))
    builder.add_node("handoff", _wrap_with_db(handoff_to_front_desk_node))
    builder.add_node("end_call", _wrap_with_db(end_call_node))

    # ?????? Wire Edges ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
    # START -> start
    builder.add_edge(START, "start")

    # Start routes explicit handoff and existing-patient corrections before registration.
    builder.add_conditional_edges(
        "start",
        route_after_start,
        {
            "detect_intent": "detect_intent",
            "register": "register",
            "identity": "identity",
            "greet": "greet",
            "handoff": "handoff",
        },
    )

    # After greet -> END (speaks greeting and waits for patient input)
    builder.add_edge("greet", END)

    # Identity -> [handoff, register, END]
    builder.add_conditional_edges(
        "identity",
        route_after_identity,
        {
            "handoff": "handoff",
            "register": "register",
            END: END,
        },
    )


    # Register -> [handoff, detect_intent, END]
    builder.add_conditional_edges(
        "register",
        route_after_register,
        {
            "handoff": "handoff",
            "detect_intent": "detect_intent",
            END: END,
        },
    )

    # Intent -> [handoff, faq, booking, reschedule, cancel, register, greet, identity, end_call, END]
    builder.add_conditional_edges(
        "detect_intent",
        route_after_intent,
        {
            "handoff": "handoff",
            "booking": "booking",
            "reschedule": "reschedule",
            "cancel": "cancel",
            "register": "register",
            "greet": "greet",
            "identity": "identity",
            "faq": "faq",
            "end_call": "end_call",
            END: END,
        },
    )

    # FAQ -> END (answer is already in latest_agent_speech)
    builder.add_edge("faq", END)

    # Booking -> [handoff, confirmation, END]
    builder.add_conditional_edges(
        "booking",
        route_after_action,
        {
            "handoff": "handoff",
            "confirmation": "confirmation",
            END: END,
        },
    )

    # Reschedule -> [handoff, confirmation, END]
    builder.add_conditional_edges(
        "reschedule",
        route_after_action,
        {
            "handoff": "handoff",
            "confirmation": "confirmation",
            END: END,
        },
    )

    # Cancel -> [handoff, confirmation, END]
    builder.add_conditional_edges(
        "cancel",
        route_after_action,
        {
            "handoff": "handoff",
            "confirmation": "confirmation",
            END: END,
        },
    )

    # Confirmation -> end_call
    builder.add_edge("confirmation", "end_call")

    # Terminal nodes
    builder.add_edge("handoff", END)
    builder.add_edge("end_call", END)

    return builder


# Global checkpointer and compiled graph instance
checkpointer: Any = MemorySaver()
agent_graph = build_graph().compile(checkpointer=checkpointer)
_checkpoint_pool: Any = None


def get_agent_graph():
    """Return the active graph (PostgreSQL-backed after app startup)."""
    return agent_graph


async def initialize_persistent_checkpointer(database_url: str) -> None:
    """Use PostgreSQL for LangGraph checkpoints so active threads survive restarts."""
    global agent_graph, checkpointer, _checkpoint_pool
    if _checkpoint_pool is not None:
        return

    # LangGraph's Postgres saver uses psycopg; the application ORM uses asyncpg.
    from psycopg_pool import AsyncConnectionPool
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    connection_url = make_url(database_url).set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    pool = AsyncConnectionPool(
        conninfo=connection_url,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    checkpointer = saver
    agent_graph = build_graph().compile(checkpointer=saver)
    _checkpoint_pool = pool


async def close_persistent_checkpointer() -> None:
    global _checkpoint_pool
    if _checkpoint_pool is not None:
        await _checkpoint_pool.close()
        _checkpoint_pool = None

