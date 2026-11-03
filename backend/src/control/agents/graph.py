"""LangGraph compiled agent graph."""
from typing import Any, Callable, Dict
from sqlalchemy.engine import make_url
# pyrefly: ignore[missing-import]
from langchain_core.runnables import RunnableConfig
# pyrefly: ignore[missing-import]
from langgraph.checkpoint.memory import MemorySaver
# pyrefly: ignore[missing-import]
from langgraph.graph import END, START, StateGraph

from src.control.agents.nodes import agent_node, gate_node
from src.control.agents.state import CallState
from src.control.agents.tools.clinic_directory import ensure_directory


def _wrap_with_db(node_fn: Callable) -> Callable:
    """Injects the request-scoped database session from RunnableConfig into the node."""
    async def wrapped(state: CallState, config: RunnableConfig) -> Dict[str, Any]:
        db = config.get("configurable", {}).get("db")
        await ensure_directory(db)  # read-only refresh of branch/doctor names
        return await node_fn(state, db)
    return wrapped


def build_graph() -> StateGraph:
    """gate -> agent (one model that calls tools and writes the reply)."""
    builder = StateGraph(CallState)
    builder.add_node("gate", _wrap_with_db(gate_node))
    builder.add_node("agent", _wrap_with_db(agent_node))
    builder.add_edge(START, "gate")
    builder.add_edge("gate", "agent")
    builder.add_edge("agent", END)
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

