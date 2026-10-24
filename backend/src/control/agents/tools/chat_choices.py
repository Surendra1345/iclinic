"""Tap-to-answer buttons for the web chat, worked out from what the assistant just asked.

Chat only: voice and calls never use these. A button simply sends the same words the patient could have typed, so
nothing about the conversation logic depends on them. Slot lists are handled by `slot_speech.chat_options`; this
module covers the other questions: which branch, which doctor, which visit type, and yes / no.
"""
import re
from typing import Dict, Iterable, List

from src.utils.text import short_branch_name

_BRANCH_QUESTION = re.compile(r"\bwhich (?:clinic )?(?:branch|of these branches)|\bwhich branch", re.IGNORECASE)
_DOCTOR_QUESTION = re.compile(r"\bwhich doctor", re.IGNORECASE)
_DOCTOR_NAME = re.compile(r"Dr\. [A-Z][a-z]+(?: [A-Z][a-z]+)+")
_VISIT_QUESTION = re.compile(r"reason for your visit", re.IGNORECASE)
_YES_NO_QUESTION = re.compile(
    r"\b(?:shall i|would you like me to|do you want me to|are you sure|would you like to (?:reschedule|book|cancel|keep))\b",
    re.IGNORECASE,
)

MAX_BUTTONS = 8


def _buttons(labels: Iterable[str]) -> List[Dict[str, str]]:
    seen: List[str] = []
    for label in labels:
        if label and label not in seen:
            seen.append(label)
    return [{"label": label, "message": label} for label in seen[:MAX_BUTTONS]]


def reply_choices(speech: str, *, branch_names: Iterable[str], visit_types: Iterable[str]) -> List[Dict[str, str]]:
    """Buttons for the question in `speech`, or an empty list when it is not a question with fixed answers."""
    text = speech or ""
    if _VISIT_QUESTION.search(text):
        return _buttons(visit_types)
    if _BRANCH_QUESTION.search(text):
        shorts = [short_branch_name(name, "") for name in branch_names]
        mentioned = [short for short in shorts if short and short.lower() in text.lower()]
        return _buttons(mentioned or shorts)
    if _DOCTOR_QUESTION.search(text):
        doctors = _DOCTOR_NAME.findall(text)
        if doctors:
            return _buttons(doctors)
    if text.rstrip().endswith("?") and _YES_NO_QUESTION.search(text):
        return [{"label": "Yes", "message": "yes"}, {"label": "No", "message": "no"}]
    return []
