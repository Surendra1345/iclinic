"""Background scheduler — periodically frees expired slot reservations."""
import asyncio
import logging
import time
from typing import Optional

from src.data.clients.postgres import AsyncSessionLocal
from src.data.repositories.slot_repository import SlotRepository
from src.observability.metrics import (
    scheduler_last_run_timestamp,
    scheduler_released_slots_total,
)

logger = logging.getLogger(__name__)

_cleanup_task: Optional[asyncio.Task] = None
_running: bool = False


def is_scheduler_running() -> bool:
    return _running and _cleanup_task is not None and not _cleanup_task.done()


async def _reservation_cleanup_loop(interval_seconds: int = 60):
    global _running
    while _running:
        try:
            scheduler_last_run_timestamp.set(time.time())
            async with AsyncSessionLocal() as session:
                repo = SlotRepository(session)
                released_count = await repo.cleanup_expired_reservations()
                await session.commit()
                if released_count > 0:
                    logger.info(f"Released {released_count} expired slot reservations.")
                    scheduler_released_slots_total.inc(released_count)
                else:
                    logger.debug("Scheduler cleanup completed; no expired reservations found.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Error during slot reservation cleanup: %s", e)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break


async def start_scheduler():
    """Start background scheduler tasks on app startup."""
    global _cleanup_task, _running
    if not _running:
        _running = True
        _cleanup_task = asyncio.create_task(_reservation_cleanup_loop())
        logger.info("Slot reservation cleanup scheduler started interval_seconds=60")


async def stop_scheduler():
    """Cancel background scheduler tasks on app shutdown."""
    global _cleanup_task, _running
    _running = False
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None
        logger.info("Slot reservation cleanup scheduler stopped.")
