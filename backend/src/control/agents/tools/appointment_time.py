"""Appointment time formatting for patient-facing messages."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CLINIC_TIMEZONE = ZoneInfo("Asia/Kolkata")


def format_appointment_time(value: datetime) -> str:
    """Format a stored appointment timestamp in the clinic's local timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local_time = value.astimezone(CLINIC_TIMEZONE)
    return local_time.strftime("%A, %B %d at %I:%M %p")
