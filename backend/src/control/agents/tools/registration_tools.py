"""Registration tools ??? validate DOB and register new patients."""
import re
from datetime import date, datetime
from typing import Optional
# pyrefly: ignore[missing-import]
from sqlalchemy import select
# pyrefly: ignore[missing-import]
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.patient import Patient
from src.data.repositories.appointment_repository import AppointmentRepository
from src.data.repositories.patient_repository import PatientRepository


_GREETING_WORDS = {
    "hello",
    "hey",
    "hi",
    "hii",
    "hlo",
    "hloo",
    "hullo",
    "hey there",
    "hello there",
    "good morning",
    "good afternoon",
    "good evening",
}

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
PHONE_REGEX = re.compile(r"(?:\+91[\-\s]?)?[6-9]\d{9}\b")


def is_greeting(text: str) -> bool:
    """Return True when text is a casual greeting, not a patient name or instruction."""
    cleaned = re.sub(r"[^a-z\s]", " ", text.strip().lower())
    cleaned = " ".join(cleaned.split())
    if cleaned in _GREETING_WORDS:
        return True
    normalized = re.sub(r"[^a-z\s]", " ", cleaned)
    words = normalized.split()
    if not words:
        return False
    if len(words) == 1:
        word = re.sub(r"(.)\1+", r"\1", words[0])
        return word in {"hello", "hey", "hi", "hlo", "hullo"}
    if len(words) == 2 and words[0] in {"good", "hey", "hello"}:
        return f"{words[0]} {words[1]}" in _GREETING_WORDS
    return False


_CLOSING_PHRASES = [
    "thank you for your conformation",
    "thank you for your confirmation",
    "thank you for confirming",
    "thanks for confirming",
    "thanks for the confirmation",
    "thank you for the confirmation",
    "thank you for the information",
    "thanks for the information",
    "thank you for the info",
    "thanks for the info",
    "thank you for letting me know",
    "thanks for letting me know",
    "thank you for your help",
    "thanks for your help",
    "thank you so much",
    "thank you very much",
    "thanks a lot",
    "that's all thank you",
    "that is all thank you",
    "that will be all thank you",
    "that's all thanks",
    "that's all",
    "that is all",
    "that will be all",
    "that's it thank you",
    "that's it",
    "no thank you",
    "no thanks",
    "no that's fine",
    "no that's okay",
    "no that's alright",
    "i'm good thank you",
    "i am good thank you",
    "i'm good thanks",
    "have a good day",
    "have a nice day",
    "have a great day",
    "take care",
    "goodbye",
    "bye bye",
    "bye",
]

_EXACT_THANKS = {
    "thank you",
    "thankyou",
    "thanks",
    "thx",
    "thank u",
    "ok thank you",
    "okay thank you",
    "ok thanks",
    "okay thanks",
    "alright thank you",
    "all right thank you",
    "no thank you",
    "no thanks",
}


def is_closing_or_thanks(text: str) -> bool:
    """Return True when text expresses gratitude, acknowledgement, or closing rather than a new action."""
    cleaned = text.strip().lower()
    cleaned_no_punct = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned_norm = " ".join(cleaned_no_punct.split())

    if cleaned_norm in _EXACT_THANKS or cleaned in _EXACT_THANKS:
        return True

    for phrase in _CLOSING_PHRASES:
        if phrase in cleaned_norm or phrase in cleaned:
            remaining = cleaned_norm.replace(phrase, " ")
            rem_words = remaining.split()
            if any(act in rem_words for act in ["book", "reschedule", "cancel", "doctor"]):
                return False
            return True

    words = cleaned_norm.split()
    if words and (words[0] in {"thanks", "thankyou"} or (len(words) >= 2 and words[0] == "thank" and words[1] == "you")):
        if not any(act in words for act in ["book", "reschedule", "cancel", "doctor", "dr"]):
            return True
    if words and (words[-1] in {"thanks", "thankyou"} or (len(words) >= 2 and words[-2] == "thank" and words[-1] == "you")):
        if not any(act in words for act in ["book", "reschedule", "cancel", "doctor", "dr"]):
            return True

    return False


def extract_email(text: str) -> Optional[str]:
    """Extract standard email address from text."""
    match = EMAIL_REGEX.search(text)
    return match.group(0).lower() if match else None


def extract_phone(text: str) -> Optional[str]:
    """Extract standard 10-digit mobile number from text."""
    match = PHONE_REGEX.search(text)
    if match:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10:
            return f"+91{digits}"
        if len(digits) == 12 and digits.startswith("91"):
            return f"+{digits}"
        return f"+{digits}"
    # General fallback for any 10 consecutive digits
    m10 = re.search(r"\b\d{10}\b", text)
    if m10:
        return f"+91{m10.group(0)}"
    return None


def validate_dob(dob_str: str) -> tuple[bool, Optional[date], str]:
    """
    Validate patient Date of Birth.
    Must be in the past, and age must be between 0 and 120 years.
    Returns (is_valid, parsed_date, error_message).
    """
    cleaned = dob_str.strip()
    # Remove ordinal suffixes like 14th, 1st, 2nd, 3rd
    cleaned = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(".", "-").replace("/", "-")

    parsed_date: Optional[date] = None

    date_patterns = [
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%d %B %Y",
        "%B %d %Y",
        "%d %b %Y",
        "%b %d %Y",
    ]

    # Try exact formats first
    for fmt in date_patterns:
        try:
            parsed_date = datetime.strptime(cleaned, fmt).date()
            break
        except ValueError:
            pass

    # If full text had other words, search for date pattern inside string
    if not parsed_date:
        date_regex = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", dob_str)
        if date_regex:
            d1, d2, yr = int(date_regex.group(1)), int(date_regex.group(2)), int(date_regex.group(3))
            try:
                # Assume day-month-year first
                parsed_date = date(yr, d2, d1)
            except ValueError:
                try:
                    parsed_date = date(yr, d1, d2)
                except ValueError:
                    pass

    # Speech recognition often inserts spaces between spoken year digits
    # (for example, "14 December 2 0 0 3"). Normalize only a clear day,
    # month-name, four-digit-year sequence; never infer a missing/ambiguous year.
    if not parsed_date:
        month_names = (
            r"january|february|march|april|may|june|july|august|september|"
            r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
        )
        spoken_month = re.search(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})\s+((?:\d\s*){{3}}\d)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if spoken_month:
            day_num = int(spoken_month.group(1))
            month_text = spoken_month.group(2)
            year_text = re.sub(r"\s+", "", spoken_month.group(3))
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    parsed_date = datetime.strptime(
                        f"{day_num} {month_text} {year_text}", fmt
                    ).date()
                    break
                except ValueError:
                    pass

    if not parsed_date:
        return False, None, "Invalid date format. Please provide date of birth as Day-Month-Year (e.g. 14-08-2004)."

    today = date.today()
    if parsed_date > today:
        return False, None, "Date of birth cannot be in the future."

    age = today.year - parsed_date.year - ((today.month, today.day) < (parsed_date.month, parsed_date.day))
    if age > 120:
        return False, None, "Date of birth is outside valid range (must be less than 120 years ago)."
    if age < 0:
        return False, None, "Date of birth cannot be in the future."

    return True, parsed_date, ""


def is_invalid_name(text: str) -> bool:
    """Check if the provided name is a conversational phrase rather than a real name."""
    cleaned = text.strip().lower()
    if is_greeting(cleaned):
        return True
    phrases = [
        "reschedule", "appointment", "booking", "book", "cancel",
        "doctor", "checkup", "consult", "i need", "i want", "i am looking",
        "help", "hi", "hello", "new patient", "register", "please", "yes", "no",
        "thank you", "thankyou", "thanks", "thank u", "could you", "can you",
        "what is", "where is", "available"
    ]
    if any(re.search(rf"\b{re.escape(phrase)}\b", cleaned) for phrase in phrases):
        return True
    words = cleaned.split()
    if len(words) > 4 or len(words) == 0:
        return True
    return False


_NON_NAME_WORDS = {
    "i", "im", "i'm", "am", "are", "is", "was", "were", "have", "has", "had",
    "my", "me", "you", "your", "we", "our", "they", "this", "that", "these",
    "those", "the", "a", "an", "and", "or", "but", "to", "for", "with", "at",
    "from", "of", "on", "in", "it", "please", "can", "could", "would", "will",
    "want", "need", "like", "forward", "transfer", "connect", "send", "talk", "speak",
    "frontdesk", "front", "desk", "receptionist", "staff", "human", "help", "hello",
    "hi", "hey", "thanks", "thank", "thankyou", "okay", "ok", "skip", "book",
    "appointment", "schedule", "cancel", "reschedule", "doctor", "pain", "stomach",
    "fever", "cough", "headache", "chest", "sick", "hurt", "hurts", "symptoms",
    # Interrogatives/explanatory terms make short questions look like names if
    # they are omitted (for example, "what does Python mean?").
    "what", "does", "do", "did", "how", "why", "when", "where", "which",
    "who", "whose", "whom", "mean", "meaning", "explain", "define", "tell",
    "show", "list", "available", "branch", "branches", "clinic", "service",
}


_NAME_INTRO = re.compile(
    r"^(?:(?:hello|hi|hey|yes|yeah|okay|ok|sure)[\s,!.]*)?"
    r"(?:my (?:full )?name is|my name's|name is|i am|i'm|im|this is|it is|it's|its|call me|they call me|you can call me)\s+",
    re.IGNORECASE,
)
_NAME_CORRECTION = re.compile(
    r"\b(?:(?:this|that|it)(?: is|'s| was)? not my name|not my name|wrong name|that(?:'s| is) wrong|"
    r"(?:that|this)(?: is|'s) not me|that name is wrong|isn't my name|is not my name)\b",
    re.IGNORECASE,
)


def strip_name_intro(text: str) -> str:
    """'My name is Sonia' -> 'Sonia'."""
    return _NAME_INTRO.sub("", (text or "").strip(), count=1).strip()


def is_name_correction(text: str) -> bool:
    """The patient says the name we captured is wrong ("this is not my name")."""
    return bool(_NAME_CORRECTION.search(text or ""))


def name_from_speech(text: str) -> Optional[str]:
    """A bare name, with or without an introduction ("Sonia", "my name is Sonia"); else None."""
    cleaned = strip_name_intro(text)
    return re.sub(r"[.!?,;:]+$", "", cleaned).strip().title() if is_name_only_candidate(cleaned) else None


def is_name_only_candidate(text: str) -> bool:
    """Accept only short, name-like replies; reject ordinary phrases and requests."""
    cleaned = re.sub(r"[.!?,;:]+$", "", strip_name_intro(text or ""))
    words = cleaned.split()
    if not 1 <= len(words) <= 4 or is_invalid_name(cleaned):
        return False
    if any(word.lower().strip("'’-") in _NON_NAME_WORDS for word in words):
        return False
    return all(
        word.replace("'", "").replace("’", "").replace("-", "").isalpha()
        for word in words
    )


async def register_new_patient(
    full_name: str,
    dob: date,
    phone: str,
    email: Optional[str],
    db: AsyncSession,
) -> dict:
    """Reuse a matching patient (by phone or name+dob) or create a new patient record."""
    repo = PatientRepository(db)
    cleaned_phone = phone.strip() if phone else ""
    digits = re.sub(r"\D", "", cleaned_phone)
    if len(digits) == 10:
        cleaned_phone = f"+91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        cleaned_phone = f"+{digits}"

    patient = None

    # 1. Search for existing profiles registered under this mobile number
    if cleaned_phone and len(digits) >= 10:
        phone_matches = (
            await db.scalars(
                select(Patient)
                .where(
                    Patient.phone == cleaned_phone,
                    Patient.is_active == True,
                )
                .order_by(Patient.created_at.desc())
            )
        ).all()

        for p in phone_matches:
            p_name = p.full_name.strip().lower()
            req_name = full_name.strip().lower()

            # Check if this profile belongs to the same person (name match or DOB match)
            first_name_match = (
                p_name == req_name
                or (p_name.split() and req_name.split() and p_name.split()[0] == req_name.split()[0])
            )
            dob_match = (p.date_of_birth == dob) if (p.date_of_birth and dob) else False

            # If it's the SAME person (e.g. returning patient), reuse their profile
            if first_name_match or dob_match:
                patient = p
                break

    # 2. If no phone match was the same person, check if this Name + DOB exists across clinic
    if not patient:
        existing_patients = (
            await db.scalars(
                select(Patient)
                .where(
                    Patient.full_name.ilike(full_name.strip()),
                    Patient.date_of_birth == dob,
                    Patient.is_active == True,
                )
                .order_by(Patient.created_at.desc())
            )
        ).all()
        if existing_patients:
            appointment_repo = AppointmentRepository(db)
            for existing_patient in existing_patients:
                if await appointment_repo.get_active_for_patient(existing_patient.id):
                    patient = existing_patient
                    break
            else:
                patient = existing_patients[0]

    # If existing patient was found (same person), update missing/updated details
    if patient:
        updated = False
        if cleaned_phone and (not patient.phone or patient.phone == ""):
            patient.phone = cleaned_phone
            updated = True
        if email and (not patient.email or patient.email != email):
            patient.email = email
            updated = True
        if dob and patient.date_of_birth != dob:
            patient.date_of_birth = dob
            updated = True
        if full_name and patient.full_name.strip().lower() != full_name.strip().lower():
            patient.full_name = full_name.strip()
            updated = True
        if updated:
            await db.flush()

        return {
            "id": str(patient.id),
            "full_name": patient.full_name,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
            "phone": patient.phone,
            "email": patient.email,
        }

    # 3. If no match was found:
    # This is a brand NEW patient (either a new individual or a child/family member sharing the phone!)
    # Create an independent profile so the child gets their own medical records and appointment slot.
    patient = await repo.create_patient(
        full_name=full_name.strip(),
        date_of_birth=dob,
        phone=cleaned_phone,
        email=email,
        source="assistant",
    )
    return {
        "id": str(patient.id),
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
        "phone": patient.phone,
        "email": patient.email,
    }

