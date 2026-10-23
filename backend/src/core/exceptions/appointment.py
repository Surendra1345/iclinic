"""Errors raised while booking, rescheduling or cancelling appointments."""
from src.core.exceptions.base import ClinicError


class AppointmentServiceError(ClinicError):
    """An appointment operation could not be completed (wrong status, cutoff passed, slot booked...)."""


class SlotUnavailableError(ClinicError, ValueError):
    """Raised when a slot selected from stale availability is no longer free."""
