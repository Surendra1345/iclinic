"""Intent detection node — state-aware LLM intent classification with safety guardrails."""
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.control.agents.state import CallState
from src.control.agents.nodes.dialogue_guardrails import (
    is_explicit_confirmation,
    is_explicit_rejection,
    is_repeat_request,
    is_reschedule_confirmation,
)
from src.control.agents.tools.registration_tools import is_closing_or_thanks, is_greeting, validate_dob
from src.control.agents.tools.registration_tools import is_name_correction, is_name_only_candidate, name_from_speech
from src.control.agents.tools.slot_tools import (
    get_slots_by_date_and_criteria,
    has_date_reference,
    parse_date_query_to_range,
)
from src.control.agents.tools.booking_tools import check_patient_active_appointment
from src.control.agents.tools.followup_tools import (
    followup_candidate_prompt,
    get_followup_candidates,
)
from src.control.agents.nodes.booking_helpers import (
    _clean_loc, _extract_time_of_day, _extract_time_window, _format_slot_time_str,
    _match_branch, _match_doctor,
)
from src.utils.appointment_time import CLINIC_TIMEZONE
from src.utils.pii import redact_pii
from src.control.agents.tools.slot_speech import day_availability_speech, period_from_request
from src.data.models.postgres.location import Location
from src.data.models.postgres.provider import Provider
from src.core.services.intent_classification_service import (
    intent_classification_service,
    IntentLabel,
)
from src.core.services.medical_safety_service import is_emergency_report

logger = logging.getLogger(__name__)


def _recent_dialogue_context(state: CallState, current_message: str) -> str:
    """Return a short, identifier-redacted transcript tail for intent resolution."""
    messages = state.get("messages") or []
    tail = []
    current_normalized = " ".join(current_message.lower().split())
    for message in reversed(messages):
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if not content or role not in ("patient", "user", "agent", "assistant"):
            continue
        normalized = " ".join(content.lower().split())
        if role in ("patient", "user") and normalized == current_normalized:
            continue
        content = redact_pii(content, state.get("patient_name"))
        tail.append(("patient" if role in ("patient", "user") else "assistant", content[:350]))
        if len(tail) == 4:
            break
    tail.reverse()
    return "\n".join(f"{role}: {content}" for role, content in tail)


async def _handle_doctor_availability_query(
    db: AsyncSession,
    requested_specialty: Optional[str] = None,
    user_speech: str = "",
) -> Dict[str, Any]:
    """Answers doctor availability questions grounded in database records without converting to booking."""
    doctors = list((await db.scalars(
        select(Provider)
        .options(selectinload(Provider.location))
        .where(Provider.is_active.is_(True))
        .order_by(Provider.full_name)
    )).all())
    known_specialties = {doctor.specialty for doctor in doctors if doctor.specialty}
    lower = user_speech.lower()

    date_was_requested = has_date_reference(user_speech)
    requested_time = _extract_time_of_day(user_speech)
    requested_window = _extract_time_window(user_speech)
    if (requested_time or requested_window) and not date_was_requested:
        return {
            "intent": "faq_response",
            "latest_agent_speech": "Which date should I check for appointment openings at that time?",
        }
    if date_was_requested:
        date_start, date_end = parse_date_query_to_range(user_speech)
        if date_start is None or date_end is None:
            return {
                "intent": "faq_response",
                "latest_agent_speech": "I couldn't understand that date. Please give me a valid date, such as October 27.",
            }
        if not requested_specialty:
            words = re.findall(r"[a-z]+", lower)
            requested_specialty = next(
                (specialty for specialty in known_specialties if specialty.lower() in lower),
                None,
            )
            if not requested_specialty and any(term in lower for term in (
                "general consultation", "general consultant", "general medicine", "general doctor",
            )):
                requested_specialty = next(
                    (item for item in known_specialties if item.lower() == "general medicine"), None
                )
            if not requested_specialty:
                candidates = sorted(known_specialties, key=len, reverse=True)
                fuzzy = [
                    (SequenceMatcher(None, word, specialty.lower()).ratio(), specialty)
                    for word in words for specialty in candidates if len(word) >= 5
                ]
                if fuzzy and max(fuzzy)[0] >= 0.76:
                    requested_specialty = max(fuzzy)[1]
        branch = _match_branch(user_speech)
        doctor_name = _match_doctor(user_speech)
        local_day = date_start.astimezone(CLINIC_TIMEZONE).date()
        # Fetch the whole day, then answer by morning / afternoon / evening.
        slots = await get_slots_by_date_and_criteria(
            db,
            date_query=local_day.isoformat(),
            specialty=requested_specialty,
            location_name=branch,
            doctor_name=doctor_name,
            limit=50,
        )
        date_label = date_start.astimezone(CLINIC_TIMEZONE).strftime("%A, %B %d")
        if not slots:
            specialty_label = f" for {requested_specialty}" if requested_specialty else ""
            return {
                "intent": "faq_response",
                "availability_context": None,
                "latest_agent_speech": (
                    f"I couldn't find active appointment openings{specialty_label} on {date_label}. "
                    "Would you like me to check another date?"
                ),
            }
        period = period_from_request(user_speech, requested_window, requested_time)
        speech, offered, asks_period = day_availability_speech(
            slots,
            day_label=date_label,
            period=period if requested_time is None else None,
            exact_time=requested_time,
        )
        doctors_in_answer = {slot["doctor_name"] for slot in slots}
        context = {
            "doctor": next(iter(doctors_in_answer)) if len(doctors_in_answer) == 1 else None,
            "location": branch,
            "specialty": requested_specialty,
            "date": local_day.isoformat(),
        } if asks_period else None
        return {"intent": "faq_response", "availability_context": context, "latest_agent_speech": speech}

    if not requested_specialty:
        if any(term in lower for term in (
            "general consultation", "general consultant", "general consultants",
            "general consult", "general medicine", "general doctor", "general physician"
        )):
            requested_specialty = "General Medicine"
        else:
            words = re.findall(r"[a-z]+", lower)
            candidates = sorted(known_specialties, key=len, reverse=True)
            for specialty in candidates:
                if specialty.lower() in lower:
                    requested_specialty = specialty
                    break
            if not requested_specialty:
                matches = [
                    (SequenceMatcher(None, word, specialty.lower()).ratio(), specialty)
                    for word in words
                    for specialty in candidates
                    if len(word) >= 5
                ]
                if matches:
                    score, specialty = max(matches)
                    if score >= 0.76:
                        requested_specialty = specialty

    if requested_specialty:
        matching_doctors = [
            f"{doctor.full_name} at {doctor.location.name.removesuffix(' Branch')}"
            for doctor in doctors
            if doctor.specialty
            and doctor.specialty.lower() == requested_specialty.lower()
            and doctor.location
        ]
        if matching_doctors:
            answer = (
                f"For {requested_specialty}, available doctors are "
                f"{', '.join(matching_doctors)}. Which branch would you prefer?"
            )
        else:
            answer = f"I couldn't find an active doctor listed for {requested_specialty}. Would you like to ask about another specialty?"
    else:
        listed_doctors = [
            f"{doctor.full_name} ({doctor.specialty or 'specialty not listed'} at "
            f"{doctor.location.name.removesuffix(' Branch')})"
            for doctor in doctors if doctor.location
        ]
        answer = (
            f"Our active doctors are {', '.join(listed_doctors)}. Which specialty or branch would you like?"
            if listed_doctors else
            "I can’t retrieve the active doctor list right now. Please try again shortly."
        )
    return {
        "intent": "faq_response",
        "preferred_specialty": requested_specialty,
        "latest_agent_speech": answer,
    }


def _repeat_response(state: CallState) -> Dict[str, Any]:
    """Patient did not understand the assistant: say the last message again, without changing flow state."""
    last = (state.get("latest_agent_speech") or "").strip()
    if not last:
        return {
            "intent": "faq_response",
            "latest_agent_speech": "Sorry about that. How can I help you today? You can say book, reschedule, cancel, or ask about the clinic.",
        }
    if last == state.get("last_repeat_speech"):
        # Repeating did not help; offer simpler ways forward instead of looping.
        speech = (
            "I'm sorry for the confusion. You can tell me in a few words what you need, such as book, "
            "reschedule or cancel, or say front desk and I'll have our team help you directly."
        )
    else:
        speech = f"Sorry about that, let me say it again. {last}"
    return {"intent": "faq_response", "latest_agent_speech": speech, "last_repeat_speech": speech}


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return {1: f"{n}st", 2: f"{n}nd", 3: f"{n}rd"}.get(n % 10, f"{n}th")


async def detect_intent_node(state: CallState, db: AsyncSession) -> Dict[str, Any]:
    """
    State-aware intent detection node:
    1. Deterministic conversation-state shortcuts and safety guardrails.
    2. LLM structured intent classification (book, reschedule, cancel, doctor_availability, faq, handoff, general_consultation, unknown).
    3. Safety validation of output against clinic rules and LangGraph routing.
    """
    user_speech = state.get("latest_user_speech", "").strip()
    if not user_speech:
        return {
            "intent": "faq_response",
            "latest_agent_speech": "I didn’t catch that. Could you please repeat or rephrase?",
        }

    lower = user_speech.lower()
    current_intent = state.get("intent")
    has_active_appt = bool(state.get("active_appointment_id") or state.get("active_appointment_details"))
    last_agent_speech = state.get("latest_agent_speech", "").lower()

    # Keep explicit date preferences in an active reschedule flow attached to
    # that flow. This avoids sending "October 28 afternoon" through generic
    # intent classification after a prior slot search failed.
    reschedule_date_context = has_active_appt and (
        current_intent == "reschedule"
        or state.get("pending_intent") == "reschedule"
        or state.get("awaiting_preferred_date")
    )
    parsed_preference_date, _ = parse_date_query_to_range(user_speech)
    explicit_cancel = bool(re.search(
        r"\b(?:just\s+)?canc(?:el|le|ell)(?:ed|ing)?(?:\s+(?:my|the|this|his|her))?\s+(?:appointment|it|that)\b",
        lower,
    ))
    if (
        reschedule_date_context
        and parsed_preference_date is not None
        and has_date_reference(user_speech)
        and not explicit_cancel
        and not is_emergency_report(user_speech)
    ):
        return {"intent": "reschedule"}

    # A held replacement slot is awaiting a reschedule confirmation. Route
    # affirmative replies directly to the reschedule node regardless of a
    # stale prior intent or an LLM's competing BOOK/UNKNOWN classification.
    if (
        has_active_appt
        and state.get("target_slot_id")
        and "move your appointment" in last_agent_speech
    ):
        if is_reschedule_confirmation(user_speech):
            return {"intent": "reschedule"}
        if (
            re.search(r"\breschedul(?:e|ing)\b", lower)
            or any(phrase in lower for phrase in (
                "move it", "move my appointment", "change my appointment",
                "another slot", "alternative slot", "different time", "another time",
                "different date", "another date", "change date", "change time",
            ))
            or has_date_reference(user_speech)
            or _extract_time_of_day(user_speech) is not None
            or _extract_time_window(user_speech) is not None
        ):
            return {"intent": "reschedule"}

    # ── 1. CONVERSATION-STATE & SAFETY FAST PATHS ─────────────────────────────

    # Medical Emergency Lock: Do not allow booking, rescheduling, or normal conversation during an active emergency
    if state.get("is_emergency") or state.get("handoff_reason") == "medical_emergency":
        return {
            "intent": "handoff",
            "handoff_required": True,
            "is_emergency": True,
            "handoff_reason": "medical_emergency",
            "latest_agent_speech": (
                "Because you reported severe emergency symptoms, scheduling an appointment is not safe. "
                "Please go to the nearest hospital emergency department or call emergency services (112 or 108) immediately."
            ),
            "is_completed": True,
        }

    # We just told the patient which parts of the day have openings; they now pick one.
    ctx = state.get("availability_context")
    if ctx and len(user_speech.split()) <= 6 and (
        period_from_request(user_speech, _extract_time_window(user_speech), _extract_time_of_day(user_speech))
    ) and not has_date_reference(user_speech):
        who = " ".join(part for part in (ctx.get("doctor"), ctx.get("location"), ctx.get("specialty")) if part)
        answer = await _handle_doctor_availability_query(
            db, user_speech=f"{who} on {ctx['date']} {user_speech}".strip()
        )
        answer["availability_context"] = answer.get("availability_context")
        return answer

    # "I couldn't understand you" / "repeat that": answer it directly, keeping the flow state intact.
    if is_repeat_request(user_speech) and not is_emergency_report(user_speech):
        return _repeat_response(state)

    # Follow-up booking must be anchored to a completed visit, not treated as
    # an ordinary new consultation. All channel adapters share this state path.
    asks_followup_booking = bool(
        re.search(r"\b(?:follow[\s-]?up|return\s+visit)\b", lower)
        and re.search(r"\b(?:appointment|consultation|visit|book|schedule)\b", lower)
        and not re.search(r"\b(?:what\s+(?:is|does)|meaning|explain)\b", lower)
    )

    if state.get("awaiting_followup_decision"):
        if is_explicit_confirmation(user_speech):
            return {
                "intent": "book",
                "pending_intent": "book",
                "preferred_appointment_type": "General Consultation",
                "awaiting_followup_decision": False,
                "awaiting_followup_visit": False,
                "followup_candidates": [],
                "awaiting_preferred_date": True,
                "latest_agent_speech": "Certainly. Which clinic branch or doctor would you prefer, and what date works best?",
            }
        if is_explicit_rejection(user_speech):
            return {
                "intent": "faq_response",
                "preferred_appointment_type": None,
                "awaiting_followup_decision": False,
                "followup_candidates": [],
                "latest_agent_speech": "Understood. Let me know if you would like help with another appointment or clinic question.",
            }
        return {
            "intent": "faq_response",
            "awaiting_followup_decision": True,
            "latest_agent_speech": "Would you like to book a regular General Consultation instead? Please say yes or no.",
        }

    if state.get("awaiting_followup_visit"):
        candidates = state.get("followup_candidates") or []
        selected = None
        ordinal = re.search(r"\b(first|second|third|fourth|fifth|[1-5])\b", lower)
        if ordinal:
            index_map = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
            index = index_map.get(ordinal.group(1), int(ordinal.group(1)) - 1 if ordinal.group(1).isdigit() else -1)
            if 0 <= index < len(candidates):
                selected = candidates[index]
        if selected is None:
            doctor_matches = [
                item for item in candidates
                if item.get("doctor_name") and item["doctor_name"].lower().replace("dr. ", "") in lower.replace("dr. ", "")
            ]
            if len(doctor_matches) == 1:
                selected = doctor_matches[0]
        if selected is None:
            selected_range = parse_date_query_to_range(user_speech)[0] if has_date_reference(user_speech) else None
            if selected_range:
                selected_day = selected_range.astimezone(CLINIC_TIMEZONE).date().isoformat()
                date_matches = [item for item in candidates if item.get("visit_date") == selected_day]
                if len(date_matches) == 1:
                    selected = date_matches[0]
        if selected is None:
            return {
                "intent": "faq_response",
                "awaiting_followup_visit": True,
                "latest_agent_speech": followup_candidate_prompt(candidates),
            }
        return {
            "intent": "faq_response",
            "pending_intent": "book",
            "preferred_appointment_type": "Follow-up Consultation",
            "preferred_doctor": selected.get("doctor_name"),
            "preferred_specialty": selected.get("specialty"),
            "preferred_location": selected.get("location_name"),
            "preferred_date": None,
            "awaiting_preferred_date": True,
            "awaiting_followup_visit": False,
            "followup_candidates": [],
            "latest_agent_speech": (
                f"Understood. What date and time would you prefer for a follow-up with "
                f"{selected.get('doctor_name')}?"
            ),
        }

    if asks_followup_booking:
        if not state.get("is_verified") or not state.get("patient_id"):
            return {
                "intent": "book",
                "pending_intent": "book",
                "preferred_appointment_type": "Follow-up Consultation",
            }
        active_appointment = state.get("active_appointment_details")
        if not active_appointment:
            active_appointment = await check_patient_active_appointment(state["patient_id"], db)
        if active_appointment:
            return {
                "intent": "faq_response",
                "active_appointment_id": active_appointment["appointment_id"],
                "active_appointment_details": active_appointment,
                "latest_agent_speech": (
                    f"You already have an active appointment with {active_appointment['formatted_speech']}. "
                    "Our clinic allows one active appointment per patient, so I can't add another follow-up booking right now. "
                    "Would you like help with that existing appointment?"
                ),
            }
        candidates = await get_followup_candidates(state["patient_id"], db)
        if not candidates:
            return {
                "intent": "faq_response",
                "pending_intent": "book",
                "preferred_appointment_type": None,
                "awaiting_followup_decision": True,
                "latest_agent_speech": (
                    "I couldn't find a previous completed appointment to link this follow-up to. "
                    "Would you like to book a regular General Consultation instead?"
                ),
            }
        if len(candidates) > 1:
            return {
                "intent": "faq_response",
                "preferred_appointment_type": "Follow-up Consultation",
                "followup_candidates": candidates,
                "awaiting_followup_visit": True,
                "latest_agent_speech": followup_candidate_prompt(candidates),
            }
        visit = candidates[0]
        branch = f" at {visit['location_name']}" if visit.get("location_name") else ""
        return {
            "intent": "faq_response",
            "pending_intent": "book",
            "preferred_appointment_type": "Follow-up Consultation",
            "preferred_doctor": visit["doctor_name"],
            "preferred_specialty": visit["specialty"],
            "preferred_location": visit["location_name"],
            "preferred_date": None,
            "awaiting_preferred_date": True,
            "followup_candidates": candidates,
            "latest_agent_speech": (
                f"I found your previous visit with {visit['doctor_name']} ({visit['specialty']}){branch} "
                f"on {visit['formatted_date']}. What date and time would you prefer for your follow-up?"
            ),
        }

    # Acknowledgements during identity collection
    if (
        not state.get("is_verified")
        and state.get("awaiting_identity_verification")
        and (is_closing_or_thanks(user_speech) or is_greeting(user_speech))
    ):
        return {"intent": "identity"}

    # Cancellation confirmation gate
    if (
        state.get("awaiting_cancel_confirmation")
        and (is_explicit_confirmation(user_speech) or is_explicit_rejection(user_speech))
    ):
        return {"intent": "cancel"}

    # Reschedule vs cancel ambiguity resolution
    asks_reschedule = any(phrase in lower for phrase in (
        "reschedule", "move appointment", "change appointment", "another doctor",
        "different doctor", "other doctor", "switch doctor", "change doctor",
    ))
    if state.get("awaiting_change_action_choice"):
        if explicit_cancel or lower.strip() in {"cancel", "cancel it", "just cancel"}:
            return {"intent": "cancel", "awaiting_change_action_choice": False, "awaiting_cancel_confirmation": False}
        if asks_reschedule:
            return {"intent": "reschedule", "awaiting_change_action_choice": False, "awaiting_cancel_confirmation": False}
        # Anything else is interpreted by the LLM classifier below, which is
        # told the assistant is waiting for a reschedule-or-cancel choice.

    if explicit_cancel and asks_reschedule:
        return {
            "intent": "faq_response",
            "awaiting_change_action_choice": True,
            "latest_agent_speech": "I can do either one. Would you like to reschedule your existing appointment with another doctor, or cancel it completely?",
        }

    # Bare number disambiguation during date/slot selection
    bare_number = re.fullmatch(r"\s*(\d{1,2})\s*", user_speech)
    if bare_number and (
        state.get("offered_slots")
        or state.get("awaiting_preferred_date")
    ):
        number = bare_number.group(1)
        # In a reschedule date prompt, an unqualified day above 12 cannot be
        # a valid 12-hour clock time. Treat it as the requested calendar day.
        if (
            int(number) > 12
            and reschedule_date_context
            and parse_date_query_to_range(user_speech)[0] is not None
        ):
            return {"intent": "reschedule"}
        hour_options = (
            f"{number}:00 AM, {number}:00 PM, or the {_ordinal(int(number))} day of the month"
            if 1 <= int(number) <= 12
            else f"the {_ordinal(int(number))} day of the month or a time written with AM or PM"
        )
        return {
            "intent": "faq_response",
            "latest_agent_speech": (
                f"I want to make sure I understood correctly. Do you mean {hour_options}? Please include AM or PM, "
                "or say the full date."
            ),
        }

    # Vague calendar references
    if lower.strip() in {"next week", "this week", "later", "soon"} and (
        has_active_appt or state.get("awaiting_preferred_date")
    ):
        return {
            "intent": "faq_response",
            "latest_agent_speech": "Do you mean a particular day? Please tell me the date, for example October 27, and a preferred time if you have one.",
        }

    # Held slot disambiguation for vague references
    if state.get("target_slot_id") and lower.strip() in {
        "appointment", "the appointment", "it", "that", "this",
    }:
        return {
            "intent": "faq_response",
            "latest_agent_speech": "Do you want me to confirm the proposed appointment, show other slots, or cancel your current appointment?",
        }

    # Keep emergency escalation deterministic, but classify ordinary health and
    # clinic questions with the LLM below. A word such as "medicine" alone is
    # not evidence that the patient is asking for medical advice.
    health_concerns = (
        "fever", "cough", "cold", "pain", "headache", "chest", "heart",
        "rash", "infection", "bleeding", "dizzy", "dizziness", "vomit",
        "nausea", "breathing", "allergy", "allergic", "medicine", "medication",
        "symptom", "pregnant", "pregnancy", "earache", "ear", "throat", "sinus",
        "nose", "hearing", "tonsil", "joint", "knee", "back", "bone", "sprain",
        "period", "menstrual", "pelvic", "vaginal", "itch", "itching", "skin",
        "acne", "palpitations",
    )
    mentions_health_concern = any(
        re.search(rf"\b{re.escape(term)}\b", lower) for term in health_concerns
    )
    symptom_terms = (
        "fever", "cough", "cold", "pain", "headache", "rash", "infection",
        "bleeding", "dizzy", "dizziness", "vomit", "nausea", "breathing",
        "allergy", "allergic", "symptom", "pregnant", "pregnancy", "earache",
        "ear", "throat", "sinus", "nose", "hearing", "tonsil", "joint", "knee",
        "back", "bone", "sprain", "period", "menstrual", "pelvic", "vaginal",
        "itch", "itching", "skin", "acne", "palpitations",
    )
    mentions_symptom = any(
        re.search(rf"\b{re.escape(term)}\b", lower) for term in symptom_terms
    )
    if is_emergency_report(user_speech):
        return {
            "intent": "handoff",
            "handoff_required": True,
            "is_emergency": True,
            "handoff_reason": "medical_emergency",
            "latest_agent_speech": (
                "This sounds like a serious medical emergency. Please call emergency services (112 or 108) "
                "or go to the nearest hospital emergency room immediately. "
                "Do not wait for a clinic appointment or callback."
            ),
            "is_completed": True,
        }

    # Gratitude / Closing check
    if is_closing_or_thanks(user_speech):
        return {
            "intent": "close",
            "latest_agent_speech": f"You're very welcome! I am always here to help. Thank you for choosing {settings.CLINIC_NAME}. Have a wonderful day!",
        }

    # Greeting check
    if is_greeting(user_speech):
        return {"intent": "greet"}

    # Bare patient name during unverified state
    name_words = lower.rstrip(".!?").split()
    non_name_terms = {"book", "appointment", "schedule", "doctor", "cancel", "reschedule", "change", "help", "yes", "no", "hello", "hi"}
    if not state.get("is_verified") and is_name_correction(user_speech):
        return {"intent": "identity"}
    introduced_name = name_from_speech(user_speech)
    if (
        not state.get("is_verified")
        and introduced_name
        and not any(word in non_name_terms for word in introduced_name.lower().split())
        and re.fullmatch(r"[a-z][a-z'’-]*(?:\s+[a-z][a-z'’-]*){0,3}", introduced_name.lower())
    ):
        return {"intent": "identity"}

    # New patient registration flow
    if state.get("is_new_patient") and not state.get("is_verified"):
        return {"intent": "register"}

    # Awaiting identity verification or DOB stated
    has_dob_match, _, _ = validate_dob(user_speech)
    if (has_dob_match or any(w in lower for w in ["dob", "date of birth", "born on"])) and not state.get("is_verified"):
        if any(w in lower for w in ["register", "new patient", "new", "sign up", "not registered"]):
            return {"intent": "register"}
        return {"intent": "identity"}

    # Registration direct keywords
    if any(w in lower for w in [
        "register as a new patient", "new patient registration", "how do i register",
        "i want to register", "register me", "registration", "i am a new patient", "sign up", "register"
    ]):
        return {"intent": "register"}

    # Continue a collection step directly only when the reply is a plausible
    # value for that field. Other requests (including handoff/cancel) go to the
    # LLM instead of being trapped in the form flow.
    has_email = bool(re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", user_speech))
    if state.get("awaiting_patient_email") and (
        has_email or lower.strip() in {"skip", "no email", "i don't have email"}
    ):
        curr = current_intent
        if curr in ("identity", "greet", None):
            curr = state.get("pending_intent") or ("reschedule" if has_active_appt else "book")
        return {"intent": curr}

    valid_preference = False
    if state.get("awaiting_preferred_date") and not state.get("target_slot_id") and not is_explicit_confirmation(user_speech) and not is_explicit_rejection(user_speech):
        parsed_date, _ = parse_date_query_to_range(user_speech)
        has_time = _extract_time_of_day(user_speech) is not None or _extract_time_window(user_speech) is not None
        location_names = (await db.execute(
            select(Location.name).where(Location.is_active.is_(True))
        )).scalars().all()
        provider_names = (await db.execute(
            select(Provider.full_name).where(Provider.is_active.is_(True))
        )).scalars().all()
        has_branch = bool(_match_branch(user_speech)) or any(
            n.removesuffix(" Branch").lower() in lower for n in location_names
        )
        has_doctor = bool(_match_doctor(user_speech)) or any(
            part in lower
            for name in provider_names
            for part in re.sub(r"^dr\.?\s+", "", name.lower()).split()
            if len(part) > 2
        )
        asks_for_options = any(phrase in lower for phrase in (
            "alternative", "another slot", "other slot", "different time", "different date",
            "morning", "afternoon", "evening",
        ))
        valid_preference = any((parsed_date, has_time, has_branch, has_doctor, asks_for_options))

    # Valid date/time/branch/doctor answers continue the active booking task.
    if state.get("awaiting_preferred_date") and valid_preference:
        curr = state.get("intent")
        if (
            state.get("preferred_appointment_type")
            and state.get("pending_intent") == "book"
        ):
            curr = "book"
        if curr in ("identity", "greet", None):
            curr = state.get("pending_intent") or ("reschedule" if has_active_appt else "book")
        return {"intent": curr}

    # Active reschedule prompt check
    asked_reschedule_active = has_active_appt and (
        "reschedule that appointment" in last_agent_speech
        or "would you like to reschedule it" in last_agent_speech
        or "allows one active" in last_agent_speech
        or "reschedule that appointment instead" in last_agent_speech
    )
    if asked_reschedule_active:
        if is_closing_or_thanks(user_speech):
            return {
                "intent": "close",
                "latest_agent_speech": "You're very welcome! I am always here to help. Your appointment remains confirmed. Have a wonderful day!",
            }
        # Only a bare yes/no answer is handled here. Anything else (including
        # "cancel it", "book another doctor", typos) goes to the LLM classifier
        # with the recent dialogue so the reply is understood, not keyword-matched.
        if explicit_cancel and not asks_reschedule:
            return {"intent": "cancel"}
        if not explicit_cancel and not asks_reschedule:
            if is_explicit_rejection(user_speech):
                return {
                    "intent": "faq_response",
                    "latest_agent_speech": "No problem. Your current appointment remains unchanged. How else can I help?",
                }
            if re.fullmatch(r"(?:yes|yeah|yep|yup|sure|okay|ok)\b[\s,.!]*(?:please)?[\s.!]*", lower.strip()) \
                    or is_explicit_confirmation(user_speech):
                return {"intent": "reschedule"}

    # Doctor browsing follow-up: filter by branch
    if state.get("intent") == "faq_response" and state.get("preferred_specialty"):
        selected_branch = _match_branch(user_speech)
        if selected_branch:
            specialty = state["preferred_specialty"]
            branch = await db.scalar(
                select(Location).where(
                    Location.is_active.is_(True),
                    Location.name.ilike(f"%{selected_branch}%"),
                )
            )
            doctors = []
            if branch:
                doctors = list((await db.scalars(
                    select(Provider)
                    .where(
                        Provider.is_active.is_(True),
                        Provider.location_id == branch.id,
                        Provider.specialty.ilike(specialty),
                    )
                    .order_by(Provider.full_name)
                )).all())
            if doctors:
                answer = (
                    f"For {specialty} at our {selected_branch} branch, "
                    f"the available doctor is {', '.join(doctor.full_name for doctor in doctors)}. "
                    "Would you like to book with this doctor?"
                )
            else:
                branches = list((await db.scalars(
                    select(Location.name)
                    .join(Provider, Provider.location_id == Location.id)
                    .where(
                        Location.is_active.is_(True),
                        Provider.is_active.is_(True),
                        Provider.specialty.ilike(specialty),
                    )
                    .distinct()
                    .order_by(Location.name)
                )).all())
                branch_names = [name.removesuffix(" Branch") for name in branches]
                answer = (
                    f"Our {selected_branch} branch does not offer {specialty}. "
                    f"It is available at {', '.join(branch_names) if branch_names else 'no currently listed branch'}. "
                    "Which branch would you prefer?"
                )
            return {
                "intent": "faq_response",
                "preferred_specialty": specialty,
                "preferred_location": selected_branch if doctors else None,
                "latest_agent_speech": answer,
            }

    # ── 2. STATE-AWARE LLM INTENT CLASSIFIER ──────────────────────────────────

    context_parts = []
    if has_active_appt:
        context_parts.append("Patient has an existing active appointment.")
    if state.get("is_verified"):
        context_parts.append("Patient identity is verified.")
    else:
        context_parts.append("Patient is unverified.")
    if state.get("awaiting_identity_verification") and not state.get("is_verified"):
        context_parts.append("The patient was asked to provide identity details, but may still ask clinic questions or request a staff handoff.")
    if current_intent:
        context_parts.append(f"Current intent: {current_intent}.")
    if state.get("awaiting_change_action_choice"):
        context_parts.append("The assistant just asked whether to reschedule the existing appointment or cancel it.")
    if state.get("awaiting_cancel_confirmation"):
        context_parts.append("The assistant just asked the patient to confirm cancelling their appointment.")
    if state.get("awaiting_preferred_date"):
        context_parts.append("The assistant is waiting for the patient's preferred date, time, branch or doctor.")
    if asked_reschedule_active:
        context_parts.append("The assistant just told the patient they already have an active appointment and offered to reschedule it. Only a yes/no-style reply answers that offer; classify any other request (for example booking a different specialty) on its own meaning.")
    recent_dialogue = _recent_dialogue_context(state, user_speech)
    if recent_dialogue:
        context_parts.append("Recent dialogue (PII redacted):\n" + recent_dialogue)
    conversation_context = "; ".join(context_parts) if context_parts else None

    classification = await intent_classification_service.classify_intent(
        user_message=user_speech,
        conversation_context=conversation_context,
    )

    # The classifier provides a semantic safety check in addition to the fast
    # phrase detector above, so paraphrased red-flag reports still escalate.
    if classification.intent == IntentLabel.EMERGENCY:
        return {
            "intent": "handoff",
            "handoff_required": True,
            "is_emergency": True,
            "handoff_reason": "medical_emergency",
            "latest_agent_speech": (
                "This may be a serious medical emergency. Please call emergency services (112 or 108) "
                "or go to the nearest hospital emergency room immediately. "
                "Do not wait for a clinic appointment or callback."
            ),
            "is_completed": True,
        }

    if classification.intent == IntentLabel.REPEAT:
        return _repeat_response(state)

    # Ground model-extracted entities before any entity can affect availability
    # queries or booking state. Dates/times must parse from this utterance;
    # providers, branches, and specialties must exist in the clinic database.
    entities = classification.entities
    if entities.date:
        utterance_date, _ = parse_date_query_to_range(user_speech)
        entity_date, _ = parse_date_query_to_range(entities.date)
        if not has_date_reference(user_speech) or utterance_date is None or entity_date is None:
            entities.date = None
            classification.needs_clarification = True
        elif utterance_date.astimezone(CLINIC_TIMEZONE).date() != entity_date.astimezone(CLINIC_TIMEZONE).date():
            entities.date = None
            classification.needs_clarification = True
        else:
            entities.date = utterance_date.astimezone(CLINIC_TIMEZONE).date().isoformat()
    if entities.time:
        utterance_time = _extract_time_of_day(user_speech)
        utterance_window = _extract_time_window(user_speech)
        entity_time = _extract_time_of_day(entities.time)
        if utterance_time is None and utterance_window is not None and entities.time.lower() in {
            "morning", "afternoon", "evening"
        }:
            # Dayparts are parsed by the booking flow as windows, not clock times.
            entities.time = None
        elif utterance_time is None or entity_time is None or utterance_time != entity_time:
            entities.time = None
            classification.needs_clarification = True
        else:
            entities.time = f"{utterance_time[0]:02d}:{utterance_time[1]:02d}"
    if entities.branch:
        mentioned_branch = _match_branch(user_speech)
        valid_locations = set((await db.scalars(
            select(Location.name).where(Location.is_active.is_(True))
        )).all())
        canonical_branch = next(
            (name for name in valid_locations
             if name.lower().removesuffix(" branch") == entities.branch.lower().removesuffix(" branch")),
            None,
        )
        if (
            not canonical_branch
            or not mentioned_branch
            or canonical_branch.lower().removesuffix(" branch") != mentioned_branch.lower().removesuffix(" branch")
        ):
            entities.branch = None
            classification.needs_clarification = True
        else:
            entities.branch = canonical_branch
    if entities.specialty:
        valid_specialties = set((await db.scalars(
            select(Provider.specialty).where(Provider.is_active.is_(True)).distinct()
        )).all())
        canonical_specialty = next(
            (name for name in valid_specialties if name and name.lower() == entities.specialty.lower()), None
        )
        if not canonical_specialty:
            entities.specialty = None
            classification.needs_clarification = True
        else:
            entities.specialty = canonical_specialty
    if entities.doctor:
        active_doctors = list((await db.scalars(
            select(Provider.full_name).where(Provider.is_active.is_(True))
        )).all())
        normalize_doctor = lambda name: re.sub(r"\bdr\.?\s*", "", name.lower()).strip()
        canonical_doctor = next(
            (name for name in active_doctors
             if name and normalize_doctor(name) == normalize_doctor(entities.doctor)),
            None,
        )
        if not canonical_doctor:
            entities.doctor = None
            classification.needs_clarification = True
        else:
            entities.doctor = canonical_doctor

    # Short symptom reports (including imperfect speech-to-text grammar) should
    # reach the safe General Medicine offer instead of an unknown-intent prompt.
    # Preserve explicit action intents, while routing treatment questions to the
    # medical-advice response without diagnosing or recommending medication.
    medical_advice_terms = (
        "what medicine", "which medicine", "medication", "dosage", "dose",
        "tablet", "diagnose", "diagnosis", "prescribe", "prescription",
        "treatment", "cure", "what should i take", "how to treat",
    )
    if (
        mentions_symptom
        and classification.intent in (IntentLabel.UNKNOWN, IntentLabel.GENERAL_CONSULTATION)
        and not any(term in lower for term in medical_advice_terms)
    ):
        classification.intent = IntentLabel.GENERAL_CONSULTATION
        classification.confidence = "medium"
        classification.needs_clarification = False
    elif (
        mentions_symptom
        and classification.intent in (IntentLabel.UNKNOWN, IntentLabel.GENERAL_CONSULTATION)
        and any(term in lower for term in medical_advice_terms)
    ):
        classification.intent = IntentLabel.MEDICAL_ADVICE
        classification.confidence = "medium"
        classification.needs_clarification = False

    # ── 3. SAFETY VALIDATION & APPLICATION ROUTING ────────────────────────────

    # Rule: Handle uncertainty, low confidence, or unknown intent with clarification
    if classification.needs_clarification or classification.intent == IntentLabel.UNKNOWN or classification.confidence == "low":
        if state.get("awaiting_identity_verification") and not state.get("is_verified"):
            return {"intent": "identity"}
        if state.get("awaiting_patient_email"):
            return {
                "intent": "faq_response",
                "latest_agent_speech": (
                    "I didn't understand the email address. Could you say it again, "
                    "for example name@example.com, or say skip?"
                ),
            }
        if state.get("awaiting_preferred_date"):
            return {
                "intent": "faq_response",
                "latest_agent_speech": (
                    "I didn't understand the date or time you prefer. Could you say a full date, "
                    "such as October 27, and a time such as 10 AM or morning?"
                ),
            }
        if has_active_appt:
            return {
                "intent": "faq_response",
                "latest_agent_speech": (
                    "I didn't quite understand. Are you asking about your current appointment, clinic information, "
                    "or something else? Please tell me what you'd like help with."
                ),
            }
        return {
            "intent": "faq_response",
            "latest_agent_speech": (
                "I didn’t quite understand that. Could you rephrase your question? "
                "I can help with clinic information, bookings, rescheduling, or cancellations."
            ),
        }

    # Rule: Human handoff
    if classification.intent == IntentLabel.HANDOFF:
        return {
            "intent": "handoff",
            "handoff_reason": "Patient requested front desk transfer",
        }

    # Rule: Doctor availability inquiries must NEVER automatically convert to booking requests
    if classification.intent == IntentLabel.DOCTOR_AVAILABILITY:
        return await _handle_doctor_availability_query(
            db,
            requested_specialty=classification.entities.specialty,
            user_speech=user_speech,
        )

    # Rule: General consultation information request
    if classification.intent == IntentLabel.GENERAL_CONSULTATION:
        if mentions_health_concern:
            specialty_cues = (
                ("Cardiology", ("palpitations", "heartbeat", "heart racing")),
                ("Dermatology", ("rash", "itch", "itching", "skin", "acne")),
                ("ENT", ("ear", "throat", "sinus", "nose", "hearing", "tonsil")),
                ("Orthopedics", ("joint", "knee", "back pain", "bone", "sprain")),
                ("Gynecology", ("period", "menstrual", "pregnan", "pelvic", "vaginal")),
                ("Pediatrics", ("my child", "my baby", "my son", "my daughter", "for my child")),
            )
            suggested_specialty = classification.entities.specialty or next(
                (
                    specialty for specialty, cues in specialty_cues
                    if any(cue in lower for cue in cues)
                ),
                "General Medicine",
            )
            available_specialties = {
                specialty for specialty in (await db.scalars(
                    select(Provider.specialty)
                    .where(Provider.is_active.is_(True))
                    .distinct()
                )).all()
                if specialty
            }
            if suggested_specialty not in available_specialties:
                suggested_specialty = (
                    "General Medicine" if "General Medicine" in available_specialties else None
                )
            offer = (
                f"I can help arrange an appointment with a {suggested_specialty} doctor. Would you like help booking one?"
                if suggested_specialty else
                "I can't confirm which clinic specialty is appropriate from the available information. Would you like me to connect you with the front desk?"
            )
            return {
                "intent": "faq_response",
                "preferred_specialty": suggested_specialty,
                "latest_agent_speech": (
                    "I'm sorry you're feeling unwell. I can't diagnose symptoms. " + offer
                ),
            }
        return {
            "intent": "faq",
            "semantic_label": "general_consultation_explanation",
        }

    # Safe medical response: never diagnose or prescribe. Don't initiate a
    # staff handoff unless the patient asked for one; ask how they want to proceed.
    if classification.intent == IntentLabel.MEDICAL_ADVICE:
        return {
            "intent": "faq_response",
            "latest_agent_speech": (
                "I can't diagnose or recommend medicine or treatment. A qualified clinician can advise you. "
                "Would you like me to help find a doctor, or connect you with the front desk?"
            ),
        }

    # Rule: General FAQ
    if classification.intent == IntentLabel.FAQ:
        return {"intent": "faq"}

    # Rule: Cancellation request (Application code verifies identity & confirms)
    if classification.intent == IntentLabel.CANCEL:
        return {"intent": "cancel"}

    # Rule: Reschedule request
    if classification.intent == IntentLabel.RESCHEDULE:
        updates: Dict[str, Any] = {"intent": "reschedule"}
        if classification.entities.date:
            updates["preferred_date"] = classification.entities.date
        if classification.entities.time:
            updates["preferred_time"] = classification.entities.time
        return updates

    # In a reschedule flow, a plain confirmation of the offered replacement
    # must commit the move, even if the classifier labels "book it" as book.
    if (
        classification.intent == IntentLabel.BOOK
        and current_intent == "reschedule"
        and state.get("target_slot_id")
        and is_explicit_confirmation(user_speech)
    ):
        return {"intent": "reschedule"}

    # Rule: Book new appointment
    if classification.intent == IntentLabel.BOOK:
        updates: Dict[str, Any] = {"intent": "book"}
        if classification.entities.specialty:
            updates["preferred_specialty"] = classification.entities.specialty
        if classification.entities.branch:
            updates["preferred_location"] = classification.entities.branch
        if classification.entities.doctor:
            updates["preferred_doctor"] = classification.entities.doctor
        if classification.entities.date:
            updates["preferred_date"] = classification.entities.date
        if classification.entities.time:
            updates["preferred_time"] = classification.entities.time
        return updates

    return {"intent": "unknown"}
