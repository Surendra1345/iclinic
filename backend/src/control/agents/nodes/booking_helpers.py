"""Text parsing and clinic-name helpers shared by booking and identity flows."""
import re
from datetime import datetime
from typing import Optional

from src.control.agents.tools.appointment_time import CLINIC_TIMEZONE, format_appointment_time

BRANCH_ALIASES = {
    "Anna Nagar": ["anna nagar", "annanagar"],
    "T. Nagar": ["t nagar", "t. nagar", "tnagar", "t.nagar"],
    "Velachery": ["velachery"],
    "Tambaram": ["tambaram"],
}

DOCTOR_MAP = {
    "Dr. Arjun Reddy": ["arjun reddy", "arjun"],
    "Dr. Rajesh Kannan": ["rajesh kannan", "rajesh"],
    "Dr. Shalini Sundaram": ["shalini sundaram", "shalini"],
    "Dr. Meera Krishnan": ["meera krishnan", "meera"],
    "Dr. Ashwin Balaji": ["ashwin balaji", "ashwin"],
    "Dr. Priya Nair": ["priya nair", "priya"],
    "Dr. Karthik Subramanian": ["karthik subramanian", "karthik"],
    "Dr. Deepa Venkat": ["deepa venkat", "deepa"],
    "Dr. Sandeep Kumar": ["sandeep kumar", "sandeep"],
    "Dr. Ananya Iyer": ["ananya iyer", "ananya"],
    "Dr. Suresh Chandran": ["suresh chandran", "suresh"],
    "Dr. Divya Rangarajan": ["divya rangarajan", "divya"],
    "Dr. Vivek Sharma": ["vivek sharma", "vivek"],
    "Dr. Lakshmi Narayanan": ["lakshmi narayanan", "lakshmi"],
    "Dr. Harish Gautham": ["harish gautham", "harish"],
    "Dr. Nithya Raman": ["nithya raman", "nithya"],
}


def _match_branch(text: str) -> Optional[str]:
    lower = text.lower()
    for branch, aliases in BRANCH_ALIASES.items():
        if any(alias in lower for alias in aliases):
            return branch
    return None


def _match_doctor(text: str) -> Optional[str]:
    lower = text.lower()
    for doc, aliases in DOCTOR_MAP.items():
        if any(alias in lower for alias in aliases):
            return doc
    return None


def _format_slot_time_str(start_time_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(start_time_iso)
        return format_appointment_time(dt)
    except Exception:
        return start_time_iso


def _clean_slot_time(start_time_iso: str) -> str:
    try:
        t_fmt = _format_slot_time_str(start_time_iso)
        return t_fmt.split(" at ")[-1] if " at " in t_fmt else t_fmt
    except Exception:
        return start_time_iso


def _clean_loc(loc_name: Optional[str]) -> str:
    if not loc_name:
        return "clinic"
    return loc_name.replace(" Branch", "").replace(" branch", "").strip()


EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")


def _extract_name_and_email(text: str) -> tuple[Optional[str], Optional[str]]:
    matched_email = EMAIL_REGEX.search(text)
    email = matched_email.group(0).lower() if matched_email else None

    # Remove email from text
    cleaned_text = EMAIL_REGEX.sub("", text).strip()
    cleaned_text = re.sub(r"[,;:\(\)]", " ", cleaned_text).strip()

    name = None
    # Check "my name is X", "i am X", "name is X"
    m = re.search(r"(?:my name is|i am|name is|this is)\s+([a-zA-Z\s]{2,40})", cleaned_text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        stop_words = {"booking", "trying", "looking", "interested", "calling", "here", "a", "an", "the", "and"}
        words = [w for w in candidate.split() if w.lower() not in stop_words]
        if words and len(words) <= 4:
            name = " ".join(words).title()
    elif cleaned_text:
        filler = {"my", "email", "is", "and", "yes", "sure", "please", "confirm", "it", "to", "for", "the", "at", "book", "me"}
        words = [w for w in cleaned_text.split() if w.lower() not in filler and w.isalpha()]
        if 1 <= len(words) <= 4:
            name = " ".join(words).title()

    return name, email


def _extract_time_of_day(text: str) -> Optional[tuple[int, int]]:
    """
    Extract requested time of day from speech.
    Returns (hour_24, minute).
    Examples:
      '2:00 PM' -> (14, 0)
      '2 PM' -> (14, 0)
      '2pm' -> (14, 0)
      '11:30 AM' -> (11, 30)
      'at 2' -> (14, 0)
    """
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

    m4 = re.search(r"\b(\d{1,2})\s*o'?clock\b", lower)
    if m4:
        hr = int(m4.group(1))
        if 1 <= hr <= 6:
            hr += 12
        return hr, 0

    return None


def _extract_time_window(text: str) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
    """Extract a requested time range such as 'between 2pm and 4pm'."""
    lower = text.lower()
    if re.search(r"\b(morning|in the morning)\b", lower):
        return (9, 0), (11, 59)
    if re.search(r"\b(afternoon|in the afternoon)\b", lower):
        return (12, 0), (16, 59)
    if re.search(r"\b(evening|in the evening)\b", lower):
        return (17, 0), (17, 59)
    match = re.search(
        r"\b(?:(?:between|from)\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:and|to|until|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        lower,
    )
    if not match:
        return None

    def parse_clock(value: str, inferred_meridiem: Optional[str] = None) -> Optional[tuple[int, int]]:
        value = value.strip().lower()
        clock = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value)
        if not clock:
            return None
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = clock.group(3) or inferred_meridiem
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        elif not meridiem and 1 <= hour <= 6:
            hour += 12
        if hour > 23 or minute > 59:
            return None
        return hour, minute

    first, second = match.groups()
    second_meridiem = re.search(r"(am|pm)\s*$", second)
    inferred = second_meridiem.group(1) if second_meridiem else None
    start = parse_clock(first, inferred)
    end = parse_clock(second, inferred)
    if start is None or end is None or start >= end:
        return None
    return start, end


