"""Reschedule agent node ??? handles atomic rescheduling with doctor anchoring, alternative slot selection, and cutoff checks."""
import logging
import re
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Tuple
# pyrefly: ignore[missing-import]
from sqlalchemy import select
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.control.agents.tools.reschedule_tools import reschedule_appointment
from src.control.agents.nodes.booking_helpers import _extract_time_window
from src.control.agents.tools.slot_tools import (
    get_available_slots,
    get_branches_for_specialty,
    get_slots_by_doctor,
    get_slots_by_date_and_criteria,
    get_slots_by_location,
    get_slots_by_specialty_and_location,
    parse_date_query_to_range,
    release_slot,
    reserve_slot,
)
from src.config.settings import settings
from src.constants.enums import ConversationState
from src.data.models.postgres.appointment_type import AppointmentType
from src.data.repositories.conversation_repository import ConversationRepository
from src.observability.metrics import booking_outcomes_total

logger = logging.getLogger(__name__)

CLINIC_TIMEZONE = ZoneInfo("Asia/Kolkata")


def _extract_time_of_day(text: str) -> Optional[Tuple[int, int]]:
    """Extract requested time of day from speech. Returns (hour_24, minute)."""
    lower = text.lower().strip()
    m1 = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", lower)
    if m1:
        hr = int(m1.group(1))
        mn = int(m1.group(2))
        meridiem = m1.group(3)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        elif not meridiem and 1 <= hr <= 6:
            hr += 12
        return hr, mn

    m2 = re.search(r"\b(\d{1,2})\s*(am|pm)\b", lower)
    if m2:
        hr = int(m2.group(1))
        meridiem = m2.group(2)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        return hr, 0

    m3 = re.search(r"\bat\s+(\d{1,2})\b", lower)
    if m3:
        hr = int(m3.group(1))
        if 1 <= hr <= 6:
            hr += 12
        return hr, 0

    return None


async def reschedule_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    raw_speech = state.get("latest_user_speech", "").strip()
    user_speech = raw_speech.lower()
    patient_id = state.get("patient_id")
    convo_id = state.get("conversation_id")
    target_slot = state.get("target_slot_details")
    target_slot_id = state.get("target_slot_id")
    offered_slots = state.get("offered_slots") or []
    repo = ConversationRepository(db)

    # 1. Fetch current active appointment
    active_appt = state.get("active_appointment_details")
    if not active_appt and patient_id:
        active_appt = await check_patient_active_appointment(patient_id, db)

    if not active_appt:
        return {
            "latest_agent_speech": "I couldn't find an active appointment to reschedule. Would you like to book a new appointment instead?",
        }

    # 2. Check 24-hour cutoff policy
    start_time_iso = active_appt.get("start_time")
    if start_time_iso:
        try:
            start_dt = datetime.fromisoformat(start_time_iso)
            now = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now(timezone.utc)
            hours_diff = (start_dt - now).total_seconds() / 3600
            if hours_diff < settings.RESCHEDULE_CANCEL_CUTOFF_HOURS:
                return {
                    "handoff_required": True,
                    "handoff_reason": "Reschedule within 24-hour cutoff window",
                    "latest_agent_speech": (
                        f"Your appointment is in less than {settings.RESCHEDULE_CANCEL_CUTOFF_HOURS} hours. "
                        "Our clinic policy requires speaking with the front desk for late changes. Please hold while I connect you."
                    ),
                }
        except Exception as e:
            logger.warning(f"Failed parsing appointment start time: {e}")

    # Anchor doctor, specialty, location from active appointment or state
    current_doc = active_appt.get("doctor_name")
    current_loc = active_appt.get("location_name")
    current_spec = active_appt.get("specialty")
    requested_start, requested_end = parse_date_query_to_range(raw_speech)
    is_asking_alternative_dates = any(
        phrase in user_speech
        for phrase in (
            "alternative date", "alternative dates", "other dates", "another date",
            "different date", "different dates", "show me dates", "show dates",
        )
    )

    # 3. Detect Confirmation when a new slot is currently held
    has_confirm_word = any(
        w in user_speech
        for w in [
            "yes", "confirm", "sure", "move it", "change it", "please", "okay", "fine",
            "book it", "book that", "book", "go ahead", "reschedule it", "reschedule",
            "that works", "perfect", "sounds good", "done", "alright", "proceed"
        ]
    )
    has_negation = any(
        w in user_speech
        for w in [
            "no", "don't", "cancel", "not this", "different", "other", "another",
            "alternative", "alterantive", "change time", "change slot", "keep"
        ]
    )

    if target_slot and target_slot_id:
        # Check same slot constraint
        if target_slot_id == active_appt.get("slot_id"):
            await release_slot(target_slot_id, db)
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "latest_agent_speech": "You are already booked for that same appointment slot! Would you like to pick a different date or time?",
            }

        # User confirms held slot
        if has_confirm_word and not has_negation:
            try:
                res = await reschedule_appointment(
                    appointment_id_str=active_appt["appointment_id"],
                    new_slot_id_str=target_slot_id,
                    conversation_id_str=convo_id,
                    db=db,
                )
                if convo_id:
                    try:
                        await repo.update_state(uuid.UUID(str(convo_id)), ConversationState.RESCHEDULED)
                    except Exception:
                        pass
                booking_outcomes_total.labels("reschedule", "success").inc()

                # Get preparation instructions if available
                prep_note = ""
                type_res = await db.execute(select(AppointmentType).where(AppointmentType.is_active == True).limit(1))
                appt_type = type_res.scalars().first()
                if appt_type and appt_type.instructions:
                    prep_note = f" {appt_type.instructions}"

                speech = (
                    f"Your appointment with {target_slot.get('doctor_name')} has been rescheduled to "
                    f"{target_slot.get('formatted_speech')}."
                    f"{prep_note}"
                )
                return {
                    "booking_confirmed": True,
                    "active_appointment_id": active_appt["appointment_id"],
                    # Keep the selected slot through the confirmation node so it
                    # reports the new time, not the stale active appointment time.
                    "target_slot_id": target_slot_id,
                    "target_slot_details": target_slot,
                    "latest_agent_speech": speech,
                }
            except Exception as e:
                booking_outcomes_total.labels("reschedule", "failed").inc()
                logger.error(f"Reschedule failed: {e}")
                try:
                    await db.rollback()
                except Exception:
                    pass
                try:
                    await release_slot(target_slot_id, db)
                except Exception:
                    pass
                return {
                    "handoff_required": True,
                    "handoff_reason": f"Reschedule failure: {str(e)}",
                    "latest_agent_speech": "I encountered an issue updating your appointment. Let me transfer you to our front desk.",
                }

    # 4. Check if patient asks for an alternative slot / different time / different date
    is_asking_alternative = not is_asking_alternative_dates and (any(
        phrase in user_speech
        for phrase in [
            "another slot", "alternative slot", "alterantive slot", "can i have alternative slots",
            "different slot", "other slot", "another time", "different time", "other time",
            "different day", "another day", "change time", "change slot", "another timing",
            "alternative timing", "other slots", "different date", "another date", "alternative",
            "alternatives", "can i have another slot", "any other slot", "any other time"
        ]
    ) or (
        any(w in user_speech for w in ["another", "different", "other", "alternative", "alterantive"])
        and any(w in user_speech for w in ["slot", "slots", "time", "times", "date", "dates", "timing", "timings"])
    ))

    # 5. Check if patient asks for another location or branch
    is_asking_another_location = any(
        phrase in user_speech
        for phrase in [
            "another location", "can i have another location", "different location",
            "other location", "change location", "another branch", "different branch",
            "other branch", "change branch", "switch branch", "switch location",
        ]
    )
    if is_asking_another_location:
        if target_slot_id:
            await release_slot(target_slot_id, db)
        spec = current_spec or "General Medicine"
        avail_branches = get_branches_for_specialty(spec)
        branch_str = ", ".join(avail_branches[:-1]) + f", and {avail_branches[-1]}" if len(avail_branches) > 1 else (avail_branches[0] if avail_branches else "our other")
        speech = (
            f"City Care Clinic has four branches in Chennai: Anna Nagar, T. Nagar, Velachery, and Tambaram. "
            f"For {spec}, doctors are available at our {branch_str} branches. Which branch would you prefer?"
        )
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "preferred_specialty": spec,
            "latest_agent_speech": speech,
        }

    # 6. Parse specific location or doctor mentioned by user
    requested_location = next(
        (
            loc
            for loc, aliases in {
                "Anna Nagar": ("anna nagar", "annanagar"),
                "T. Nagar": ("t nagar", "t. nagar", "tnagar"),
                "Velachery": ("velachery",),
                "Tambaram": ("tambaram",),
            }.items()
            if any(alias in user_speech for alias in aliases)
        ),
        None,
    )

    requested_doctor = None
    doctor_match = re.search(
        r"\b(?:for|with|from)\s+(?:dr\.?\s+)?([a-z]+(?:\s+[a-z]+){1,3})",
        user_speech,
    )
    if doctor_match:
        requested_doctor = doctor_match.group(1).strip().title()

    # Determine effective doctor anchor
    # CRITICAL: Always default to CURRENT appointment's doctor unless user explicitly requested another doctor/branch!
    effective_doctor = requested_doctor or state.get("preferred_doctor") or current_doc

    # Check if user requested a specific time of day (e.g. "at 2 PM", "11:30 AM")
    req_time = _extract_time_of_day(user_speech)
    req_window = _extract_time_window(user_speech)
    is_asking_to_change_date = is_asking_alternative_dates or any(
        phrase in user_speech
        for phrase in ("change my date", "change date", "new date", "another day", "different day")
    )

    is_reschedule_start = any(
        phrase in user_speech
        for phrase in (
            "reschedule my appointment", "reschedule appointment", "i want to reschedule",
            "i need to reschedule", "move my appointment", "change my appointment",
            "i want to change my appointment",
        )
    )
    if (
        is_reschedule_start
        and requested_start is None
        and req_time is None
        and req_window is None
        and requested_location is None
        and requested_doctor is None
    ):
        if target_slot_id:
            await release_slot(target_slot_id, db)
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "offered_slots": [],
            "awaiting_preferred_date": True,
            "preferred_doctor": current_doc,
            "preferred_location": current_loc,
            "preferred_specialty": current_spec,
            "latest_agent_speech": (
                f"Certainly. What date and time would work better for you with {current_doc}? "
                "You can also tell me a preferred time of day, such as morning or afternoon."
            ),
        }

    # An alternative list is not a selection. Require the patient to name a
    # listed time, then hold that exact slot and ask for final confirmation.
    if offered_slots and not target_slot_id:
        if req_time or req_window:
            req_hr, req_mn = req_time or (None, None)
            requested_start, requested_end = parse_date_query_to_range(raw_speech)
            chosen = None
            for slot in offered_slots:
                slot_dt = datetime.fromisoformat(slot["start_time"])
                if slot_dt.tzinfo is None:
                    slot_dt = slot_dt.replace(tzinfo=timezone.utc)
                local_dt = slot_dt.astimezone(CLINIC_TIMEZONE)
                requested_date = requested_start.astimezone(CLINIC_TIMEZONE).date() if requested_start else None
                requested_date_matches = requested_date is None or requested_date == local_dt.date()
                if requested_date_matches and local_dt.hour == req_hr and abs(local_dt.minute - req_mn) <= 15:
                    chosen = slot
                    break
            if chosen:
                await reserve_slot(chosen["slot_id"], db)
                return {
                    "target_slot_id": chosen["slot_id"],
                    "target_slot_details": chosen,
                    "offered_slots": [],
                    "latest_agent_speech": (
                        f"I can hold {chosen['formatted_speech']}. Would you like me to move your appointment to that time?"
                    ),
                }
        if any(word in user_speech for word in ["book it", "book that", "yes", "confirm", "go ahead"]):
            choices = "; ".join(slot["formatted_speech"] for slot in offered_slots)
            return {
                "latest_agent_speech": f"Which of these times would you like: {choices}? Please tell me the time, and I will confirm before changing your appointment.",
            }

    # A date-change request without a date should ask for one; it must not fall
    # through to the doctor's earliest slot and repeat the old date.
    if is_asking_to_change_date and not is_asking_alternative_dates and requested_start is None:
        if target_slot_id:
            await release_slot(target_slot_id, db)
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "offered_slots": [],
            "awaiting_preferred_date": True,
            "preferred_doctor": effective_doctor,
            "preferred_location": requested_location or current_loc,
            "preferred_specialty": current_spec,
            "latest_agent_speech": "Of course. What date would you like to move your appointment to?",
        }

    # For an explicit date, search within that clinic-local day only. Never
    # silently substitute the doctor's next available date.
    if requested_start is not None:
        if target_slot_id:
            await release_slot(target_slot_id, db)
        requested_local_date = requested_start.astimezone(CLINIC_TIMEZONE).date()
        date_query = requested_local_date.isoformat()
        date_slots = await get_slots_by_date_and_criteria(
            db,
            date_query=date_query,
            doctor_name=effective_doctor,
            location_name=requested_location or current_loc,
            specialty=current_spec,
            limit=50,
        )
        date_slots = [
            slot for slot in date_slots
            if slot["slot_id"] != active_appt.get("slot_id")
        ]
        if req_time or req_window:
            req_hr, req_mn = req_time or (None, None)
            matching = []
            for slot in date_slots:
                slot_dt = datetime.fromisoformat(slot["start_time"])
                if slot_dt.tzinfo is None:
                    slot_dt = slot_dt.replace(tzinfo=timezone.utc)
                slot_local = slot_dt.astimezone(CLINIC_TIMEZONE)
                slot_clock = (slot_local.hour, slot_local.minute)
                matches_time = (
                    req_window[0] <= slot_clock <= req_window[1]
                    if req_window
                    else slot_local.hour == req_hr and abs(slot_local.minute - req_mn) <= 15
                )
                if matches_time:
                    matching.append(slot)
            date_slots = matching

        if not date_slots:
            day_label = requested_local_date.strftime("%A, %B %d")
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "offered_slots": [],
                "awaiting_preferred_date": True,
                "preferred_doctor": effective_doctor,
                "preferred_location": requested_location or current_loc,
                "preferred_specialty": current_spec,
                "latest_agent_speech": (
                    f"I couldn't find an available slot with {effective_doctor} on {day_label}. "
                    "What other date would work for you?"
                ),
            }

        if len(date_slots) == 1:
            chosen = date_slots[0]
            await reserve_slot(chosen["slot_id"], db)
            return {
                "target_slot_id": chosen["slot_id"],
                "target_slot_details": chosen,
                "offered_slots": [],
                "awaiting_preferred_date": False,
                "preferred_doctor": chosen["doctor_name"],
                "preferred_location": chosen["location_name"],
                "preferred_specialty": chosen.get("specialty", current_spec),
                "latest_agent_speech": (
                    f"I found {chosen['formatted_speech']}. Would you like me to move your appointment to that time?"
                ),
            }

        options = date_slots[:5]
        times = "; ".join(slot["formatted_speech"] for slot in options)
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "offered_slots": options,
            "awaiting_preferred_date": True,
            "preferred_doctor": effective_doctor,
            "preferred_location": requested_location or current_loc,
            "preferred_specialty": current_spec,
            "latest_agent_speech": (
                f"On {requested_local_date.strftime('%A, %B %d')}, these times are available: {times}. "
                "Which time would you prefer? I will ask you to confirm before changing the appointment."
            ),
        }

    # "Alternative dates" means different calendar days, not more times on
    # the current day. Offer one real slot on each of the next available days.
    if is_asking_alternative_dates:
        candidates = await get_slots_by_doctor(effective_doctor, db, limit=100) if effective_doctor else []
        current_slot_id = active_appt.get("slot_id")
        current_start = active_appt.get("start_time")
        current_local_day = None
        if current_start:
            current_dt = datetime.fromisoformat(current_start)
            if current_dt.tzinfo is None:
                current_dt = current_dt.replace(tzinfo=timezone.utc)
            current_local_day = current_dt.astimezone(CLINIC_TIMEZONE).date()
        seen_days = set()
        date_options = []
        for slot in candidates:
            if slot["slot_id"] == current_slot_id:
                continue
            slot_dt = datetime.fromisoformat(slot["start_time"])
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=timezone.utc)
            slot_day = slot_dt.astimezone(CLINIC_TIMEZONE).date()
            if slot_day == current_local_day:
                continue
            if slot_day not in seen_days:
                seen_days.add(slot_day)
                date_options.append(slot)
            if len(date_options) == 3:
                break
        if date_options:
            dates_text = "; ".join(slot["formatted_speech"] for slot in date_options)
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "offered_slots": date_options,
                "latest_agent_speech": (
                    f"Here are alternative dates with {effective_doctor}: {dates_text}. "
                    "Which date would you prefer? I will confirm the exact time before rescheduling."
                ),
            }
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "offered_slots": [],
            "awaiting_preferred_date": True,
            "latest_agent_speech": (
                f"I couldn't find another available date with {effective_doctor} right now. "
                "What date would you prefer me to check?"
            ),
        }

    # 7. Slot Discovery
    # If user was already offered a slot and asks for an alternative, release the current held slot
    rejected_slot_id = None
    if (is_asking_alternative or has_negation or req_time) and target_slot_id:
        rejected_slot_id = target_slot_id
        await release_slot(target_slot_id, db)
        target_slot_id = None
        target_slot = None

    slots = []
    # A. Search by doctor first (preserves doctor continuity for patient)
    if effective_doctor and not requested_location:
        all_doc_slots = await get_slots_by_doctor(
            effective_doctor, db, limit=100 if (req_time or req_window) else 15
        )
        # Filter out current active slot and any rejected slot
        candidate_slots = [
            s for s in all_doc_slots
            if s["slot_id"] != active_appt.get("slot_id") and s["slot_id"] != rejected_slot_id
        ]

        if req_time or req_window:
            # Match slot around requested time
            req_hr, req_mn = req_time or (None, None)
            for s in candidate_slots:
                s_dt = datetime.fromisoformat(s["start_time"])
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=timezone.utc)
                s_local = s_dt.astimezone(CLINIC_TIMEZONE)
                slot_clock = (s_local.hour, s_local.minute)
                matches_time = (
                    req_window[0] <= slot_clock <= req_window[1]
                    if req_window
                    else s_local.hour == req_hr and abs(s_local.minute - req_mn) <= 15
                )
                if matches_time:
                    if req_window:
                        slots.append(s)
                    else:
                        slots = [s]
                        break

        if not slots:
            slots = candidate_slots

    # B. If doctor search yielded nothing or user requested a branch
    if not slots:
        if requested_location:
            if current_spec:
                slots = await get_slots_by_specialty_and_location(current_spec, requested_location, db, limit=10)
            else:
                slots = await get_slots_by_location(requested_location, db, limit=10)
        elif current_spec and current_loc:
            # Same specialty and location as current appointment
            slots = await get_slots_by_specialty_and_location(current_spec, current_loc, db, limit=10)
        else:
            slots = await get_available_slots(db, limit=10)

        # Filter out current active slot and rejected slot
        slots = [
            s for s in slots
            if s["slot_id"] != active_appt.get("slot_id") and s["slot_id"] != rejected_slot_id
        ]

    # 8. No slots found
    if not slots:
        if req_time or req_window:
            req_str = (
                f"{req_time[0]:02d}:{req_time[1]:02d}"
                if req_time
                else "the requested time"
            )
            if req_window:
                req_str = (
                    f"between {req_window[0][0]:02d}:{req_window[0][1]:02d} and "
                    f"{req_window[1][0]:02d}:{req_window[1][1]:02d}"
                )
            return {
                "active_appointment_details": active_appt,
                "preferred_doctor": effective_doctor,
                "preferred_location": current_loc,
                "preferred_specialty": current_spec,
                "target_slot_id": None,
                "target_slot_details": None,
                "latest_agent_speech": (
                    f"I'm sorry, I don't see an open slot around {req_str} with {effective_doctor}. "
                    "What other date or time would work for you, or would you like to check another doctor?"
                ),
            }
        return {
            "handoff_required": True,
            "handoff_reason": "No alternative slots available to reschedule",
            "latest_agent_speech": (
                f"I don't have any other open slots for {effective_doctor} right now. "
                "Let me connect you with our front desk to look into additional dates or arrange an opening."
            ),
        }

    # 9. Offer the found slot
    if is_asking_alternative:
        alternatives = slots[:3]
        choices = "; ".join(slot["formatted_speech"] for slot in alternatives)
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "offered_slots": alternatives,
            "active_appointment_details": active_appt,
            "preferred_doctor": effective_doctor,
            "preferred_location": current_loc,
            "preferred_specialty": current_spec,
            "latest_agent_speech": (
                f"Here are alternative times with {effective_doctor}: {choices}. "
                "Which one would you like? I will ask you to confirm before changing your appointment."
            ),
        }

    first_slot = slots[0]
    await reserve_slot(first_slot["slot_id"], db)

    alt_phrase = "an alternative opening" if is_asking_alternative else "an opening"
    speech = (
        f"I have {alt_phrase} for {first_slot['formatted_speech']}. "
        f"Would you like me to move your appointment to that time?"
    )

    return {
        "active_appointment_details": active_appt,
        "target_slot_id": first_slot["slot_id"],
        "target_slot_details": first_slot,
        "offered_slots": [],
        "preferred_doctor": first_slot["doctor_name"],
        "preferred_location": first_slot["location_name"],
        "preferred_specialty": first_slot.get("specialty", current_spec),
        "latest_agent_speech": speech,
    }

