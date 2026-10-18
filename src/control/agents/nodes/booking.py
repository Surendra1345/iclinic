"""Booking agent node — slot discovery, reservation, and booking confirmation."""
import logging
import uuid
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.agents.state import CallState
from src.control.agents.tools.booking_tools import book_appointment, check_patient_active_appointment
from src.control.agents.tools.slot_tools import (
    get_available_slots,
    get_slots_by_doctor,
    get_slots_by_specialty,
    get_slots_by_location,
    get_slots_by_specialty_and_location,
    get_doctor_options_by_specialty,
    release_slot,
    reserve_slot,
)
from src.constants.enums import ConversationState
from src.data.repositories.conversation_repository import ConversationRepository
from src.observability.metrics import booking_outcomes_total

logger = logging.getLogger(__name__)


async def booking_agent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    user_speech = state.get("latest_user_speech", "").strip().lower()
    patient_id = state.get("patient_id")
    convo_id = state.get("conversation_id")
    target_slot = state.get("target_slot_details")
    target_slot_id = state.get("target_slot_id")
    repo = ConversationRepository(db)
    logger.info(
        "Booking turn: speech=%r target_slot_id=%s specialty=%s location=%s",
        user_speech,
        target_slot_id,
        state.get("preferred_specialty"),
        state.get("preferred_location"),
    )

    # 1. Strict One Patient, One Active Slot Check
    if patient_id:
        existing_appt = await check_patient_active_appointment(patient_id, db)
        if existing_appt:
            return {
                "active_appointment_id": existing_appt["appointment_id"],
                "active_appointment_details": existing_appt,
                "latest_agent_speech": (
                    f"You already have an active appointment scheduled for {existing_appt['formatted_speech']}. "
                    f"Our clinic allows one active appointment per patient. "
                    f"Would you like to reschedule that appointment instead?"
                ),
            }

    # 2. If a slot was offered/reserved and patient is inquiring or confirming
    if target_slot and target_slot_id:
        is_asking_alternative_slot = any(
            phrase in user_speech
            for phrase in [
                "another slot",
                "alternative slot",
                "alternative time",
                "different time",
                "different slot",
                "another time",
                "other time",
                "other slot",
            ]
        ) or (
            "alternative" in user_speech
            or "alternatives" in user_speech
            or "another" in user_speech
        )
        is_asking_alternative_slot = is_asking_alternative_slot and not any(
            phrase in user_speech
            for phrase in ["location", "locations", "branch", "branches"]
        )
        logger.info(
            "Alternative-slot decision: call_speech=%r matched=%s",
            user_speech,
            is_asking_alternative_slot,
        )
        if is_asking_alternative_slot:
            specialty = target_slot.get("specialty") or state.get("preferred_specialty")
            location = target_slot.get("location_name") or state.get("preferred_location")
            await release_slot(target_slot_id, db)

            if specialty and location:
                alternative_slots = await get_slots_by_specialty_and_location(
                    specialty,
                    location,
                    db,
                    limit=10,
                )
            elif specialty:
                alternative_slots = await get_slots_by_specialty(
                    specialty,
                    db,
                    limit=10,
                )
            elif location:
                alternative_slots = await get_slots_by_location(location, db, limit=10)
            else:
                alternative_slots = []

            alternative_slot = next(
                (slot for slot in alternative_slots if slot["slot_id"] != target_slot_id),
                None,
            )
            if alternative_slot:
                await reserve_slot(alternative_slot["slot_id"], db)
                return {
                    "target_slot_id": alternative_slot["slot_id"],
                    "target_slot_details": alternative_slot,
                    "preferred_specialty": specialty,
                    "preferred_location": location,
                    "latest_agent_speech": (
                        f"I have another opening with {alternative_slot['formatted_speech']}. "
                        "Shall I go ahead and book this appointment for you?"
                    ),
                }

            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "preferred_specialty": specialty,
                "preferred_location": location,
                "latest_agent_speech": (
                    "I could not find another available slot for that doctor or specialty. "
                    "Would you like me to check another location or connect you with our front desk?"
                ),
            }

        requested_location = next(
            (
                location
                for location, aliases in {
                    "Anna Nagar": ("anna nagar", "annanagar"),
                    "T. Nagar": ("t nagar", "t. nagar", "tnagar"),
                    "Velachery": ("velachery",),
                    "Tambaram": ("tambaram",),
                }.items()
                if any(alias in user_speech for alias in aliases)
            ),
            None,
        )
        current_location = (target_slot.get("location_name") or "").lower()
        if requested_location and requested_location.lower() not in current_location:
            await release_slot(target_slot_id, db)
            target_slot = None
            target_slot_id = None
            state = {**state, "preferred_location": requested_location}

        # 2a. Check if patient asks for other locations or other branches
        is_asking_other_locations = target_slot_id and any(w in user_speech for w in [
            "other location", "other locations", "other branch", "other branches",
            "different location", "different branch", "another location", "another branch",
            "no other location", "no other locations", "know other location", "know other locations",
            "what other", "any other", "what are the other", "where else", "other options",
            "what about other"
        ])
        if is_asking_other_locations:
            spec = target_slot.get("specialty") or state.get("preferred_specialty") or "General Medicine"
            await release_slot(target_slot_id, db)
            if spec == "General Medicine":
                speech = (
                    "City Care Clinic has branches in Anna Nagar, T. Nagar, Velachery, and Tambaram. "
                    f"For {spec.lower()}, we can check the available doctors at each branch. "
                    "Which branch would you prefer?"
                )
            else:
                speech = (
                    "City Care Clinic has four branches in Chennai: Anna Nagar, T. Nagar, Velachery, and Tambaram. "
                    "Which location or branch would you prefer?"
                )
            return {
                "target_slot_id": None,
                "target_slot_details": None,
                "preferred_specialty": spec,
                "latest_agent_speech": speech,
            }

        # 2b. Patient asks for the location/address of the offered doctor or clinic
        elif target_slot_id and (any(w in user_speech for w in [
            "location of the doctor", "where is the doctor", "what is the location",
            "where is this", "where is it located", "what is the address", "address of the doctor",
            "which area", "where is t nagar"
        ]) or (
            any(w in user_speech for w in ["location", "address", "where", "branch"]) and not any(w in user_speech for w in ["other", "another", "different"])
        )):
            loc_name = target_slot.get("location_name") or "T. Nagar Branch"
            loc_addr = target_slot.get("location_address") or "Chennai"
            doc_name = target_slot.get("doctor_name", "The doctor")
            addr_phrase = f" on {loc_addr}" if loc_addr else ""
            speech = (
                f"{doc_name} is located at our {loc_name}{addr_phrase}. "
                f"Shall I go ahead and book this appointment for you?"
            )
            return {
                "target_slot_id": target_slot_id,
                "target_slot_details": target_slot,
                "latest_agent_speech": speech,
            }

        # 2c. Patient reiterates prior input ("I already said that")
        elif any(w in user_speech for w in ["i already said", "already told", "i said", "like i said", "as i said"]):
            speech = (
                f"My apologies! As discussed, we have an opening with {target_slot.get('formatted_speech')}. "
                f"Shall I go ahead and book this appointment for you?"
            )
            return {
                "target_slot_id": target_slot_id,
                "target_slot_details": target_slot,
                "latest_agent_speech": speech,
            }

        # 2d. Check rejection / change
        elif any(w in user_speech for w in ["no", "cancel", "don't", "different", "another", "change"]):
            await release_slot(target_slot_id, db)
            target_slot = None
            target_slot_id = None

        # 2e. Check genuine confirmation intent (ensure it is NOT an inquiry or question)
        has_confirm_word = any(w in user_speech for w in ["yes", "confirm", "sure", "book it", "please", "go ahead", "okay", "fine", "yep", "that works", "sounds good"])
        has_inquiry_word = any(w in user_speech for w in ["other", "another", "different", "location", "locations", "branch", "where", "?", "what", "can i", "could you"])

        if has_confirm_word and not has_inquiry_word:
            try:
                res = await book_appointment(
                    patient_id_str=patient_id,
                    slot_id_str=target_slot_id,
                    conversation_id_str=convo_id,
                    db=db,
                )
                if convo_id:
                    await repo.update_state(uuid.UUID(convo_id), ConversationState.BOOKED)
                booking_outcomes_total.labels("book", "success").inc()

                speech = (
                    f"Your appointment with {target_slot.get('doctor_name')} at our "
                    f"{target_slot.get('location_name', 'clinic')} on "
                    f"{target_slot.get('formatted_speech')} has been booked! "
                    f"We have sent you a confirmation text."
                )
                return {
                    "booking_confirmed": True,
                    "active_appointment_id": res["appointment_id"],
                    "latest_agent_speech": speech,
                }
            except Exception as e:
                booking_outcomes_total.labels("book", "failed").inc()
                logger.error(f"Booking execution failed: {e}")
                try:
                    await db.rollback()
                    await release_slot(target_slot_id, db)
                except Exception:
                    pass
                return {
                    "handoff_required": True,
                    "handoff_reason": f"Booking failure: {str(e)}",
                    "latest_agent_speech": "I had trouble securing that slot in our system. Let me transfer you to our receptionist to complete your booking.",
                }

    # If patient objects or asks why a doctor was suggested without them giving a reason
    if any(w in user_speech for w in ["didn't tell", "did not tell", "didn't say", "did not say", "why are you suggesting", "no reason", "what cause", "any reason"]):
        if target_slot_id:
            await release_slot(target_slot_id, db)
        return {
            "target_slot_id": None,
            "target_slot_details": None,
            "latest_agent_speech": "My apologies! Could you please let me know what symptoms you are having, or which doctor or specialty you would like to see?",
        }

    # 3. Patient asks generally about clinic locations/branches
    is_location_question = (
        any(
            phrase in user_speech
            for phrase in [
                "what are the locations",
                "where are you located",
                "which branches",
                "what locations do you have",
                "clinic locations",
                "other locations",
                "any other locations",
                "where can i",
                "which locations",
                "what branches",
            ]
        )
        or (
            any(word in user_speech for word in ["locations", "branches", "branch", "location"])
            and any(word in user_speech for word in ["what", "which", "where", "available", "have", "offer", "options"])
        )
    )
    if is_location_question:
        return {
            "latest_agent_speech": "City Care Clinic has four branches in Chennai: Anna Nagar, T. Nagar, Velachery, and Tambaram. Which branch would you prefer, or what symptoms are you experiencing?",
        }

    # 4. Discover available slots by symptoms, doctor, or location
    import re
    tokens = set(re.findall(r"\b[a-z]+\b", user_speech.lower()))
    slots = []
    has_specified_need = False

    # Check preferred location in speech
    preferred_loc = state.get("preferred_location")
    if "anna nagar" in user_speech or "annanagar" in user_speech:
        preferred_loc = "Anna Nagar"
    elif "t nagar" in user_speech or "t. nagar" in user_speech or "tnagar" in user_speech:
        preferred_loc = "T. Nagar"
    elif "velachery" in user_speech:
        preferred_loc = "Velachery"
    elif "tambaram" in user_speech:
        preferred_loc = "Tambaram"

    # Check specialty / doctor
    specialty_match = None
    specialty_was_inferred_from_symptoms = False
    if any(w in tokens for w in ["arjun", "ashwin", "lakshmi"]):
        specialty_match = "General Medicine"
        has_specified_need = True
    elif any(w in tokens for w in ["rajesh", "sandeep", "harish"]):
        specialty_match = "Cardiology"
        has_specified_need = True
    elif any(w in tokens for w in ["priya", "shalini", "nithya"]):
        specialty_match = "Dermatology"
        has_specified_need = True
    elif any(w in tokens for w in ["karthik", "suresh"]):
        specialty_match = "Orthopedics"
        has_specified_need = True
    elif any(w in tokens for w in ["meera", "divya"]):
        specialty_match = "Pediatrics"
        has_specified_need = True
    elif any(w in tokens for w in ["vivek"]):
        specialty_match = "ENT"
        has_specified_need = True
    elif any(w in tokens for w in ["deepa", "ananya"]):
        specialty_match = "Gynecology"
        has_specified_need = True
    elif any(w in tokens for w in ["stomach", "belly", "abdominal", "fever", "cold", "cough", "headache", "general", "physician", "infection", "medicine", "digestion", "vomit", "vomiting"]):
        specialty_match = "General Medicine"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif any(w in tokens for w in ["cardio", "cardiology", "heart", "chest", "bp", "hypertension", "palpitation"]):
        specialty_match = "Cardiology"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif any(w in tokens for w in ["derma", "dermatology", "skin", "rash", "itch", "itching", "acne", "hair"]):
        specialty_match = "Dermatology"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif any(w in tokens for w in [
        "ortho", "orthopedic", "orthopaedic", "orthopedics", "orthopaedics",
        "bone", "joint", "knee", "back", "shoulder", "fracture", "muscle",
        "ankle", "wrist", "elbow", "hip", "leg", "arm", "foot", "neck",
        "spine", "arthritis", "sprain", "strain", "ligament", "tendon",
        "stiffness", "swelling", "injury",
    ]):
        specialty_match = "Orthopedics"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif any(w in tokens for w in ["pediatric", "pediatrics", "child", "kid", "baby", "infant"]):
        specialty_match = "Pediatrics"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif any(w in tokens for w in ["ent", "ear", "ears", "nose", "throat", "sinus"]):
        specialty_match = "ENT"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif any(w in tokens for w in ["gyn", "gynecology", "pregnancy", "pregnant", "period", "women"]):
        specialty_match = "Gynecology"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True
    elif "checkup" in user_speech or "routine check" in user_speech:
        specialty_match = "General Medicine"
        has_specified_need = True
        specialty_was_inferred_from_symptoms = True

    # If no specialty in this turn, restore remembered specialty from previous turn
    if not specialty_match and state.get("preferred_specialty"):
        specialty_match = state.get("preferred_specialty")
        has_specified_need = True

    doctor_question = (
        any(
            phrase in user_speech
            for phrase in [
                "what doctors",
                "which doctors",
                "doctors available",
                "available doctors",
                "doctor available",
                "which doctor",
                "what doctor",
            ]
        )
        or (
            "doctor" in tokens
            and any(word in tokens for word in ["available", "availability", "options", "offer"])
        )
        or "do you have doctors" in user_speech
    )
    named_doctor = (
        "dr " in user_speech
        or any(
            name in tokens
            for name in [
                "arjun", "ashwin", "lakshmi", "rajesh", "sandeep", "harish",
                "priya", "shalini", "nithya", "karthik", "suresh", "meera",
                "divya", "vivek", "deepa", "ananya",
            ]
        )
    )
    explicit_doctor_or_location = preferred_loc is not None or doctor_question or named_doctor

    # Symptoms identify a specialty, but must not silently choose a doctor.
    if specialty_match and specialty_was_inferred_from_symptoms and not explicit_doctor_or_location:
        return {
            "preferred_specialty": specialty_match,
            "latest_agent_speech": (
                f"For those symptoms, {specialty_match} would be the appropriate specialty. "
                "Do you have a preferred clinic location or doctor?"
            ),
        }

    if doctor_question and not preferred_loc:
        doctor_options = (
            await get_doctor_options_by_specialty(specialty_match, db, limit=10)
            if specialty_match
            else await get_available_slots(db, limit=10)
        )
        if not doctor_options:
            return {
                "preferred_specialty": specialty_match,
                "latest_agent_speech": (
                    f"I could not find available {specialty_match or 'doctors'} right now. "
                    "Would you like me to check another specialty or location?"
                ),
            }
        option_text = "; ".join(
            f"{option['doctor_name']} is available at {option['location_name']} {option['formatted_speech'].split(' on ', 1)[-1]}"
            for option in doctor_options
        )
        return {
            "preferred_specialty": specialty_match,
            "latest_agent_speech": (
                f"{f'For {specialty_match}, ' if specialty_match else ''}"
                f"the available options are: {option_text}. "
                "Would you prefer one of these doctors or a particular location?"
            ),
        }

    from src.control.agents.tools.slot_tools import get_slots_by_location, get_slots_by_specialty_and_location

    if specialty_match and preferred_loc:
        slots = await get_slots_by_specialty_and_location(specialty_match, preferred_loc, db)
        if not slots:
            slots = await get_slots_by_specialty(specialty_match, db)
    elif specialty_match:
        slots = await get_slots_by_specialty(specialty_match, db)
    elif preferred_loc:
        slots = await get_slots_by_location(preferred_loc, db)
        has_specified_need = True

    # If patient only stated intent to book without specifying symptoms, doctor, or location
    if not has_specified_need:
        return {
            "latest_agent_speech": "Sure! Could you tell me what symptoms you are experiencing, or which doctor or specialty you would like to see?",
        }

    if not slots:
        return {
            "handoff_required": True,
            "handoff_reason": "No available slots found",
            "latest_agent_speech": "I'm sorry, but we don't have any openings available for that request right now. Let me connect you with our front desk team to check the waitlist.",
        }

    # Present slots and tentatively reserve the first one
    first_slot = slots[0]
    await reserve_slot(first_slot["slot_id"], db)
    if convo_id:
        await repo.update_state(uuid.UUID(convo_id), ConversationState.SLOT_RESERVED)

    speech = (
        f"I have an opening with {first_slot['formatted_speech']}. "
        f"Shall I go ahead and book this appointment for you?"
    )

    return {
        "target_slot_id": first_slot["slot_id"],
        "target_slot_details": first_slot,
        "preferred_specialty": specialty_match,
        "preferred_location": preferred_loc,
        "latest_agent_speech": speech,
    }
