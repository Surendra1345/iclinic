"""The tools the agent model can call, and the rules each one enforces.

The model decides which tool to call, in what order, and what to say. It cannot bypass the rules, because
they live here, inside the tools, and a tool that is not allowed simply refuses:

  * identity first: nothing about a patient's appointments works until name + date of birth matched
    (or the patient was registered); two failed checks hand the patient to the front desk
  * a slot can only be held if it was offered by a search in this conversation
  * a booking, change or cancellation is written only after a yes/no question was recorded with
    `request_confirmation` in the PREVIOUS turn, and the patient's own words in the current message contain
    the consent the model quotes
  * one active appointment per patient; changes inside the 24 hour cutoff go to the front desk

Every tool returns a small dict. Domain problems come back as `{"status": ...}` for the model to explain;
unexpected errors propagate so the whole turn is rolled back.
"""
import inspect
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import settings
from src.constants.enums import SlotStatus
from src.control.agents.state import AWAITING_HANDOFF_CONTACT, CONFIRMATION_AWAITING
from src.control.agents.tools import clinic_directory, slot_tools
from src.control.agents.tools.booking_tools import book_appointment, check_patient_active_appointment
from src.control.agents.tools.cancel_tools import cancel_appointment
from src.control.agents.tools.followup_tools import get_followup_candidates
from src.control.agents.tools.identity_tools import verify_patient_by_name_and_dob
from src.control.agents.tools.registration_tools import normalise_phone, register_new_patient, valid_email, validate_dob
from src.control.agents.tools.reschedule_tools import reschedule_appointment
from src.control.agents.tools.visit_type import DEFAULT_VISIT_TYPE, active_visit_names, canonical_visit_type
from src.core.exceptions import AppointmentServiceError, SlotUnavailableError
from src.core.services.confirmation_delivery import queue_confirmation, queue_frontdesk_alert
from src.core.services.notification_service import NotificationService
from src.data.models.postgres.appointment_type import AppointmentType
from src.data.models.postgres.location import Location
from src.data.models.postgres.patient import Patient
from src.data.models.postgres.provider import Provider
from src.data.models.postgres.slot import Slot
from src.observability.metrics import booking_outcomes_total
from src.utils.appointment_time import CLINIC_TIMEZONE, format_appointment_time

logger = logging.getLogger(__name__)

PHONE_CHANNELS = ("outbound_call", "inbound_call")
MAX_VERIFY_ATTEMPTS = 2
MAX_OFFERED = 6
MAX_PER_DOCTOR = 3
AVAILABILITY_DAYS = 7
EMERGENCY_REASON = "medical_emergency"
DEFAULT_HANDOFF_REASON = "Patient requested front desk transfer"
YES_NO = [{"label": "Yes", "message": "yes"}, {"label": "No", "message": "no"}]


# ── Small helpers ─────────────────────────────────────────────────────────────

def _words(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").casefold()).split())


def _clean_name(value: Optional[str]) -> Optional[str]:
    words = [w for w in (value or "").replace(",", " ").split() if w]
    if not words or len(words) > 5 or any(any(ch.isdigit() for ch in w) for w in words):
        return None
    return " ".join(w[:1].upper() + w[1:] for w in words)


def appointment_summary(appointment: Dict[str, Any]) -> Dict[str, Any]:
    when = appointment.get("spoken_time")
    if not when and appointment.get("start_time"):
        try:
            when = format_appointment_time(datetime.fromisoformat(appointment["start_time"]))
        except ValueError:
            when = None
    return {
        "doctor": appointment.get("doctor_name"), "specialty": appointment.get("specialty"),
        "branch": appointment.get("location_name"), "when": when,
    }


def hours_until(appointment: Dict[str, Any]) -> Optional[float]:
    try:
        start = datetime.fromisoformat(appointment["start_time"])
    except (KeyError, ValueError, TypeError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600


def within_cutoff(appointment: Dict[str, Any]) -> bool:
    hours = hours_until(appointment)
    return hours is not None and hours < settings.RESCHEDULE_CANCEL_CUTOFF_HOURS


def public_slot(slot: Dict[str, Any], n: Optional[int] = None) -> Dict[str, Any]:
    """A slot as the model sees it. `when` is the exact wording to say aloud."""
    data = {
        "slot_id": slot.get("slot_id"), "doctor": slot.get("doctor_name"), "specialty": slot.get("specialty"),
        "branch": slot.get("location_name"), "when": slot.get("spoken_time"),
        "date": slot.get("local_date"), "time": slot.get("local_time"),
    }
    return {"n": n, **data} if n is not None else data


def slot_buttons(slots: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {"label": f"{slot['spoken_time']} · {slot['doctor_name']}", "message": f"{slot['doctor_name']}, {slot['spoken_time']}"}
        for slot in slots
    ]


def _pick_offered(slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Earliest slots, at most MAX_PER_DOCTOR per doctor, so one busy doctor does not fill the list."""
    per_doctor: Dict[str, int] = {}
    picked: List[Dict[str, Any]] = []
    for slot in slots:
        name = slot["doctor_name"]
        if per_doctor.get(name, 0) >= MAX_PER_DOCTOR:
            continue
        per_doctor[name] = per_doctor.get(name, 0) + 1
        picked.append(slot)
        if len(picked) >= MAX_OFFERED:
            break
    return picked


def _active_details(appointment_id: str, slot: Dict[str, Any], status: str) -> Dict[str, Any]:
    return {
        "appointment_id": appointment_id, "slot_id": slot.get("slot_id"), "status": status,
        "doctor_name": slot.get("doctor_name"), "specialty": slot.get("specialty"),
        "location_name": slot.get("location_name"), "location_address": slot.get("location_address"),
        "start_time": slot.get("start_time"), "spoken_time": slot.get("spoken_time"),
        "formatted_speech": slot.get("formatted_speech"),
    }


def policy_facts() -> List[str]:
    hours = settings.RESCHEDULE_CANCEL_CUTOFF_HOURS
    return [
        f"Rescheduling and cancelling can be done up to {hours} hours before the appointment; "
        f"inside {hours} hours the front desk handles the change.",
        "Each patient can hold one active appointment at a time; to book another, the current one must be "
        "rescheduled or cancelled first.",
        "Booking needs the patient's full name and date of birth for identity verification, or registration for new patients.",
        "Booking, rescheduling, cancelling and clinic questions work in the web chat, the browser voice assistant "
        "(English, Tamil, Telugu) and on phone calls.",
        "A confirmation is sent by email after booking, rescheduling or cancelling (and by text message when it is available).",
    ]


def _spec(name: str, description: str, properties: Optional[Dict[str, Any]] = None, required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }


def _str(description: str, **extra: Any) -> Dict[str, Any]:
    return {"type": "string", "description": description, **extra}


TOOL_SPECS: List[Dict[str, Any]] = [
    _spec(
        "get_clinic_info",
        "Clinic facts: branches, doctors and specialties, appointment types, hours and policies, open times in the next 7 days, "
        "front desk contact. Read-only, works before identity. Use for any clinic question; never answer these from memory.",
        {"topic": _str("What to look up", enum=["all", "branches", "doctors", "appointment_types", "hours_and_policies", "open_times"])},
    ),
    _spec(
        "verify_identity",
        "Confirm an existing patient by full name and date of birth, exactly as the patient said them. Unlocks the patient tools. "
        "A mismatch does not say which detail was wrong; 2 failed checks automatically pass the patient to the front desk.",
        {"full_name": _str("Full name"), "date_of_birth": _str("YYYY-MM-DD")}, ["full_name", "date_of_birth"],
    ),
    _spec(
        "register_patient",
        "Register a new patient (or one verify_identity could not find who says they are new) and verify them. Needs full name, date "
        "of birth and a mobile number (on a phone call the number called is used). Email is optional; ask once.",
        {"full_name": _str("Full name"), "date_of_birth": _str("YYYY-MM-DD"), "phone": _str("Mobile number"), "email": _str("Optional email")},
        ["full_name", "date_of_birth"],
    ),
    _spec("save_patient_email", "Save an email on the verified patient's record for confirmations.", {"email": _str("Email")}, ["email"]),
    _spec(
        "get_my_appointment",
        "The verified patient's one active appointment and whether it is inside the 24 hour cutoff. Call before booking, rescheduling or cancelling.",
    ),
    _spec("get_previous_visits", "The verified patient's recent completed visits; use for a follow-up (same doctor and branch)."),
    _spec(
        "search_slots",
        "Search open times for the verified patient. Pass only what the patient asked for; at least one of specialty, doctor, branch or date. "
        "Returns up to 6 numbered options with slot_id and the exact wording to say in `when`. Holds nothing. If none match, retry with fewer "
        "filters (time, then date, branch, doctor) and say what you loosened; never change the specialty without asking.",
        {
            "specialty": _str("Specialty"), "doctor": _str("Doctor"), "branch": _str("Branch"),
            "date_from": _str("YYYY-MM-DD"), "date_to": _str("YYYY-MM-DD"),
            "time_from": _str("HH:MM 24h"), "time_to": _str("HH:MM 24h"),
            "exclude_doctors": {"type": "array", "items": {"type": "string"}, "description": "Doctors the patient does not want"},
        },
    ),
    _spec(
        "hold_slot",
        "Hold one option from the latest search_slots for the verified patient for a few minutes. Replaces any slot already held. Books nothing.",
        {"slot_id": _str("slot_id of the chosen option")}, ["slot_id"],
    ),
    _spec("release_hold", "Give back the held slot (patient declined or wants another time)."),
    _spec(
        "request_confirmation",
        "Record that you are about to ask the final yes/no question before a booking, reschedule or cancellation. book/reschedule need a held "
        "slot; reschedule/cancel need an active appointment outside the cutoff; book needs no active appointment. When it succeeds, end your "
        "turn by reading the details back and asking one clear yes/no question. The write tools only work on the patient's answer in the NEXT message.",
        {"action": _str("What will be written", enum=["book", "reschedule", "cancel"])}, ["action"],
    ),
    _spec(
        "book_appointment",
        "Book the held slot. Only works if the previous turn ended with request_confirmation(book) for this slot and the patient's current message says yes.",
        {
            "consent_quote": _str("The patient's agreeing words, copied exactly from their latest message"),
            "appointment_type": _str("A type from get_clinic_info; default General Consultation"), "visit_reason": _str("Short reason"),
        },
        ["consent_quote"],
    ),
    _spec(
        "reschedule_appointment",
        "Move the active appointment to the held slot. Same rules, after request_confirmation(reschedule).",
        {"consent_quote": _str("The patient's agreeing words, copied exactly from their latest message"), "visit_reason": _str("Optional")},
        ["consent_quote"],
    ),
    _spec(
        "cancel_appointment",
        "Cancel the active appointment. Same rules, after request_confirmation(cancel).",
        {"consent_quote": _str("The patient's agreeing words, copied exactly from their latest message")}, ["consent_quote"],
    ),
    _spec(
        "handoff_to_front_desk",
        "Pass the conversation to the human front desk and alert them: emergencies (emergency=true, at once, no identity needed), a request for a "
        "person, being stuck, or when a tool says the front desk must handle it. On web chat, if no contact is known the tool asks you to request "
        "one; the patient may decline (contact_declined=true).",
        {
            "reason": _str("Why, in a few words"), "emergency": {"type": "boolean", "description": "Current life-threatening problem"},
            "callback_phone": _str("Phone to reach the patient"), "callback_email": _str("Email to reach the patient"),
            "contact_declined": {"type": "boolean", "description": "Patient refused to give a contact"},
        },
        ["reason"],
    ),
    _spec(
        "end_conversation",
        "Finish after goodbye or when there is nothing more to do; releases any held slot. Use reason wrong_person if someone on a call says it is the wrong number.",
        {"reason": _str("Why", enum=["goodbye", "wrong_person", "other"])},
    ),
]


class Toolbox:
    """The tools for one turn. `state` is the conversation state and is updated in place."""

    def __init__(self, db, state: Dict[str, Any]) -> None:
        self.db = db
        self.s = state
        self.message = _words(state.get("latest_user_speech") or "")
        # The yes/no question recorded in the PREVIOUS turn. Consent only counts against this.
        self.confirmation_at_start: Optional[Dict[str, Any]] = state.get("pending_confirmation")
        self.confirmation_asked = False
        self.searched = False
        self.contact_requested = False
        self._visit_names: Optional[List[str]] = None
        self._handlers: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {
            spec["name"]: getattr(self, spec["name"]) for spec in TOOL_SPECS
        }

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            return {"status": "unknown_tool", "message": f"No tool named {name}."}
        # Arguments the tool does not take are ignored (models sometimes add extras); missing ones are reported.
        accepted = inspect.signature(handler).parameters
        clean = {k: v for k, v in (args or {}).items() if v is not None and k in accepted}
        try:
            return await handler(**clean)
        except TypeError as exc:
            return {"status": "bad_arguments", "message": str(exc)[:200]}

    # ── Shared checks ─────────────────────────────────────────────────────────

    @property
    def verified(self) -> bool:
        return bool(self.s.get("is_verified"))

    @property
    def phone_call(self) -> bool:
        return self.s.get("channel") in PHONE_CHANNELS

    def _closed(self) -> Optional[Dict[str, Any]]:
        if self.s.get("handoff_completed") or self.s.get("end_outcome"):
            return {"status": "conversation_closed", "message": "This conversation has already been handed over or ended."}
        return None

    def _need_identity(self) -> Optional[Dict[str, Any]]:
        if self.verified:
            return None
        return {"status": "identity_required", "message": "Confirm the patient's full name and date of birth first (verify_identity), or register them if they are new."}

    async def _visit_type_names(self) -> List[str]:
        if self._visit_names is None:
            self._visit_names = await active_visit_names(self.db)
        return self._visit_names

    async def _active_appointment(self) -> Optional[Dict[str, Any]]:
        active = await check_patient_active_appointment(self.s["patient_id"], self.db)
        self.s["active_appointment_id"] = active["appointment_id"] if active else None
        self.s["active_appointment_details"] = active
        return active

    async def _release(self) -> None:
        slot_id = self.s.get("target_slot_id")
        if slot_id:
            try:
                await slot_tools.release_slot(slot_id, self.db)
            except Exception:
                logger.warning("Could not release held slot %s", slot_id, exc_info=True)
        self.s["target_slot_id"] = None
        self.s["target_slot_details"] = None

    def _apply_patient(self, patient: Dict[str, Any]) -> None:
        s = self.s
        s.update({
            "is_verified": True, "patient_id": patient["id"], "patient_name": patient["full_name"],
            "patient_dob": patient.get("date_of_birth"), "patient_email": patient.get("email") or s.get("patient_email"),
            "verify_attempts": 0,
        })
        if patient.get("phone") and not s.get("patient_phone"):
            s["patient_phone"] = patient["phone"]

    def _consent(self, action: str, quote: str) -> Optional[Dict[str, Any]]:
        """None when this write is allowed; otherwise the refusal to show the model."""
        pending = self.confirmation_at_start
        if not pending or pending.get("action") != action:
            return {"status": "not_confirmed", "message": (
                "No confirmation question is on record. Call request_confirmation, then ask the yes/no question in this reply "
                "and wait for their answer in the next message; do not call this tool again in this turn.")}
        if action in ("book", "reschedule") and pending.get("slot_id") != self.s.get("target_slot_id"):
            return {"status": "not_confirmed", "message": "The held slot changed since the patient was asked. Ask again."}
        if action in ("reschedule", "cancel") and pending.get("appointment_id") != self.s.get("active_appointment_id"):
            return {"status": "not_confirmed", "message": "The appointment changed since the patient was asked. Ask again."}
        quoted = _words(quote)
        if not quoted or len(quoted) > 120 or quoted not in self.message:
            return {"status": "consent_not_found", "message": "consent_quote must be the patient's own words, copied from their latest message."}
        return None

    # ── Clinic information ────────────────────────────────────────────────────

    async def get_clinic_info(self, topic: str = "all") -> Dict[str, Any]:
        db = self.db
        locations = list((await db.scalars(select(Location).where(Location.is_active.is_(True)).order_by(Location.name))).all())
        providers = list((await db.scalars(
            select(Provider).where(Provider.is_active.is_(True)).order_by(Provider.specialty, Provider.full_name)
        )).all())
        branch_name = {loc.id: loc.name for loc in locations}
        info: Dict[str, Any] = {"clinic": settings.CLINIC_NAME}
        wanted = lambda *names: topic == "all" or topic in names   # noqa: E731
        if wanted("branches"):
            info["branches"] = [{"name": loc.name, "address": loc.address or "not listed"} for loc in locations]
        if wanted("doctors"):
            info["doctors"] = [
                {"name": p.full_name, "specialty": p.specialty or "not listed", "branch": branch_name.get(p.location_id, "")}
                for p in providers
            ]
        if wanted("appointment_types"):
            types = list((await db.scalars(select(AppointmentType).where(AppointmentType.is_active.is_(True)).order_by(AppointmentType.name))).all())
            info["appointment_types"] = [{"name": t.name, "minutes": t.duration_minutes, "instructions": t.instructions or None} for t in types]
        if wanted("hours_and_policies"):
            info["hours"] = f"{settings.CLINIC_HOURS_START:02d}:00 to {settings.CLINIC_HOURS_END:02d}:00 (local clinic time). Which days the clinic is open is NOT recorded: do not state or guess days; use open_times to show real availability."
            info["policies"] = policy_facts()
            info["front_desk_phone"] = settings.FRONT_DESK_PHONE or None
            info["front_desk_email"] = settings.FRONT_DESK_EMAIL or None
        if wanted("open_times"):
            info["open_times_next_7_days"] = await self._open_times(providers, locations)
        return info

    async def _open_times(self, providers, locations) -> Optional[List[str]]:
        """Each doctor's open times over the next week, straight from the slot table."""
        now = datetime.now(timezone.utc)
        rows = (await self.db.scalars(
            select(Slot).where(
                Slot.status == SlotStatus.AVAILABLE, Slot.start_time > now,
                Slot.start_time < now + timedelta(days=AVAILABILITY_DAYS),
            ).order_by(Slot.start_time)
        )).all()
        if not rows:
            return None
        doctors = {p.id: p for p in providers}
        branch = {loc.id: loc.name for loc in locations}
        grouped: Dict[Any, Dict[str, List[datetime]]] = defaultdict(lambda: defaultdict(list))
        for slot in rows:
            start = slot.start_time if slot.start_time.tzinfo else slot.start_time.replace(tzinfo=timezone.utc)
            local = start.astimezone(CLINIC_TIMEZONE)
            grouped[slot.provider_id][local.strftime("%a %d %b")].append(local)
        lines = []
        for provider_id, days in grouped.items():
            doctor = doctors.get(provider_id)
            if doctor is None:
                continue
            per_day = "; ".join(
                f"{day} {times[0].strftime('%I:%M %p')} to {times[-1].strftime('%I:%M %p')} ({len(times)} slots)"
                for day, times in days.items()
            )
            lines.append(f"{doctor.full_name} ({doctor.specialty or 'specialty not listed'}, {branch.get(doctor.location_id, '')}): {per_day}")
        return lines

    # ── Identity ──────────────────────────────────────────────────────────────

    async def verify_identity(self, full_name: str, date_of_birth: str) -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if self.verified:
            return {"status": "already_verified", "first_name": (self.s.get("patient_name") or "").split(" ")[0]}
        name = _clean_name(full_name)
        ok, parsed, problem = validate_dob(date_of_birth)
        if not name:
            return {"status": "invalid_name", "message": "Ask the patient for their full name."}
        if not ok or not parsed:
            return {"status": "invalid_date_of_birth", "message": problem or "Ask again with day, month and a four-digit year."}
        matched, patient = await verify_patient_by_name_and_dob(name, parsed.isoformat(), self.db)
        if matched and patient:
            self._apply_patient(patient)
            return {"status": "verified", "first_name": patient["full_name"].split(" ")[0]}
        attempts = int(self.s.get("verify_attempts") or 0) + 1
        self.s["verify_attempts"] = attempts
        if attempts >= MAX_VERIFY_ATTEMPTS:
            handed = await self.handoff_to_front_desk("Patient identity could not be verified after two attempts", contact_declined=True)
            return {"status": "failed_final_handed_to_front_desk", **{k: handed.get(k) for k in ("callback_contact_available", "front_desk_phone")}}
        return {
            "status": "no_match", "attempts_left": MAX_VERIFY_ATTEMPTS - attempts,
            "message": "The details did not match our records. Do not say which detail was wrong. Ask them to try again, or say if they are a new patient.",
        }

    async def register_patient(self, full_name: str, date_of_birth: str, phone: str = "", email: str = "") -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if self.verified:
            return {"status": "already_verified"}
        name = _clean_name(full_name)
        ok, parsed, problem = validate_dob(date_of_birth)
        mobile = normalise_phone(phone) or self.s.get("patient_phone") or None
        clean_email = valid_email(email)
        missing = [k for k, v in (("full_name", name), ("phone", mobile)) if not v]
        if not ok or not parsed:
            return {"status": "invalid_date_of_birth", "message": problem or "Ask again with day, month and a four-digit year."}
        if missing:
            return {"status": "missing_details", "missing": missing}
        if email and not clean_email:
            return {"status": "invalid_email", "message": "That email did not look valid; ask again or skip it."}
        patient = await register_new_patient(name, parsed, mobile, clean_email, self.db)
        # Registration reuses an existing profile when the phone matches. Only a full match may verify the patient.
        if _words(patient["full_name"]) != _words(name) or patient.get("date_of_birth") != parsed.isoformat():
            handed = await self.handoff_to_front_desk("Registration matched an existing profile with different details", contact_declined=True)
            return {"status": "needs_front_desk", **{k: handed.get(k) for k in ("callback_contact_available", "front_desk_phone")}}
        self._apply_patient(patient)
        self.s["patient_phone"] = patient.get("phone") or mobile
        return {"status": "registered", "first_name": patient["full_name"].split(" ")[0]}

    async def save_patient_email(self, email: str) -> Dict[str, Any]:
        if (blocked := self._need_identity()):
            return blocked
        clean = valid_email(email)
        if not clean:
            return {"status": "invalid_email", "message": "That email did not look valid; ask again or skip it."}
        patient = await self.db.get(Patient, uuid.UUID(self.s["patient_id"]))
        if patient is not None and patient.email != clean:
            patient.email = clean
            await self.db.flush()
        self.s["patient_email"] = clean
        return {"status": "saved"}

    # ── Appointment history ───────────────────────────────────────────────────

    async def get_my_appointment(self) -> Dict[str, Any]:
        if (blocked := self._need_identity()):
            return blocked
        active = await self._active_appointment()
        if not active:
            return {"status": "none", "has_active_appointment": False}
        return {
            "status": "found", "has_active_appointment": True, "appointment": appointment_summary(active),
            "within_cutoff": within_cutoff(active), "cutoff_hours": settings.RESCHEDULE_CANCEL_CUTOFF_HOURS,
        }

    async def get_previous_visits(self) -> Dict[str, Any]:
        if (blocked := self._need_identity()):
            return blocked
        visits = await get_followup_candidates(self.s["patient_id"], self.db)
        return {"status": "found" if visits else "none", "visits": [
            {"n": i, "doctor": v["doctor_name"], "specialty": v["specialty"], "branch": v.get("location_name"), "date": v["formatted_date"]}
            for i, v in enumerate(visits, start=1)
        ]}

    # ── Finding and holding a slot ────────────────────────────────────────────

    async def search_slots(
        self, specialty: str = "", doctor: str = "", branch: str = "", date_from: str = "", date_to: str = "",
        time_from: str = "", time_to: str = "", exclude_doctors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if (blocked := self._need_identity()):
            return blocked
        checked = {}
        for field, value, resolve, valid in (
            ("specialty", specialty, clinic_directory.canonical_specialty, clinic_directory.all_specialties),
            ("doctor", doctor, clinic_directory.canonical_doctor, lambda: [d["name"] for d in clinic_directory.doctors()]),
            ("branch", branch, clinic_directory.canonical_branch, clinic_directory.branch_names),
        ):
            if value:
                checked[field] = resolve(value)
                if not checked[field]:
                    return {"status": "unknown_value", "field": field, "valid_values": valid()}
        first, last = slot_tools.parse_iso_date(date_from), slot_tools.parse_iso_date(date_to)
        if (date_from and not first) or (date_to and not last):
            return {"status": "invalid_date", "message": "Dates must be YYYY-MM-DD."}
        last = last or first
        if first and first < slot_tools.clinic_today():
            return {"status": "date_in_past", "date": first.isoformat()}
        if first and last < first:
            last = first
        start, end = slot_tools.parse_hhmm(time_from), slot_tools.parse_hhmm(time_to)
        if not (checked.get("specialty") or checked.get("doctor") or checked.get("branch") or first):
            return {"status": "need_more_criteria", "message": "Ask which specialty, doctor, branch or day suits the patient.",
                    "branches": clinic_directory.branch_names(), "specialties": clinic_directory.all_specialties()}

        # A patient's own current time is never offered back to them.
        current = await self._active_appointment() or {}
        exclude = [current["slot_id"]] if current.get("slot_id") else []
        rows = await slot_tools.search_slots(
            self.db, date_from=first, date_to=last, specialty=checked.get("specialty"),
            location_name=checked.get("branch"), doctor_name=checked.get("doctor"),
            time_from=(start or end), time_to=(end or start), exclude_slot_ids=exclude, limit=40,
        )
        skip = {_words(n) for n in (exclude_doctors or [])}
        if skip:
            rows = [r for r in rows if _words(r["doctor_name"]) not in skip]
        searched = {k: v for k, v in {
            "specialty": checked.get("specialty"), "doctor": checked.get("doctor"), "branch": checked.get("branch"),
            "date_from": first.isoformat() if first else None, "date_to": last.isoformat() if last else None,
            "time_from": time_from or None, "time_to": time_to or None,
        }.items() if v}
        offered = _pick_offered(rows)
        self.s["offered_slots"] = offered
        self.searched = True
        if not offered:
            return {"status": "none_found", "searched": searched}
        return {"status": "found", "searched": searched, "total_matching": len(rows),
                "options": [public_slot(o, i) for i, o in enumerate(offered, start=1)]}

    async def hold_slot(self, slot_id: str) -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if (blocked := self._need_identity()):
            return blocked
        slot = next((o for o in (self.s.get("offered_slots") or []) if o["slot_id"] == slot_id), None)
        if slot is None:
            return {"status": "not_offered", "message": "Only a slot_id from the latest search_slots result can be held."}
        if self.s.get("target_slot_id") == slot_id:
            return {"status": "held", "slot": public_slot(slot), "already_held": True}
        await self._release()
        try:
            await slot_tools.reserve_slot(slot_id, self.db)
        except SlotUnavailableError:
            self.s["offered_slots"] = [o for o in self.s["offered_slots"] if o["slot_id"] != slot_id]
            return {"status": "slot_taken", "message": "Someone just took that time. Offer the other options or search again."}
        self.s["target_slot_id"], self.s["target_slot_details"] = slot_id, slot
        self.s["pending_confirmation"] = None
        self.confirmation_asked = False
        return {"status": "held", "slot": public_slot(slot), "held_for_minutes": settings.SLOT_RESERVATION_TIMEOUT_MINUTES}

    async def release_hold(self) -> Dict[str, Any]:
        had = bool(self.s.get("target_slot_id"))
        await self._release()
        self.s["pending_confirmation"] = None
        self.confirmation_asked = False
        return {"status": "released" if had else "nothing_held"}

    # ── Confirmation and the writes ───────────────────────────────────────────

    async def request_confirmation(self, action: str) -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if (blocked := self._need_identity()):
            return blocked
        if action not in ("book", "reschedule", "cancel"):
            return {"status": "bad_arguments", "message": "action must be book, reschedule or cancel."}
        active = await self._active_appointment()
        pending: Dict[str, Any] = {"action": action}
        summary: Dict[str, Any] = {"action": action}
        if action == "book":
            if active:
                return {"status": "blocked", "reason": "already_has_active_appointment", "appointment": appointment_summary(active),
                        "message": "One active appointment per patient. Offer to reschedule it instead."}
            if not self.s.get("target_slot_id"):
                return {"status": "blocked", "reason": "no_slot_held", "message": "Hold a slot first."}
        else:
            if not active:
                return {"status": "blocked", "reason": "no_active_appointment"}
            if within_cutoff(active):
                return {"status": "blocked", "reason": "within_cutoff", "cutoff_hours": settings.RESCHEDULE_CANCEL_CUTOFF_HOURS,
                        "message": "Changes inside the cutoff are handled by the front desk. Use handoff_to_front_desk."}
            pending["appointment_id"] = active["appointment_id"]
            summary["current"] = appointment_summary(active)
            if action == "reschedule":
                if not self.s.get("target_slot_id"):
                    return {"status": "blocked", "reason": "no_slot_held", "message": "Hold the new slot first."}
                if self.s["target_slot_id"] == active.get("slot_id"):
                    return {"status": "blocked", "reason": "same_slot"}
        if action in ("book", "reschedule"):
            pending["slot_id"] = self.s["target_slot_id"]
            summary["new"] = public_slot(self.s["target_slot_details"])
        self.s["pending_confirmation"] = pending
        self.s["intent"] = action
        self.confirmation_asked = True
        return {"status": "recorded", "summary": summary,
                "message": "Now end your turn: read the details back and ask one clear yes/no question."}

    async def _write_failed(self, action: str, exc: Exception) -> Dict[str, Any]:
        booking_outcomes_total.labels(action, "failed").inc()
        message = str(exc).lower()
        self.s["pending_confirmation"] = None
        if "hours away" in message:
            return {"status": "blocked_cutoff", "message": "Inside the cutoff window; use handoff_to_front_desk."}
        if "already has an active" in message:
            await self._release()
            return {"status": "has_active_appointment", "message": "The patient already has an active appointment; offer to reschedule it."}
        if isinstance(exc, (SlotUnavailableError, AppointmentServiceError)) and action != "cancel":
            await self._release()
            return {"status": "slot_unavailable", "message": "That time is no longer available. Search again and offer other times."}
        return {"status": "failed", "message": "It could not be saved. Apologise and use handoff_to_front_desk."}

    async def _finish_write(self, action: str, intent: str, appointment_id: str, slot: Dict[str, Any]) -> Dict[str, Any]:
        s = self.s
        s.update({
            "booking_confirmed": True, "intent": intent, "target_slot_id": None, "target_slot_details": None,
            "offered_slots": [], "pending_confirmation": None,
        })
        return await queue_confirmation(
            self.db, action=action, appointment_id=appointment_id, conversation_id=s.get("conversation_id"),
            patient_id=s.get("patient_id"), patient_name=s.get("patient_name"), patient_phone=s.get("patient_phone"),
            patient_email=s.get("patient_email"), slot=slot,
        )

    async def book_appointment(self, consent_quote: str, appointment_type: str = "", visit_reason: str = "") -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if (blocked := self._need_identity()) or (blocked := self._consent("book", consent_quote)):
            return blocked
        s = self.s
        visit_type = DEFAULT_VISIT_TYPE
        if appointment_type:
            visit_type = canonical_visit_type(appointment_type, await self._visit_type_names())
            if not visit_type:
                return {"status": "unknown_appointment_type", "valid_values": await self._visit_type_names()}
        slot = dict(s["target_slot_details"])
        try:
            async with self.db.begin_nested():
                result = await book_appointment(
                    s["patient_id"], s["target_slot_id"], s["conversation_id"], self.db,
                    reason=(visit_reason or "")[:200] or None, appointment_type_name=visit_type,
                )
        except (AppointmentServiceError, SlotUnavailableError, ValueError, SQLAlchemyError) as exc:
            return await self._write_failed("book", exc)
        booking_outcomes_total.labels("book", "success").inc()
        s["active_appointment_id"] = result["appointment_id"]
        s["active_appointment_details"] = _active_details(result["appointment_id"], slot, "booked")
        confirmation = await self._finish_write("booked", "book", result["appointment_id"], slot)
        return {"status": "booked", "appointment": public_slot(slot), "visit_type": visit_type, "confirmation": confirmation}

    async def reschedule_appointment(self, consent_quote: str, visit_reason: str = "") -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if (blocked := self._need_identity()):
            return blocked
        if not await self._active_appointment():
            return {"status": "no_active_appointment"}
        if (blocked := self._consent("reschedule", consent_quote)):
            return blocked
        s = self.s
        active, slot = dict(s["active_appointment_details"]), dict(s["target_slot_details"])
        if within_cutoff(active):
            return {"status": "blocked_cutoff", "message": "Inside the cutoff window; use handoff_to_front_desk."}
        try:
            async with self.db.begin_nested():
                result = await reschedule_appointment(
                    active["appointment_id"], s["target_slot_id"], s["conversation_id"], self.db, reason=(visit_reason or "")[:200] or None,
                )
        except (AppointmentServiceError, SlotUnavailableError, ValueError, SQLAlchemyError) as exc:
            return await self._write_failed("reschedule", exc)
        booking_outcomes_total.labels("reschedule", "success").inc()
        s["active_appointment_details"] = _active_details(result["appointment_id"], slot, "rescheduled")
        confirmation = await self._finish_write("rescheduled", "reschedule", result["appointment_id"], slot)
        return {"status": "rescheduled", "previous": appointment_summary(active), "appointment": public_slot(slot), "confirmation": confirmation}

    async def cancel_appointment(self, consent_quote: str) -> Dict[str, Any]:
        if self._closed():
            return self._closed()
        if (blocked := self._need_identity()):
            return blocked
        if not await self._active_appointment():
            return {"status": "no_active_appointment"}
        if (blocked := self._consent("cancel", consent_quote)):
            return blocked
        s = self.s
        active = dict(s["active_appointment_details"])
        if within_cutoff(active):
            return {"status": "blocked_cutoff", "message": "Inside the cutoff window; use handoff_to_front_desk."}
        try:
            async with self.db.begin_nested():
                result = await cancel_appointment(
                    active["appointment_id"], s["conversation_id"], self.db, reason=f"Patient requested cancellation ({s.get('channel')})",
                )
        except (AppointmentServiceError, SlotUnavailableError, ValueError, SQLAlchemyError) as exc:
            return await self._write_failed("cancel", exc)
        booking_outcomes_total.labels("cancel", "success").inc()
        await self._release()
        confirmation = await self._finish_write("cancelled", "cancel", result["appointment_id"], active)
        s["active_appointment_id"] = None
        s["active_appointment_details"] = None
        return {"status": "cancelled", "appointment": appointment_summary(active), "confirmation": confirmation}

    # ── Ending ────────────────────────────────────────────────────────────────

    async def handoff_to_front_desk(
        self, reason: str = DEFAULT_HANDOFF_REASON, emergency: bool = False, callback_phone: str = "",
        callback_email: str = "", contact_declined: bool = False,
    ) -> Dict[str, Any]:
        s = self.s
        if s.get("handoff_completed"):
            return {"status": "already_handed_over"}
        reason = (EMERGENCY_REASON if emergency else reason or DEFAULT_HANDOFF_REASON)[:200]
        phone = normalise_phone(callback_phone) or (s.get("patient_phone") if (self.phone_call or self.verified) else None)
        email = valid_email(callback_email) or (s.get("patient_email") if self.verified else None)

        # A web patient has no caller number: ask once for a way to reach them, unless it is an emergency.
        if not emergency and not self.phone_call and not (phone or email) and not contact_declined:
            s["handoff_reason"] = reason
            self.contact_requested = True
            return {"status": "need_callback_contact", "message": "Ask for a phone number or email so the front desk can reach them; they may skip. Then call this tool again."}

        await self._release()
        s.update({
            "handoff_required": True, "handoff_reason": reason, "handoff_completed": True, "pending_confirmation": None,
            "is_completed": True, "is_emergency": emergency or bool(s.get("is_emergency")),
            "callback_contact_unavailable": not (phone or email),
            "end_outcome": "handed_to_front_desk", "end_reason": reason,
        })
        if phone and not s.get("patient_phone"):
            s["patient_phone"] = phone
        if email and not s.get("patient_email"):
            s["patient_email"] = email
        if not s.get("frontdesk_alert_sent"):
            await self._send_alert("URGENT MEDICAL EMERGENCY REPORTED" if emergency else reason, {
                "call_sid": s.get("call_sid"), "conversation_id": s.get("conversation_id"), "channel": s.get("channel"),
                "patient_phone": phone, "patient_email": email,
                "patient_name": s.get("patient_name") if self.verified else None,
                "patient_id": s.get("patient_id") if self.verified else None,
                "identity_verified": self.verified, "emergency": emergency,
            })
        number = (settings.FRONT_DESK_PHONE or "").strip()
        number = number if number and not number.startswith("+91xxxx") else None
        return {
            "status": "handed_over", "emergency": emergency, "callback_contact_available": bool(phone or email),
            "live_transfer": bool(self.phone_call and number), "front_desk_phone": number,
        }

    async def _send_alert(self, reason: str, details: dict) -> None:
        if queue_frontdesk_alert(conversation_id=self.s.get("conversation_id"), reason=reason, call_details=details):
            return
        try:  # nobody is collecting deferred jobs (a script or test): send now
            sent = await NotificationService(self.db).send_frontdesk_alert_email(reason=reason, call_details=details)
            self.s["frontdesk_alert_sent"] = bool(sent)
        except Exception:
            logger.warning("Front desk alert failed", exc_info=True)

    async def end_conversation(self, reason: str = "goodbye") -> Dict[str, Any]:
        s = self.s
        if s.get("end_outcome"):
            return {"status": "already_ended"}
        await self._release()
        s["pending_confirmation"] = None
        s["is_completed"] = True
        if reason == "wrong_person" and self.phone_call:
            s["end_outcome"] = "wrong_person"
        else:
            s["end_outcome"] = "ended"
        return {"status": "ended"}

    # ── End of turn ───────────────────────────────────────────────────────────

    def finish_turn(self) -> List[Dict[str, str]]:
        """Settle the state after the model's last step; returns the tap-to-answer buttons for web chat."""
        s = self.s
        if not self.confirmation_asked:
            s["pending_confirmation"] = None       # a question is good for one answer only
        pending = s.get("pending_confirmation")
        if pending:
            s["awaiting"] = CONFIRMATION_AWAITING[pending["action"]]
        elif self.contact_requested:
            s["awaiting"] = AWAITING_HANDOFF_CONTACT
        else:
            s["awaiting"] = None
        if s.get("end_outcome") or s.get("is_completed"):
            return []
        if pending:
            return list(YES_NO)
        if self.searched and not s.get("target_slot_id") and s.get("offered_slots"):
            return slot_buttons(s["offered_slots"])
        return []
