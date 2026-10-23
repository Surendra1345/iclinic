"""Redaction of personal data before text is sent to a language model."""
import re
from typing import Optional

_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_NUMERIC_DATE = re.compile(r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b")
_MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WRITTEN_DATE = re.compile(
    rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\s+\d{{4}}|"
    rf"{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}})\b",
    re.IGNORECASE,
)


def redact_pii(text: str, patient_name: Optional[str] = None) -> str:
    """Mask emails, phone numbers, full dates (such as a date of birth) and the patient's name."""
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    text = _NUMERIC_DATE.sub("[date]", text)
    text = _WRITTEN_DATE.sub("[date]", text)
    name = (patient_name or "").strip()
    if name:
        text = re.sub(re.escape(name), "[patient]", text, flags=re.IGNORECASE)
    return text
