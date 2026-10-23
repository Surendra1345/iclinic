"""Date, doctor, branch and specialty slot discovery for booking."""
import difflib
import re
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.appointment_time import CLINIC_TIMEZONE
from src.control.agents.tools.slot_tools import (
    get_slots_by_date_and_criteria,
    get_specialties_for_branch, get_branch_doctors_info, get_branches_for_specialty, reserve_slot,
)
from src.control.agents.tools import clinic_directory
from src.control.agents.nodes.booking_helpers import _clean_loc, _clean_slot_time, _extract_time_of_day, _format_slot_time_str, _match_branch, _match_doctor


def _slot_offer_response(
    slots: list[dict[str, Any]], *, doctor=None, location=None, specialty=None,
    requested_time=None, requested_window=None,
):
    candidates = slots
    time_requested = requested_time is not None or requested_window is not None
    if time_requested:
        candidates = []
        for slot in slots:
            slot_dt = datetime.fromisoformat(slot["start_time"])
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=timezone.utc)
            local_clock = slot_dt.astimezone(CLINIC_TIMEZONE).time()
            clock = (local_clock.hour, local_clock.minute)
            if requested_time is not None and clock == requested_time:
                candidates.append(slot)
            elif requested_window is not None and requested_window[0] <= clock <= requested_window[1]:
                candidates.append(slot)
    offered = (candidates or slots)[:6]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for slot in offered:
        key = (str(slot.get("doctor_name") or "A doctor"), _clean_loc(slot.get("location_name")))
        grouped.setdefault(key, []).append(slot)

    group_labels = []
    for (doctor_name, branch), doctor_slots in grouped.items():
        local_datetimes = []
        for slot in doctor_slots:
            slot_dt = datetime.fromisoformat(slot["start_time"])
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=timezone.utc)
            local_datetimes.append(slot_dt.astimezone(CLINIC_TIMEZONE))
        same_date = len({value.date() for value in local_datetimes}) == 1
        if same_date:
            date_label = local_datetimes[0].strftime("%A, %B %d")
            times = ", ".join(value.strftime("%I:%M %p").lstrip("0") for value in local_datetimes)
            availability = f"on {date_label}: {times}"
        else:
            options = "; ".join(
                value.strftime("%A, %B %d at %I:%M %p").replace(" at 0", " at ")
                for value in local_datetimes
            )
            availability = options
        group_labels.append(f"{doctor_name} at {branch} has openings {availability}")

    availability_text = "; ".join(group_labels)
    if time_requested and not candidates:
        answer = f"I couldn't find a slot at your requested time. Other available appointments are: {availability_text}."
    else:
        answer = f"Available appointments are: {availability_text}."
    return {
        "target_slot_id": None,
        "target_slot_details": None,
        "offered_slots": offered,
        "awaiting_preferred_date": True,
        "preferred_doctor": doctor,
        "preferred_location": location,
        "preferred_specialty": specialty,
        "latest_agent_speech": answer + " Which date and time would you prefer? I will hold one after you choose it.",
    }


def _branch_availability_response(
    slots: list[dict[str, Any]], *, location: str, specialty: str,
) -> dict[str, Any]:
    """Name available clinicians once, then ask for the patient's preferred date/time."""
    doctors = list(dict.fromkeys(
        str(slot.get("doctor_name") or "Doctor") for slot in slots if slot.get("doctor_name")
    ))
    branch = _clean_loc(location)
    if len(doctors) == 1:
        doctor = doctors[0]
        if not doctor.lower().startswith("dr."):
            doctor = f"Dr. {doctor}"
        speech = (
            f"For {specialty} at our {branch} branch, {doctor} is available. "
            "What date and time would you prefer?"
        )
        preferred_doctor = doctors[0]
    else:
        formatted_doctors = [
            name if name.lower().startswith("dr.") else f"Dr. {name}"
            for name in doctors
        ]
        if len(formatted_doctors) == 2:
            doctor_list = " and ".join(formatted_doctors)
        elif len(formatted_doctors) > 2:
            doctor_list = ", ".join(formatted_doctors[:-1]) + f", and {formatted_doctors[-1]}"
        else:
            doctor_list = formatted_doctors[0] if formatted_doctors else "our doctors"
        speech = (
            f"For {specialty} at our {branch} branch, available doctors are {doctor_list}. "
            "Which doctor, date, and time would you prefer?"
        )
        preferred_doctor = None
    return {
        "target_slot_id": None,
        "target_slot_details": None,
        "offered_slots": [],
        "awaiting_preferred_date": True,
        "preferred_doctor": preferred_doctor,
        "preferred_location": location,
        "preferred_specialty": specialty,
        "latest_agent_speech": speech,
    }


async def _discover_slots_for_request(
    db: AsyncSession,
    *,
    doctor_name=None,
    location_name=None,
    specialty=None,
    requested_time=None,
    requested_window=None,
    limit: int = 6,
):
    """Query requested clock constraints before limiting; fetch alternatives only if needed."""
    criteria = {
        "doctor_name": doctor_name,
        "location_name": location_name,
        "specialty": specialty,
    }
    slots = await get_slots_by_date_and_criteria(
        db,
        requested_time=requested_time,
        requested_window=requested_window,
        limit=limit,
        **criteria,
    )
    if not slots and (requested_time is not None or requested_window is not None):
        slots = await get_slots_by_date_and_criteria(db, limit=limit, **criteria)
    return slots

async def discover_booking_slots(
    *, state, db, user_speech, lower_speech, requested_time, requested_window,
    has_date_in_speech, parsed_date_start, alternative_date,
):
    """Handle date, doctor, branch, specialty slot discovery and fallback."""
    # A non-date-specific offer is informational only. Hold a slot only after
    # the patient identifies one of the actual options by its time.
    offered_slots = state.get("offered_slots") or []
    if offered_slots and not has_date_in_speech and (requested_time is not None or requested_window is not None):
        matches = []
        for slot in offered_slots:
            slot_dt = datetime.fromisoformat(slot["start_time"])
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=timezone.utc)
            local_dt = slot_dt.astimezone(CLINIC_TIMEZONE)
            clock = (local_dt.hour, local_dt.minute)
            if requested_time is not None and clock == requested_time:
                matches.append(slot)
            elif requested_window is not None and requested_window[0] <= clock <= requested_window[1]:
                matches.append(slot)
        if len(matches) == 1:
            chosen = matches[0]
            await reserve_slot(chosen["slot_id"], db)
            return {
                "target_slot_id": chosen["slot_id"],
                "target_slot_details": chosen,
                "offered_slots": [],
                "preferred_doctor": chosen["doctor_name"],
                "preferred_location": chosen["location_name"],
                "preferred_specialty": chosen["specialty"],
                "preferred_date": chosen["start_time"],
                "awaiting_preferred_date": False,
                "latest_agent_speech": f"I have tentatively held {_format_slot_time_str(chosen['start_time'])} with {chosen['doctor_name']} at {_clean_loc(chosen['location_name'])}. Shall I book it?",
            }
        if len(matches) > 1:
            labels = [_format_slot_time_str(s["start_time"]) for s in matches[:6]]
            return {
                "offered_slots": matches[:6],
                "target_slot_id": None,
                "target_slot_details": None,
                "awaiting_preferred_date": True,
                "latest_agent_speech": (
                    f"I found more than one matching option: {', '.join(labels)}. Which date and time do you mean?"
                ),
            }
        # A requested time range that is absent from the displayed list may
        # still be available later on that same date (for example, afternoon
        # after we initially showed morning slots). Continue to the saved-date
        # database query below instead of repeating the old options.
    # 6. Find slots for an explicit date or previously requested date.
    saved_preferred_date = state.get("preferred_date")
    has_saved_preferred_date = bool(
        state.get("awaiting_preferred_date")
        and (requested_time is not None or requested_window is not None)
        and saved_preferred_date
    )
    if state.get("awaiting_preferred_date") or has_date_in_speech or alternative_date:
        if has_date_in_speech or has_saved_preferred_date or alternative_date:
            if has_saved_preferred_date and not has_date_in_speech:
                try:
                    saved_dt = datetime.fromisoformat(str(saved_preferred_date))
                    parsed_date_start = saved_dt.date()
                except ValueError:
                    parsed_date_start = None
            elif alternative_date and not has_date_in_speech:
                parsed_date_start = alternative_date
            if parsed_date_start is None:
                return {
                    "awaiting_preferred_date": True,
                    "latest_agent_speech": "What date would you prefer? I can then check the available times.",
                }
            doc = _match_doctor(user_speech) or state.get("preferred_doctor")
            loc = _match_branch(user_speech) or state.get("preferred_location")
            spec = state.get("preferred_specialty")
            date_query = user_speech if has_date_in_speech else parsed_date_start.isoformat()

            slots = await get_slots_by_date_and_criteria(
                db,
                date_query=date_query,
                doctor_name=doc,
                location_name=loc,
                specialty=spec,
                requested_time=requested_time,
                requested_window=requested_window,
                limit=50,
            )

            # If the requested clock time is unavailable, check other openings
            # on that same date before offering later dates.
            if not slots and (requested_time is not None or requested_window is not None):
                slots = await get_slots_by_date_and_criteria(
                    db,
                    date_query=parsed_date_start.isoformat(),
                    doctor_name=doc,
                    location_name=loc,
                    specialty=spec,
                    limit=50,
                )

            if slots:
                requested_slots = slots
                if requested_window is not None:
                    start_clock, end_clock = requested_window
                    requested_slots = []
                    for s in slots:
                        s_dt = datetime.fromisoformat(s["start_time"])
                        if s_dt.tzinfo is None:
                            s_dt = s_dt.replace(tzinfo=timezone.utc)
                        s_loc = s_dt.astimezone(CLINIC_TIMEZONE)
                        clock = (s_loc.hour, s_loc.minute)
                        if start_clock <= clock <= end_clock:
                            requested_slots.append(s)

                    if not requested_slots:
                        times = [_clean_slot_time(s["start_time"]) for s in slots[:6]]
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "preferred_doctor": doc,
                            "preferred_location": loc,
                            "preferred_specialty": spec,
                            "preferred_date": parsed_date_start.isoformat(),
                            "offered_slots": slots[:6],
                            "latest_agent_speech": (
                                f"I couldn't find an opening between {start_clock[0]:02d}:{start_clock[1]:02d} and "
                                f"{end_clock[0]:02d}:{end_clock[1]:02d} on {parsed_date_start.strftime('%A, %B %d')}. "
                                f"Other available times are {', '.join(times)}. Which would you prefer?"
                            ),
                        }
                    if len(requested_slots) > 1:
                        times = [_clean_slot_time(s["start_time"]) for s in requested_slots[:6]]
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "preferred_doctor": doc,
                            "preferred_location": loc,
                            "preferred_specialty": spec,
                            "preferred_date": parsed_date_start.isoformat(),
                            "offered_slots": requested_slots[:6],
                            "latest_agent_speech": (
                                f"I found these times within your preferred range on "
                                f"{parsed_date_start.strftime('%A, %B %d')}: {', '.join(times)}. Which one works best?"
                            ),
                        }
                elif requested_time is not None:
                    requested_slots = []
                    for s in slots:
                        s_dt = datetime.fromisoformat(s["start_time"])
                        if s_dt.tzinfo is None:
                            s_dt = s_dt.replace(tzinfo=timezone.utc)
                        s_loc = s_dt.astimezone(CLINIC_TIMEZONE)
                        if (s_loc.hour, s_loc.minute) == requested_time:
                            requested_slots.append(s)
                    if not requested_slots:
                        previously_offered_ids = {
                            str(item.get("slot_id")) for item in offered_slots if item.get("slot_id")
                        }
                        alternatives = [
                            slot for slot in slots
                            if str(slot.get("slot_id")) in previously_offered_ids
                        ] or slots
                        times = [_clean_slot_time(s["start_time"]) for s in alternatives[:6]]
                        requested = f"{requested_time[0]:02d}:{requested_time[1]:02d}"
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "preferred_doctor": doc,
                            "preferred_location": loc,
                            "preferred_specialty": spec,
                            "preferred_date": parsed_date_start.isoformat(),
                            "offered_slots": alternatives[:6],
                            "latest_agent_speech": (
                                f"{requested} isn't available on {parsed_date_start.strftime('%A, %B %d')}. "
                                f"Other available times are {', '.join(times)}. Which would you prefer?"
                            ),
                        }

                if requested_time is None and requested_window is None:
                    times = [_clean_slot_time(s["start_time"]) for s in slots[:6]]
                    return {
                        "target_slot_id": None,
                        "target_slot_details": None,
                        "awaiting_preferred_date": True,
                        "preferred_doctor": doc,
                        "preferred_location": loc,
                        "preferred_specialty": spec,
                        "preferred_date": parsed_date_start.isoformat(),
                        "offered_slots": slots[:6],
                        "latest_agent_speech": (
                            f"I found these available times on {parsed_date_start.strftime('%A, %B %d')}: "
                            f"{', '.join(times)}. Which time would you like?"
                        ),
                    }

                chosen_slot = requested_slots[0]

                await reserve_slot(chosen_slot["slot_id"], db)
                date_label = parsed_date_start.strftime("%A, %B %d")
                clean_branch = _clean_loc(chosen_slot["location_name"])
                clean_chosen_time = _clean_slot_time(chosen_slot["start_time"])
                speech = (
                    f"On {date_label}, I have tentatively held the {clean_chosen_time} slot with {chosen_slot['doctor_name']} "
                    f"at our {clean_branch} branch for you. Shall I go ahead and book it?"
                )

                return {
                    "target_slot_id": chosen_slot["slot_id"],
                    "target_slot_details": chosen_slot,
                    "preferred_doctor": chosen_slot["doctor_name"],
                    "preferred_location": chosen_slot["location_name"],
                    "preferred_specialty": chosen_slot["specialty"],
                    "preferred_date": chosen_slot["start_time"],
                    "awaiting_preferred_date": False,
                    "latest_agent_speech": speech,
                }
            else:
                desc = doc or spec or loc or "that request"
                alt_slots = []
                if doc:
                    alt_slots = await _discover_slots_for_request(
                        db, doctor_name=doc, requested_time=requested_time,
                        requested_window=requested_window,
                    )
                elif spec and loc:
                    alt_slots = await _discover_slots_for_request(
                        db, specialty=spec, location_name=loc, requested_time=requested_time,
                        requested_window=requested_window,
                    )
                elif spec:
                    alt_slots = await _discover_slots_for_request(
                        db, specialty=spec, requested_time=requested_time,
                        requested_window=requested_window,
                    )
                elif loc:
                    alt_slots = await _discover_slots_for_request(
                        db, location_name=loc, requested_time=requested_time,
                        requested_window=requested_window,
                    )

                if alt_slots:
                    choices = "; ".join(s["formatted_speech"] for s in alt_slots[:3])
                    speech = (
                        f"I couldn't find an available slot on {parsed_date_start.strftime('%A, %B %d')} for {desc}. "
                        f"The next available openings are: {choices}. Would any of those work for you?"
                    )
                    return {
                        "target_slot_id": None,
                        "target_slot_details": None,
                        "offered_slots": alt_slots[:3],
                        "awaiting_preferred_date": True,
                        "preferred_doctor": doc,
                        "preferred_location": loc,
                        "preferred_specialty": spec,
                        "latest_agent_speech": speech,
                    }
                speech = (
                    f"I'm sorry, we don't have any openings on {parsed_date_start.strftime('%B %d')} "
                    f"for {desc}. Would you like to check another date or another branch?"
                )
                return {
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "offered_slots": [],
                    "awaiting_preferred_date": True,
                    "preferred_doctor": doc,
                    "preferred_location": loc,
                    "preferred_specialty": spec,
                    "latest_agent_speech": speech,
                }

    # 7. Extract symptoms / specialty
    tokens = set(re.findall(r"\b[a-z]+\b", lower_speech))
    specialty_match = None
    if any(w in tokens for w in ["cardio", "cardiology", "heart", "chest", "bp", "hypertension", "palpitation"]):
        specialty_match = "Cardiology"
    elif any(w in tokens for w in ["derma", "dermatology", "skin", "rash", "itch", "itching", "acne", "hair"]):
        specialty_match = "Dermatology"
    elif any(w in tokens for w in [
        "ortho", "orthopedic", "orthopaedic", "orthopedics", "orthopaedics",
        "bone", "joint", "knee", "back", "shoulder", "fracture", "muscle",
        "ankle", "wrist", "elbow", "hip", "leg", "arm", "foot", "neck",
        "spine", "arthritis", "sprain", "strain", "ligament", "tendon",
        "stiffness", "swelling", "injury"
    ]):
        specialty_match = "Orthopedics"
    elif any(w in tokens for w in ["pediatric", "pediatrics", "child", "kid", "baby", "infant"]):
        specialty_match = "Pediatrics"
    elif any(w in tokens for w in ["ent", "ear", "ears", "nose", "throat", "sinus"]):
        specialty_match = "ENT"
    elif any(w in tokens for w in ["gyn", "gynecology", "pregnancy", "pregnant", "period", "women"]):
        specialty_match = "Gynecology"
    elif any(w in tokens for w in [
        "stomach", "belly", "abdominal", "fever", "cold", "cough", "headache",
        "general", "physician", "infection", "medicine", "digestion", "vomit",
        "checkup", "consultation", "routine", "regular"
    ]):
        specialty_match = "General Medicine"

    if not specialty_match:
        # Tolerate misspelt specialties ("cordiologu") using the specialties that really exist.
        for token in tokens:
            if len(token) >= 5:
                close = difflib.get_close_matches(token, [s.lower() for s in clinic_directory.all_specialties()], n=1, cutoff=0.75)
                if close:
                    specialty_match = next(s for s in clinic_directory.all_specialties() if s.lower() == close[0])
                    break

    active_specialty = specialty_match or state.get("preferred_specialty")
    mentioned_branch = _match_branch(user_speech)
    named_doctor = _match_doctor(user_speech)

    # 8. Patient specifies a Doctor by name
    if named_doctor:
        loc = mentioned_branch or state.get("preferred_location")
        slots = await _discover_slots_for_request(
            db,
            doctor_name=named_doctor,
            location_name=loc,
            requested_time=requested_time,
            requested_window=requested_window,
        )

        if slots:
            return _slot_offer_response(slots, doctor=named_doctor, location=loc, specialty=slots[0].get("specialty"), requested_time=requested_time, requested_window=requested_window)
        else:
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "preferred_doctor": named_doctor,
                "preferred_location": loc,
                "latest_agent_speech": f"I couldn't find any available openings for {named_doctor} right now. Would you like me to check another doctor or branch?",
            }

    # 9. Patient specifies a Branch
    if mentioned_branch:
        if active_specialty:
            branch_specialties = get_specialties_for_branch(mentioned_branch)
            if active_specialty not in branch_specialties:
                # Branch does NOT offer this specialty!
                avail_branches = get_branches_for_specialty(active_specialty)
                avail_text = clinic_directory.join_names(avail_branches, "or") or "our other"
                branch_info = get_branch_doctors_info(mentioned_branch)
                doc_strings = [f"{d['name']} ({d['specialty']})" for d in branch_info["doctors"]]
                docs_text = ", ".join(doc_strings[:-1]) + f", and {doc_strings[-1]}" if len(doc_strings) > 1 else (doc_strings[0] if doc_strings else "")

                speech = (
                    f"Our {mentioned_branch} branch does not have {active_specialty} doctors (available specialties at {mentioned_branch} are {docs_text}). "
                    f"{active_specialty} is available at our {avail_text} branches. "
                    f"Which of these branches would you prefer?"
                )
                return {
                    "preferred_location": None,
                    "preferred_doctor": None,
                    "preferred_specialty": active_specialty,
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "latest_agent_speech": speech,
                }
            else:
                # Branch DOES offer this specialty!
                slots = await _discover_slots_for_request(
                    db, specialty=active_specialty, location_name=mentioned_branch,
                    requested_time=requested_time, requested_window=requested_window,
                )
                if slots:
                    return _branch_availability_response(
                        slots, location=mentioned_branch, specialty=active_specialty,
                    )
                else:
                    return {
                        "preferred_location": mentioned_branch,
                        "preferred_specialty": active_specialty,
                        "awaiting_preferred_date": True,
                        "latest_agent_speech": f"I don't see any immediate openings for {active_specialty} at our {mentioned_branch} branch today. What is your preferred date to visit?",
                    }
        else:
            # Branch mentioned without a known specialty
            branch_info = get_branch_doctors_info(mentioned_branch)
            doctors = branch_info["doctors"]
            if doctors:
                doc_strings = [f"{d['name']} ({d['specialty']})" for d in doctors]
                docs_text = ", ".join(doc_strings[:-1]) + f", and {doc_strings[-1]}" if len(doc_strings) > 1 else doc_strings[0]
                speech = (
                    f"At our {branch_info['branch']} branch, we have {docs_text}. "
                    f"Which doctor or specialty would you like to consult with?"
                )
                return {
                    "preferred_location": branch_info["branch"],
                    "preferred_doctor": None,
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "latest_agent_speech": speech,
                }

    # 10. General question about locations
    is_general_location_question = any(
        phrase in lower_speech
        for phrase in [
            "what are the locations", "where are you located", "which branches",
            "what locations do you have", "clinic locations", "other locations",
            "any other locations", "where can i", "which locations", "what branches",
        ]
    ) or (
        any(word in lower_speech for word in ["locations", "branches", "branch", "location"])
        and any(word in lower_speech for word in ["what", "which", "where", "available", "have", "offer", "options"])
    )
    if is_general_location_question:
        if active_specialty:
            avail_branches = get_branches_for_specialty(active_specialty)
            avail_text = clinic_directory.join_names(avail_branches) or "our other"
            speech = (
                f"{clinic_directory.branches_sentence()} "
                f"For {active_specialty}, doctors are available at our {avail_text} branches. Which branch would you prefer?"
            )
        else:
            speech = f"{clinic_directory.branches_sentence()} Which branch or doctor would you prefer?"
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "preferred_doctor": None,
            "preferred_location": None,
            "latest_agent_speech": speech,
        }

    # 11. Specialty mentioned without a branch in this turn
    if specialty_match:
        loc = state.get("preferred_location")
        if loc:
            branch_specialties = get_specialties_for_branch(loc)
            if specialty_match in branch_specialties:
                slots = await _discover_slots_for_request(
                    db, specialty=specialty_match, location_name=loc,
                    requested_time=requested_time, requested_window=requested_window,
                )
                if slots:
                    return _slot_offer_response(slots, location=loc, specialty=specialty_match, requested_time=requested_time, requested_window=requested_window)
            else:
                avail_branches = get_branches_for_specialty(specialty_match)
                avail_text = clinic_directory.join_names(avail_branches, "or") or "our other"
                return {
                    "preferred_location": None,
                    "preferred_doctor": None,
                    "preferred_specialty": specialty_match,
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "latest_agent_speech": (
                        f"Our {loc} branch does not offer {specialty_match}. "
                        f"{specialty_match} is available at our {avail_text} branches. "
                        f"Which branch would you prefer?"
                    ),
                }

        avail_branches = get_branches_for_specialty(specialty_match)
        avail_text = clinic_directory.join_names(avail_branches) or "our clinic branches"
        is_direct_specialty = any(w in lower_speech for w in [
            "general consultation", "consultation", "checkup", "general checkup",
            "medicine", "physician", "doctor",
        ]) or any(sp.lower() in lower_speech for sp in clinic_directory.all_specialties())
        if is_direct_specialty:
            speech = f"For {specialty_match}, which clinic branch would you prefer? We have branches in {clinic_directory.join_names(clinic_directory.branch_names())}."
        else:
            speech = f"For those symptoms, {specialty_match} would be the appropriate specialty. Which clinic branch would you prefer? We have branches in {clinic_directory.join_names(clinic_directory.branch_names())}."
        return {
            "preferred_specialty": specialty_match,
            "awaiting_preferred_date": True,
            "latest_agent_speech": speech,
        }

    # 12. Fallback prompt
    return {
        "awaiting_preferred_date": True,
        "latest_agent_speech": "Sure! Which clinic branch or doctor would you prefer, and what date works best for you?",
    }
