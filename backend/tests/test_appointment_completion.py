"""Past appointments never block a new booking, and the front desk can mark one completed."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException

from src.api.rest.routes import dashboard
from src.control.agents.tools import booking_tools
from src.core.services import appointment_service


def test_looking_up_the_active_appointment_completes_a_passed_one_first(monkeypatch):
    order = []

    class Repo:
        def __init__(self, db):
            pass

        async def complete_past_for_patient(self, patient_id):
            order.append("complete_past")
            return 1

        async def get_active_for_patient(self, patient_id):
            order.append("get_active")
            return None

    monkeypatch.setattr(booking_tools, "AppointmentRepository", Repo)
    assert asyncio.run(booking_tools.check_patient_active_appointment(str(uuid.uuid4()), None)) is None
    assert order == ["complete_past", "get_active"]


def test_booking_completes_a_passed_appointment_before_the_one_active_check(monkeypatch):
    order = []

    class Repo:
        def __init__(self, db):
            pass

        async def complete_past_for_patient(self, patient_id):
            order.append("complete_past")
            return 1

    class Db:
        async def scalar(self, *_a, **_k):
            order.append("existing_check")
            return None   # nothing active any more, then the slot lookup finds nothing

    monkeypatch.setattr(appointment_service, "AppointmentRepository", Repo)
    service = appointment_service.AppointmentService(Db())
    with pytest.raises(appointment_service.AppointmentServiceError):
        asyncio.run(service.book_appointment_atomic(
            patient_id=uuid.uuid4(), slot_id=uuid.uuid4(), appointment_type_id=uuid.uuid4(), conversation_id=uuid.uuid4()))
    assert order[:2] == ["complete_past", "existing_check"]


@pytest.mark.parametrize("status", ["cancelled", "booked", "rescheduled", ""])
def test_the_front_desk_can_only_set_completed(status):
    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard.update_appointment_status(str(uuid.uuid4()), dashboard.UpdateAppointmentStatus(status=status)))
    assert error.value.status_code == 422


def test_a_malformed_appointment_id_is_rejected():
    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard.update_appointment_status("not-an-id", dashboard.UpdateAppointmentStatus(status="completed")))
    assert error.value.status_code == 422
