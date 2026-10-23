"""Booking agent node ? coordinates identity details, slot choice, and booking."""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.control.agents.tools.slot_tools import (
    get_slots_by_specialty_and_location, get_branch_doctors_info,
    get_specialties_for_branch, get_branches_for_specialty, get_slots_by_date_and_criteria,
    parse_date_query_to_range, has_date_reference, release_slot, reserve_slot,
)
from src.config.settings import settings
from src.utils.appointment_time import CLINIC_TIMEZONE
from src.control.agents.tools.registration_tools import is_closing_or_thanks
from src.data.repositories.conversation_repository import ConversationRepository
from src.core.exceptions import SlotUnavailableError
from src.control.agents.tools import clinic_directory
from src.control.agents.nodes.booking_helpers import (
    _clean_loc, _clean_slot_time, _extract_name_and_email, _extract_time_of_day,
    _extract_time_window, _format_slot_time_str, _match_branch, _match_doctor,
)
from src.control.agents.nodes._booking_execution import _execute_booking
from src.control.agents.nodes._booking_held_slot import handle_held_slot
from src.control.agents.nodes._booking_discovery import discover_booking_slots

logger = logging.getLogger(__name__)


async def _recover_from_slot_conflict(state, db, *, requested_date=None):
    """Refresh availability after another patient takes the selected slot."""
    selected = state.get("target_slot_details") or {}
    doctor = selected.get("doctor_name") or state.get("preferred_doctor")
    location = selected.get("location_name") or state.get("preferred_location")
    specialty = selected.get("specialty") or state.get("preferred_specialty")
    date_query = requested_date.isoformat() if requested_date else None

    selected_start = selected.get("start_time")
    if not date_query and selected_start:
        try:
            selected_dt = datetime.fromisoformat(selected_start)
            if selected_dt.tzinfo is None:
                selected_dt = selected_dt.replace(tzinfo=timezone.utc)
            date_query = selected_dt.astimezone(CLINIC_TIMEZONE).date().isoformat()
        except (TypeError, ValueError):
            date_query = None

    criteria = {"doctor_name": doctor, "location_name": location, "specialty": specialty}
    alternatives = await get_slots_by_date_and_criteria(
        db, date_query=date_query, limit=50, **criteria,
    ) if date_query else []
    if not alternatives:
        alternatives = await get_slots_by_date_and_criteria(db, limit=50, **criteria)

    response = {
        "target_slot_id": None,
        "target_slot_details": None,
        "offered_slots": alternatives[:6],
        "awaiting_preferred_date": True,
        "preferred_doctor": doctor,
        "preferred_location": location,
        "preferred_specialty": specialty,
    }
    if alternatives:
        choices = "; ".join(slot["formatted_speech"] for slot in alternatives[:3])
        response["latest_agent_speech"] = (
            "That slot was just taken by another patient. Here are the next available options: "
            f"{choices}. Which one would you like? I will hold it after you choose."
        )
    else:
        response["offered_slots"] = []
        response["latest_agent_speech"] = (
            "That slot was just taken by another patient, and I couldn't find another opening with those "
            "preferences. What other date, doctor, or branch would work for you?"
        )
    return response

async def booking_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip()
    lower_speech = user_speech.lower()
    patient_id = state.get("patient_id")
    convo_id = state.get("conversation_id")
    target_slot = state.get("target_slot_details")
    target_slot_id = state.get("target_slot_id")
    repo = ConversationRepository(db)
    requested_time = _extract_time_of_day(user_speech)
    requested_window = _extract_time_window(user_speech)
    parsed_date_start, parsed_date_end = parse_date_query_to_range(user_speech)
    has_date_in_speech = parsed_date_start is not None

    if has_date_reference(user_speech) and not has_date_in_speech:
        return {
            "awaiting_preferred_date": True,
            "latest_agent_speech": (
                "I couldn't understand that date. Please give me a valid date, such as October 27, "
                "so I can check the correct day."
            ),
        }

    # Date ranges are returned in UTC. Keep the conversational date in the
    # clinic timezone so a date such as Oct 27 is not displayed as Oct 26.
    if parsed_date_start is not None:
        parsed_date_start = parsed_date_start.astimezone(CLINIC_TIMEZONE).date()

    # When the patient is choosing from listed slot times, a bare number such
    # as "10" can mean 10:00, but it can also be a day of the month. Treat it
    # as a time only when exactly one offered slot matches; otherwise ask.
    bare_number = re.fullmatch(r"\s*(?:at\s+)?(\d{1,2})\s*", user_speech, re.IGNORECASE)
    if (
        bare_number
        and state.get("awaiting_preferred_date")
        and state.get("offered_slots")
        and requested_time is None
        and requested_window is None
    ):
        bare_hour = int(bare_number.group(1))
        if 1 <= bare_hour <= 12:
            matches = []
            for slot in state.get("offered_slots") or []:
                slot_dt = datetime.fromisoformat(slot["start_time"])
                if slot_dt.tzinfo is None:
                    slot_dt = slot_dt.replace(tzinfo=timezone.utc)
                local_dt = slot_dt.astimezone(CLINIC_TIMEZONE)
                if local_dt.hour == bare_hour and local_dt.minute == 0:
                    matches.append(slot)
            if len(matches) == 1:
                requested_time = (bare_hour, 0)
                has_date_in_speech = False
                parsed_date_start = None
            else:
                return {
                    "latest_agent_speech": (
                        f"When you say {bare_hour}, do you mean {bare_hour}:00 AM or PM, "
                        "or the day of the month? Please include AM or PM for a time."
                    ),
                }
    alternative_date = None

    # Extract name and email if present anywhere in user_speech
    parsed_name, parsed_email = _extract_name_and_email(user_speech)
    patient_email = state.get("patient_email") or parsed_email
    raw_name = state.get("patient_name")
    patient_name = parsed_name or (raw_name if raw_name and raw_name not in ("Clinic Guest", "Valued Patient") else None)

    if not patient_email and patient_id:
        try:
            from src.data.models.postgres.patient import Patient
            p_obj = await db.get(Patient, uuid.UUID(patient_id))
            if p_obj:
                if p_obj.email:
                    patient_email = p_obj.email
                if not patient_name and p_obj.full_name and p_obj.full_name not in ("Clinic Guest", "Valued Patient"):
                    patient_name = p_obj.full_name
        except Exception:
            pass

    logger.info(
        "Booking turn: speech_len=%d target_slot_id=%s doc=%s specialty=%s location=%s awaiting_date=%s awaiting_email=%s",
        len(user_speech),
        target_slot_id,
        state.get("preferred_doctor"),
        state.get("preferred_specialty"),
        state.get("preferred_location"),
        state.get("awaiting_preferred_date"),
        state.get("awaiting_patient_email"),
    )

    # 0. Check if patient is thanking or closing conversation
    if is_closing_or_thanks(user_speech):
        return {
            "is_completed": True,
            "latest_agent_speech": f"You're very welcome! I am always here to help. Thank you for choosing {settings.CLINIC_NAME}. Have a wonderful day!",
        }

    # 1. Strict One Patient, One Active Slot Check
    if patient_id and state.get("intent") == "book":
        existing_appt = await check_patient_active_appointment(patient_id, db)
        if existing_appt:
            return {
                "active_appointment_id": existing_appt["appointment_id"],
                "active_appointment_details": existing_appt,
                "target_slot_id": None,
                "target_slot_details": None,
                "offered_slots": [],
                "latest_agent_speech": (
                    f"You already have an active appointment scheduled for "
                    f"{existing_appt['formatted_speech']}. "
                    "Our clinic allows one active appointment per patient. "
                    "Would you like to reschedule that appointment instead?"
                ),
            }

    # 2. Check if patient asks for another location or different branch
    is_asking_another_location = any(
        phrase in lower_speech
        for phrase in [
            "another location", "can i have another location", "different location",
            "other location", "change location", "another branch", "different branch",
            "other branch", "change branch", "switch branch", "switch location",
            "different clinic", "other clinic", "any other location", "any other branch",
        ]
    ) or (
        any(w in lower_speech for w in ["another", "different", "other", "change", "switch"])
        and any(w in lower_speech for w in ["branch", "branches", "location", "locations", "place", "clinic"])
    )

    if is_asking_another_location:
        if target_slot_id:
            await release_slot(target_slot_id, db)
        spec = state.get("preferred_specialty")
        if spec:
            avail_branches = get_branches_for_specialty(spec)
            branch_str = clinic_directory.join_names(avail_branches) or "our other"
            speech = (
                f"{clinic_directory.branches_sentence()} "
                f"For {spec}, doctors are available at our {branch_str} branches. Which branch would you prefer?"
            )
        else:
            speech = (
                f"{clinic_directory.branches_sentence()} "
                "Which branch or doctor would you prefer?"
            )
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "preferred_doctor": None,
            "preferred_location": None,
            "awaiting_preferred_date": False,
            "awaiting_patient_email": False,
            "latest_agent_speech": speech,
        }

    # Handle common informational questions instead of treating every reply
    # to a proposed slot as a confirmation or a rejection.
    if any(phrase in lower_speech for phrase in ("opening hours", "clinic hours", "what time do you open", "when do you close")):
        return {
            "latest_agent_speech": (
                f"Our clinic is open from {settings.CLINIC_HOURS_START}:00 to "
                f"{settings.CLINIC_HOURS_END}:00. Would you like a slot during those hours?"
            ),
        }

    is_asking_another_doctor = any(
        phrase in lower_speech
        for phrase in (
            "another doctor", "different doctor", "other doctor", "any other doctor",
            "change doctor", "switch doctor", "someone else", "different physician",
        )
    )
    if is_asking_another_doctor and target_slot:
        current_doctor = target_slot.get("doctor_name")
        current_location = target_slot.get("location_name") or state.get("preferred_location")
        specialty = target_slot.get("specialty") or state.get("preferred_specialty")
        if target_slot_id:
            await release_slot(target_slot_id, db)
        options = await get_slots_by_specialty_and_location(
            specialty, current_location, db, limit=50
        ) if specialty and current_location else []
        alternatives = [s for s in options if s.get("doctor_name") != current_doctor]
        doctors = list(dict.fromkeys(s["doctor_name"] for s in alternatives))
        if doctors:
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "preferred_doctor": None,
                "preferred_location": current_location,
                "preferred_specialty": specialty,
                "awaiting_preferred_date": False,
                "latest_agent_speech": (
                    f"Other {specialty} doctors with openings at our {_clean_loc(current_location)} branch are "
                    f"{', '.join(doctors)}. Which doctor would you prefer?"
                ),
            }
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "preferred_doctor": None,
            "preferred_location": current_location,
            "preferred_specialty": specialty,
            "awaiting_preferred_date": True,
            "latest_agent_speech": (
                f"I couldn't find another {specialty or 'doctor'} with an opening at that branch. "
                "Would you like me to check another branch or date?"
            ),
        }

    # 3. Check if patient asks for an alternative slot / different time / different date
    is_asking_alternative = any(
        phrase in lower_speech
        for phrase in [
            "another slot",
            "alternative slot",
            "alternative time",
            "different time",
            "different slot",
            "another time",
            "other time",
            "other slot",
            "another day",
            "different day",
            "other timing",
            "another timing",
            "alternative timing",
            "other slots",
            "different date",
            "another date",
            "change the slot",
            "change time",
            "alternative",
            "alternatives",
        ]
    ) or (
        any(w in lower_speech for w in ["another", "different", "other"])
        and any(w in lower_speech for w in ["slot", "slots", "time", "times", "date", "dates", "timing", "timings"])
    )

    if is_asking_alternative:
        doc = (target_slot.get("doctor_name") if target_slot else None) or state.get("preferred_doctor")
        loc = (target_slot.get("location_name") if target_slot else None) or state.get("preferred_location")
        spec = (target_slot.get("specialty") if target_slot else None) or state.get("preferred_specialty")
        if target_slot:
            try:
                held_dt = datetime.fromisoformat(target_slot["start_time"])
                if held_dt.tzinfo is None:
                    held_dt = held_dt.replace(tzinfo=timezone.utc)
                held_local = held_dt.astimezone(CLINIC_TIMEZONE)
                if not has_date_in_speech and requested_time is None and requested_window is None:
                    await release_slot(target_slot_id, db)
                    alternatives = await get_slots_by_date_and_criteria(
                        db,
                        date_query=held_local.date().isoformat(),
                        doctor_name=doc,
                        location_name=loc,
                        specialty=spec,
                        limit=10,
                    )
                    alternatives = [s for s in alternatives if s.get("slot_id") != target_slot_id]
                    if alternatives:
                        times = [_clean_slot_time(s["start_time"]) for s in alternatives[:6]]
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "awaiting_patient_email": False,
                            "preferred_doctor": doc,
                            "preferred_location": loc,
                            "preferred_specialty": spec,
                            "preferred_date": held_local.date().isoformat(),
                            "latest_agent_speech": (
                                f"Here are other available times on {held_local.strftime('%A, %B %d')}: "
                                f"{', '.join(times)}. Which time would you prefer?"
                            ),
                        }
                elif target_slot_id:
                    await release_slot(target_slot_id, db)
                    alternative_date = held_local.date()
                    target_slot_id = None
                    target_slot = None
            except (KeyError, ValueError, TypeError):
                pass
        if has_date_in_speech or requested_time is not None or requested_window is not None:
            state["preferred_doctor"] = doc
            state["preferred_location"] = loc
            state["preferred_specialty"] = spec
        else:
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "awaiting_preferred_date": True,
                "awaiting_patient_email": False,
                "preferred_doctor": doc,
                "preferred_location": loc,
                "preferred_specialty": spec,
                "latest_agent_speech": "Certainly! What date or time range would work better for you?",
            }

    # 4. If awaiting patient email/name to finalize booking
    if state.get("awaiting_patient_email") and target_slot and target_slot_id:
        user_wants_skip = any(
            phrase in lower_speech
            for phrase in [
                "skip", "no email", "don't have", "dont have", "no", "none",
                "i don't have", "i dont have", "without email", "later", "no thanks"
            ]
        )
        effective_name = patient_name or state.get("patient_name") or "Valued Patient"
        effective_email = patient_email

        if effective_email or user_wants_skip or parsed_name:
            return await _execute_booking(
                target_slot_id=target_slot_id,
                target_slot=target_slot,
                patient_id=patient_id,
                patient_phone=state.get("patient_phone"),
                patient_name=effective_name,
                patient_email=effective_email if not user_wants_skip else None,
                convo_id=convo_id,
                appointment_type_name=state.get("preferred_appointment_type"),
                repo=repo,
                db=db,
            )
        else:
            if any(w in lower_speech for w in ["cancel", "don't want", "stop"]):
                await release_slot(target_slot_id, db)
                return {
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "awaiting_patient_email": False,
                    "latest_agent_speech": "I have cancelled that reservation. How else can I help you?",
                }
            return {
                "awaiting_patient_email": True,
                "target_slot_id": target_slot_id,
                "target_slot_details": target_slot,
                "latest_agent_speech": (
                    "Could you please provide your full name and email address so I can send your appointment confirmation? "
                    "Or say 'skip' to proceed without an email."
                ),
            }

    # An explicit date changes the requested day; release today's tentative
    # hold and let the date search handle the new request.
    if target_slot_id and has_date_in_speech:
        await release_slot(target_slot_id, db)
        target_slot_id = None
        target_slot = None

    try:
        held_result = await handle_held_slot(
            state=state, db=db, user_speech=user_speech, lower_speech=lower_speech,
            target_slot=target_slot, target_slot_id=target_slot_id,
            requested_time=requested_time, requested_window=requested_window,
            has_date_in_speech=has_date_in_speech, patient_id=patient_id,
            patient_name=patient_name, patient_email=patient_email, convo_id=convo_id, repo=repo,
        )
        if held_result is not None:
            return held_result

        return await discover_booking_slots(
            state=state, db=db, user_speech=user_speech, lower_speech=lower_speech,
            requested_time=requested_time, requested_window=requested_window,
            has_date_in_speech=has_date_in_speech, parsed_date_start=parsed_date_start,
            alternative_date=alternative_date,
        )
    except SlotUnavailableError:
        logger.info("Selected booking slot became unavailable; refreshing options for conversation=%s", convo_id)
        return await _recover_from_slot_conflict(state, db, requested_date=parsed_date_start)
