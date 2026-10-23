"""Conversation handling for a tentatively held booking slot."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.appointment_time import CLINIC_TIMEZONE
from src.control.agents.tools.slot_tools import get_slots_by_date_and_criteria, get_slots_by_doctor, get_slots_by_location, get_slots_by_specialty_and_location, release_slot, reserve_slot
from src.control.agents.nodes.booking_helpers import _clean_loc, _clean_slot_time, _extract_name_and_email, _extract_time_of_day, _format_slot_time_str, _match_branch
from src.control.agents.nodes._booking_execution import _execute_booking
from src.control.agents.nodes.dialogue_guardrails import is_explicit_confirmation

logger = logging.getLogger(__name__)

async def handle_held_slot(
    *, state, db, user_speech, lower_speech, target_slot, target_slot_id,
    requested_time, requested_window, has_date_in_speech, patient_id,
    patient_name, patient_email, convo_id, repo,
):
    """Handle dialogue about a tentatively held booking slot; return None to continue."""
    # 5. Check currently held slot
    if target_slot and target_slot_id:
        new_branch = _match_branch(user_speech)
        current_loc = _clean_loc(target_slot.get("location_name"))
        if new_branch and _clean_loc(new_branch) != current_loc:
            # User mentioned another branch: release current held slot and clear doc so branch handling processes it
            await release_slot(target_slot_id, db)
            target_slot = None
            target_slot_id = None
        else:
            # Check if patient specified a specific time of day
            req_time = _extract_time_of_day(user_speech)
            slot_time_iso = target_slot.get("start_time", "")
            st_local = None
            current_time = None
            if slot_time_iso:
                try:
                    st_dt = datetime.fromisoformat(slot_time_iso)
                    if st_dt.tzinfo is None:
                        st_dt = st_dt.replace(tzinfo=timezone.utc)
                    st_local = st_dt.astimezone(CLINIC_TIMEZONE)
                    current_time = (st_local.hour, st_local.minute)
                except Exception:
                    pass

            has_confirm_word = is_explicit_confirmation(user_speech)

            # If patient specified a time of day
            if (req_time is not None or requested_window is not None) and current_time is not None and st_local is not None:
                if req_time is not None and req_time == current_time and requested_window is None:
                    if not has_confirm_word:
                        return {
                            "target_slot_id": target_slot_id,
                            "target_slot_details": target_slot,
                            "latest_agent_speech": (
                                f"That is the {_clean_slot_time(target_slot['start_time'])} slot I have available "
                                f"with {target_slot.get('doctor_name')} at our {_clean_loc(target_slot.get('location_name'))} branch. "
                                "Would you like me to book it?"
                            ),
                        }
                else:
                    # User requested a different time on this date
                    date_query_str = st_local.strftime("%Y-%m-%d")
                    doc_name = target_slot.get("doctor_name")
                    loc_name = target_slot.get("location_name")
                    spec = target_slot.get("specialty") or state.get("preferred_specialty")
                    matching_slots = await get_slots_by_date_and_criteria(
                        db,
                        date_query=date_query_str,
                        doctor_name=doc_name,
                        location_name=loc_name,
                        limit=50,
                    )
                    found_slot = None
                    matching_requested_slots = []
                    for s in matching_slots:
                        s_dt = datetime.fromisoformat(s["start_time"])
                        if s_dt.tzinfo is None:
                            s_dt = s_dt.replace(tzinfo=timezone.utc)
                        s_loc = s_dt.astimezone(CLINIC_TIMEZONE)
                        slot_clock = (s_loc.hour, s_loc.minute)
                        matches = (
                            requested_window[0] <= slot_clock <= requested_window[1]
                            if requested_window is not None
                            else slot_clock == req_time
                        )
                        if matches:
                            matching_requested_slots.append(s)
                    if len(matching_requested_slots) == 1:
                        found_slot = matching_requested_slots[0]

                    if len(matching_requested_slots) > 1:
                        await release_slot(target_slot_id, db)
                        times = [_clean_slot_time(s["start_time"]) for s in matching_requested_slots[:6]]
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "preferred_date": st_local.date().isoformat(),
                            "preferred_doctor": doc_name,
                            "preferred_location": loc_name,
                            "preferred_specialty": spec,
                            "latest_agent_speech": (
                                f"Here are the available times on {st_local.strftime('%A, %B %d')} "
                                f"that match your request: {', '.join(times)}. Which one works for you?"
                            ),
                        }

                    if found_slot:
                        await release_slot(target_slot_id, db)
                        await reserve_slot(found_slot["slot_id"], db)
                        target_slot = found_slot
                        target_slot_id = found_slot["slot_id"]

                        if has_confirm_word:
                            return await _execute_booking(
                                target_slot_id=target_slot_id,
                                target_slot=target_slot,
                                patient_id=patient_id,
                                patient_phone=state.get("patient_phone"),
                                patient_name=patient_name or state.get("patient_name") or "Valued Patient",
                                patient_email=patient_email,
                                convo_id=convo_id,
                                appointment_type_name=state.get("preferred_appointment_type"),
                                repo=repo,
                                db=db,
                            )
                        clean_t = _clean_slot_time(found_slot["start_time"])
                        clean_l = _clean_loc(found_slot["location_name"])
                        speech = (
                            f"I have tentatively held the {clean_t} slot with {found_slot['doctor_name']} "
                            f"at our {clean_l} branch on {st_local.strftime('%A, %B %d')}. "
                            f"Shall I go ahead and book this appointment for you?"
                        )
                        return {
                            "target_slot_id": target_slot_id,
                            "target_slot_details": target_slot,
                            "preferred_doctor": found_slot["doctor_name"],
                            "preferred_location": found_slot["location_name"],
                            "preferred_specialty": found_slot["specialty"],
                            "preferred_date": found_slot["start_time"],
                            "latest_agent_speech": speech,
                        }
                    else:
                        await release_slot(target_slot_id, db)
                        avail_times = []
                        for s in matching_slots[:4]:
                            s_dt = datetime.fromisoformat(s["start_time"])
                            if s_dt.tzinfo is None:
                                s_dt = s_dt.replace(tzinfo=timezone.utc)
                            avail_times.append(s_dt.astimezone(CLINIC_TIMEZONE).strftime("%I:%M %p"))
                        req_time_str = (
                            f"between {requested_window[0][0]:02d}:{requested_window[0][1]:02d} and "
                            f"{requested_window[1][0]:02d}:{requested_window[1][1]:02d}"
                            if requested_window is not None
                            else f"{req_time[0]:02d}:{req_time[1]:02d}"
                        )
                        if avail_times:
                            times_str = ", ".join(avail_times)
                            speech = (
                                f"I'm sorry, I couldn't find a time {req_time_str} on {st_local.strftime('%A, %B %d')}. "
                                f"We have available slots at {times_str} with {doc_name}. Which time would you prefer?"
                            )
                        else:
                            speech = (
                                f"I'm sorry, I couldn't find a time {req_time_str} on {st_local.strftime('%A, %B %d')}. "
                                f"Would you like to check another date or time?"
                            )
                        return {
                            "target_slot_id": None,
                            "target_slot_details": None,
                            "awaiting_preferred_date": True,
                            "preferred_date": st_local.date().isoformat(),
                            "preferred_doctor": doc_name,
                            "preferred_location": loc_name,
                            "preferred_specialty": spec,
                            "latest_agent_speech": speech,
                        }

            has_inquiry_or_negation = any(
                w in lower_speech
                for w in [
                    "no", "don't", "cancel", "not", "other", "another", "different",
                    "alternative", "where is", "address of", "which area", "?",
                    "what", "can i", "could you", "who"
                ]
            )

            # 5a. Patient confirms the booking
            if has_confirm_word and not has_inquiry_or_negation:
                raw_parsed_name, raw_parsed_email = _extract_name_and_email(user_speech)
                current_name = raw_parsed_name or patient_name or state.get("patient_name")
                current_email = raw_parsed_email or patient_email or state.get("patient_email")

                if patient_id:
                    try:
                        from src.data.models.postgres.patient import Patient
                        p_obj = await db.get(Patient, uuid.UUID(patient_id))
                        if p_obj:
                            if p_obj.email:
                                current_email = p_obj.email
                            if p_obj.full_name and p_obj.full_name not in ("Clinic Guest", "Valued Patient"):
                                current_name = p_obj.full_name
                    except Exception:
                        pass

                needs_name = not current_name or current_name.strip() in ("Clinic Guest", "Valued Patient")
                needs_email = not current_email

                if needs_name and needs_email:
                    return {
                        "awaiting_patient_email": True,
                        "target_slot_id": target_slot_id,
                        "target_slot_details": target_slot,
                        "preferred_doctor": target_slot.get("doctor_name"),
                        "preferred_location": target_slot.get("location_name"),
                        "latest_agent_speech": (
                            "I would be happy to book that for you! Could you please provide your full name and email address "
                            "so I can complete your registration and send your appointment confirmation?"
                        ),
                    }
                elif needs_email:
                    return {
                        "awaiting_patient_email": True,
                        "target_slot_id": target_slot_id,
                        "target_slot_details": target_slot,
                        "preferred_doctor": target_slot.get("doctor_name"),
                        "preferred_location": target_slot.get("location_name"),
                        "latest_agent_speech": (
                            "I would be happy to book that for you! Could you please provide your email address "
                            "so I can send your appointment confirmation?"
                        ),
                    }

                return await _execute_booking(
                    target_slot_id=target_slot_id,
                    target_slot=target_slot,
                    patient_id=patient_id,
                    patient_phone=state.get("patient_phone"),
                    patient_name=current_name or "Valued Patient",
                    patient_email=current_email,
                    convo_id=convo_id,
                    appointment_type_name=state.get("preferred_appointment_type"),
                    repo=repo,
                    db=db,
                )

            # 5b. Patient asks about clinic branch / address of currently offered slot
            if any(w in lower_speech for w in ["where is", "location of", "what is the address", "address of", "which area"]):
                loc_name = target_slot.get("location_name") or "clinic"
                loc_addr = target_slot.get("location_address") or ""
                doc_name = target_slot.get("doctor_name", "The doctor")
                addr_phrase = f" at {loc_addr}" if loc_addr else ""
                speech = (
                    f"{doc_name} is located at our {loc_name} branch{addr_phrase}. "
                    f"Shall I go ahead and book this appointment for you?"
                )
                return {
                    "target_slot_id": target_slot_id,
                    "target_slot_details": target_slot,
                    "latest_agent_speech": speech,
                }

            # 5c. Patient rejects the currently offered slot
            if any(w in lower_speech for w in ["no", "cancel", "don't want", "stop"]):
                await release_slot(target_slot_id, db)
                return {
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "latest_agent_speech": "I have cancelled that reservation. How else can I help you?",
                }

            # 5d. Patient asks for alternative slots / other times while a slot is tentatively held
            is_asking_alt = any(
                phrase in lower_speech
                for phrase in [
                    "another slot", "alternative slot", "alterantive slot", "other slot", "different slot",
                    "another time", "different time", "other time", "different day", "another day",
                    "other slots", "alternative times", "alternative slots", "different timing",
                    "another timing", "any other", "any alternative", "show me other", "what other",
                    "what else", "other options", "alternative options"
                ]
            ) or (
                any(w in lower_speech for w in ["another", "different", "other", "alternative"])
                and any(w in lower_speech for w in ["slot", "slots", "time", "times", "date", "dates", "timing", "timings"])
            )
            if is_asking_alt:
                await release_slot(target_slot_id, db)
                doc_name = target_slot.get("doctor_name")
                loc_name = target_slot.get("location_name")
                spec = target_slot.get("specialty") or state.get("preferred_specialty")
                alt_slots = []
                if doc_name:
                    all_doc_slots = await get_slots_by_doctor(doc_name, db, limit=10)
                    alt_slots = [s for s in all_doc_slots if s["slot_id"] != target_slot_id]
                if not alt_slots and loc_name:
                    if spec:
                        alt_slots = await get_slots_by_specialty_and_location(spec, loc_name, db, limit=5)
                    else:
                        alt_slots = await get_slots_by_location(loc_name, db, limit=5)
                    alt_slots = [s for s in alt_slots if s["slot_id"] != target_slot_id]
                if alt_slots:
                    choices = "; ".join(s["formatted_speech"] for s in alt_slots[:3])
                    return {
                        "target_slot_id": None,
                        "target_slot_details": None,
                        "offered_slots": alt_slots[:3],
                        "awaiting_preferred_date": True,
                        "preferred_doctor": doc_name,
                        "preferred_location": loc_name,
                        "preferred_specialty": spec,
                        "latest_agent_speech": (
                            f"Here are alternative available slots with {doc_name}: {choices}. "
                            "Which one works best for you?"
                        ),
                    }
                return {
                    "target_slot_id": None,
                    "target_slot_details": None,
                    "offered_slots": [],
                    "awaiting_preferred_date": True,
                    "preferred_doctor": doc_name,
                    "preferred_location": loc_name,
                    "preferred_specialty": spec,
                    "latest_agent_speech": (
                        f"I don't see any other open slots with {doc_name} right now. "
                        "What other date would you like to check, or would you prefer another doctor?"
                    ),
                }

            # Fallback if slot is held and speech is ambiguous
            loc_name = _clean_loc(target_slot.get("location_name"))
            doc_name = target_slot.get("doctor_name", "the doctor")
            slot_time = _format_slot_time_str(target_slot.get("start_time", ""))
            return {
                "target_slot_id": target_slot_id,
                "target_slot_details": target_slot,
                "latest_agent_speech": (
                    f"I currently have an appointment tentatively held with {doc_name} at our {loc_name} branch on {slot_time}. "
                    f"Shall I go ahead and book this appointment for you, or would you like to check a different date or time?"
                ),
            }


        return None


