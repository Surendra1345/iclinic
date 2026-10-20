"""Date, doctor, branch and specialty slot discovery for booking."""
import re
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.tools.appointment_time import CLINIC_TIMEZONE
from src.control.agents.tools.slot_tools import (
    get_slots_by_date_and_criteria, get_slots_by_doctor, get_slots_by_specialty_and_location,
    get_specialties_for_branch, get_branch_doctors_info, get_branches_for_specialty, reserve_slot,
)
from src.control.agents.nodes.booking_helpers import _clean_loc, _clean_slot_time, _extract_time_of_day, _format_slot_time_str, _match_branch, _match_doctor

async def discover_booking_slots(
    *, state, db, user_speech, lower_speech, requested_time, requested_window,
    has_date_in_speech, parsed_date_start, alternative_date,
):
    """Handle date, doctor, branch, specialty slot discovery and fallback."""
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
                limit=50,
            )
            if not slots and doc:
                slots = await get_slots_by_date_and_criteria(
                    db,
                    date_query=date_query,
                    doctor_name=doc,
                    limit=50,
                )
            if not slots and loc:
                slots = await get_slots_by_date_and_criteria(
                    db,
                    date_query=date_query,
                    location_name=loc,
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
                        times = [_clean_slot_time(s["start_time"]) for s in slots[:6]]
                        requested = f"{requested_time[0]:02d}:{requested_time[1]:02d}"
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "preferred_doctor": doc,
                            "preferred_location": loc,
                            "preferred_specialty": spec,
                            "preferred_date": parsed_date_start.isoformat(),
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
                speech = (
                    f"I'm sorry, we don't have any openings on {parsed_date_start.strftime('%B %d')} "
                    f"for {desc}. Would you like to check another date or another branch?"
                )
                return {
                    "target_slot_id": None,
                    "target_slot_details": None,
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

    active_specialty = specialty_match or state.get("preferred_specialty")
    mentioned_branch = _match_branch(user_speech)
    named_doctor = _match_doctor(user_speech)

    # 8. Patient specifies a Doctor by name
    if named_doctor:
        loc = mentioned_branch or state.get("preferred_location")
        slots = await get_slots_by_date_and_criteria(
            db,
            doctor_name=named_doctor,
            location_name=loc,
            limit=3,
        )
        if not slots:
            slots = await get_slots_by_doctor(named_doctor, db, limit=3)

        if slots:
            first_slot = slots[0]
            await reserve_slot(first_slot["slot_id"], db)
            formatted_time = _format_slot_time_str(first_slot["start_time"])
            speech = (
                f"I have an opening with {first_slot['doctor_name']} at our "
                f"{_clean_loc(first_slot['location_name'])} branch on {formatted_time}. "
                f"Shall I go ahead and book this appointment for you?"
            )
            return {
                "target_slot_id": first_slot["slot_id"],
                "target_slot_details": first_slot,
                "preferred_doctor": first_slot["doctor_name"],
                "preferred_location": first_slot["location_name"],
                "preferred_specialty": first_slot["specialty"],
                "latest_agent_speech": speech,
            }
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
                avail_text = ", ".join(avail_branches[:-1]) + f", or {avail_branches[-1]}" if len(avail_branches) > 1 else (avail_branches[0] if avail_branches else "our other")
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
                slots = await get_slots_by_specialty_and_location(active_specialty, mentioned_branch, db)
                if slots:
                    first_slot = slots[0]
                    await reserve_slot(first_slot["slot_id"], db)
                    time_str = _format_slot_time_str(first_slot["start_time"])
                    speech = (
                        f"For {active_specialty} at our {_clean_loc(first_slot['location_name'])} branch, "
                        f"I have an opening with {first_slot['doctor_name']} on {time_str}. "
                        f"Shall I go ahead and book this appointment for you?"
                    )
                    return {
                        "target_slot_id": first_slot["slot_id"],
                        "target_slot_details": first_slot,
                        "preferred_specialty": active_specialty,
                        "preferred_location": first_slot["location_name"],
                        "preferred_doctor": first_slot["doctor_name"],
                        "latest_agent_speech": speech,
                    }
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
            avail_text = ", ".join(avail_branches[:-1]) + f", and {avail_branches[-1]}" if len(avail_branches) > 1 else (avail_branches[0] if avail_branches else "our other")
            speech = (
                f"City Care Clinic has four branches in Chennai: Anna Nagar, T. Nagar, Velachery, and Tambaram. "
                f"For {active_specialty}, doctors are available at our {avail_text} branches. Which branch would you prefer?"
            )
        else:
            speech = "City Care Clinic has four branches in Chennai: Anna Nagar, T. Nagar, Velachery, and Tambaram. Which branch or doctor would you prefer?"
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
                slots = await get_slots_by_specialty_and_location(specialty_match, loc, db)
                if slots:
                    first_slot = slots[0]
                    await reserve_slot(first_slot["slot_id"], db)
                    time_str = _format_slot_time_str(first_slot["start_time"])
                    speech = (
                        f"For {specialty_match} at our {_clean_loc(first_slot['location_name'])} branch, "
                        f"I have an opening with {first_slot['doctor_name']} on {time_str}. "
                        f"Shall I go ahead and book this appointment for you?"
                    )
                    return {
                        "target_slot_id": first_slot["slot_id"],
                        "target_slot_details": first_slot,
                        "preferred_specialty": specialty_match,
                        "preferred_location": first_slot["location_name"],
                        "preferred_doctor": first_slot["doctor_name"],
                        "latest_agent_speech": speech,
                    }
            else:
                avail_branches = get_branches_for_specialty(specialty_match)
                avail_text = ", ".join(avail_branches[:-1]) + f", or {avail_branches[-1]}" if len(avail_branches) > 1 else (avail_branches[0] if avail_branches else "our other")
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
        avail_text = ", ".join(avail_branches[:-1]) + f", and {avail_branches[-1]}" if len(avail_branches) > 1 else "our clinic branches"
        is_direct_specialty = any(w in lower_speech for w in [
            "general consultation", "consultation", "checkup", "general checkup",
            "medicine", "cardiology", "dermatology", "orthopedics", "pediatrics",
            "gynecology", "ent", "physician", "doctor"
        ])
        if is_direct_specialty:
            speech = f"For {specialty_match}, which clinic branch would you prefer? We have branches in Anna Nagar, T. Nagar, Velachery, and Tambaram."
        else:
            speech = f"For those symptoms, {specialty_match} would be the appropriate specialty. Which clinic branch would you prefer? We have branches in Anna Nagar, T. Nagar, Velachery, and Tambaram."
        return {
            "preferred_specialty": specialty_match,
            "latest_agent_speech": speech,
        }

    # 12. Fallback prompt
    return {
        "latest_agent_speech": "Sure! Which clinic branch or doctor would you prefer, and what date works best for you?",
    }
