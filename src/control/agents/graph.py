"""LangGraph compiled agent graph."""
from typing import Any, Callable, Dict
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
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

    # ── Register Nodes ────────────────────────────────────────────────────────
    builder.add_node("start", _wrap_with_db(start_conversation_node))
    builder.add_node("greet", _wrap_with_db(greet_patient_node))
    builder.add_node("identity", _wrap_with_db(identity_agent_node))
    builder.add_node("register", _wrap_with_db(register_patient_node))
    builder.add_node("detect_intent", _wrap_with_db(detect_intent_node))
    builder.add_node("booking", _wrap_with_db(booking_agent_node))
    builder.add_node("reschedule", _wrap_with_db(reschedule_agent_node))
    builder.add_node("cancel", _wrap_with_db(cancel_agent_node))
    builder.add_node("confirmation", _wrap_with_db(send_confirmation_node))
    builder.add_node("handoff", _wrap_with_db(handoff_to_front_desk_node))
    builder.add_node("end_call", _wrap_with_db(end_call_node))

    # ── Wire Edges ────────────────────────────────────────────────────────────
    # START -> start
    builder.add_edge(START, "start")

    # Start -> [detect_intent (if verified), register (if new), greet (if verifying), handoff]
    builder.add_conditional_edges(
        "start",
        route_after_start,
        {
            "detect_intent": "detect_intent",
            "register": "register",
            "greet": "greet",
            "handoff": "handoff",
        },
    )

    # After greet -> identity
    builder.add_edge("greet", "identity")

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

    # Intent -> [handoff, booking, reschedule, cancel]
    builder.add_conditional_edges(
        "detect_intent",
        route_after_intent,
        {
            "handoff": "handoff",
            "booking": "booking",
            "reschedule": "reschedule",
            "cancel": "cancel",
        },
    )

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
checkpointer = MemorySaver()
agent_graph = build_graph().compile(checkpointer=checkpointer)
