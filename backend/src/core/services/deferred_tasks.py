"""Work that should start only after a conversation turn has been saved, without making the patient wait.

A node calls `defer(job)` while the turn is running. The turn service launches the queued jobs once
the turn is committed, so a job never sees half-saved data. When no turn is collecting (for example in
a script or test), `defer` returns False and the caller does the work inline instead.
"""
import asyncio
import logging
from contextvars import ContextVar
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)

Job = Callable[[], Awaitable[None]]

_collector: ContextVar[Optional[List[Job]]] = ContextVar("deferred_jobs", default=None)
_running: set = set()   # keeps task references alive until they finish


def begin() -> List[Job]:
    """Start collecting deferred jobs for the current turn."""
    jobs: List[Job] = []
    _collector.set(jobs)
    return jobs


def defer(job: Job) -> bool:
    """Queue a job for after the turn is saved. False means nobody is collecting; run it inline."""
    jobs = _collector.get()
    if jobs is None:
        return False
    jobs.append(job)
    return True


def reset() -> None:
    """Stop collecting (end of turn)."""
    _collector.set(None)


def launch(jobs: List[Job]) -> None:
    """Run the queued jobs in the background; a failure is logged and never reaches the patient."""
    for job in jobs:
        task = asyncio.create_task(_run(job))
        _running.add(task)
        task.add_done_callback(_running.discard)


async def _run(job: Job) -> None:
    try:
        await job()
    except Exception:
        logger.exception("Deferred job failed")
