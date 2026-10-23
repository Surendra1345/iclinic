"""Spoken descriptions of appointment slots that read naturally and don't repeat themselves.

The doctor and branch are said once per group, followed only by the times. Availability is
described by morning / afternoon / evening, and an empty period suggests the periods that do
have openings.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.utils.appointment_time import CLINIC_TIMEZONE
from src.utils.text import short_branch_name

PERIODS = ("morning", "afternoon", "evening")
DIRECT_LIST_LIMIT = 6   # up to this many slots are read out; more are summarised by period


def local_dt(slot: Dict[str, Any]) -> datetime:
    value = slot["start_time"]
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CLINIC_TIMEZONE)


def period_of(dt: datetime) -> str:
    if dt.hour < 12:
        return "morning"
    if dt.hour < 17:
        return "afternoon"
    return "evening"


def clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def period_from_request(
    text: str = "",
    window: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None,
    exact_time: Optional[Tuple[int, int]] = None,
) -> Optional[str]:
    """Which part of the day the patient asked about, from words, a time window or a clock time."""
    lower = (text or "").lower()
    for period in PERIODS:
        if re.search(rf"\b{period}s?\b", lower):
            return period
    if window:
        return period_of(datetime(2000, 1, 1, window[0][0], window[0][1]))
    if exact_time:
        return period_of(datetime(2000, 1, 1, exact_time[0], exact_time[1]))
    return None


def times_phrase(dts: List[datetime]) -> str:
    """'9:00, 9:30 AM and 2:00, 2:30 PM' - the AM/PM marker is said once per run."""
    runs: List[Tuple[str, List[str]]] = []
    for dt in dts:
        meridiem = dt.strftime("%p")
        clock_text = dt.strftime("%I:%M").lstrip("0")
        if runs and runs[-1][0] == meridiem:
            runs[-1][1].append(clock_text)
        else:
            runs.append((meridiem, [clock_text]))
    parts = [f"{', '.join(times)} {meridiem}" for meridiem, times in runs]
    return " and ".join(parts)


def _range(dts: List[datetime]) -> str:
    return clock(dts[0]) if len(dts) == 1 else f"{clock(dts[0])} to {clock(dts[-1])}"


def _join(items: List[str], conjunction: str = "and") -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {conjunction} " + items[-1]


def _groups(slots: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[datetime]]:
    groups: Dict[Tuple[str, str], List[datetime]] = {}
    for slot in sorted(slots, key=local_dt):
        key = (str(slot.get("doctor_name") or "A doctor"), short_branch_name(slot.get("location_name"), "our clinic"))
        groups.setdefault(key, []).append(local_dt(slot))
    return groups


def _list_text(slots: List[Dict[str, Any]], day_label: str) -> str:
    groups = _groups(slots)
    if len(groups) == 1:
        (doctor, branch), dts = next(iter(groups.items()))
        return f"{doctor} at {branch} has openings on {day_label}: {times_phrase(dts)}."
    return f"On {day_label}: " + "; ".join(
        f"{doctor} at {branch}, {times_phrase(dts)}" for (doctor, branch), dts in groups.items()
    ) + "."


def _period_summary(slots: List[Dict[str, Any]], day_label: str) -> str:
    groups = _groups(slots)
    parts = []
    for (doctor, branch), dts in groups.items():
        by_period = {p: [d for d in dts if period_of(d) == p] for p in PERIODS}
        described = [f"{p} ({_range(v)})" for p, v in by_period.items() if v]
        parts.append(f"{doctor} at {branch} has {_join(described)}")
    return f"On {day_label}, " + "; ".join(parts) + "."


def _article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"


def _period_sentence(slots: List[Dict[str, Any]]) -> str:
    """'The openings are in the morning (9:00 AM to 11:30 AM) and afternoon (2:00 PM to 4:30 PM).'"""
    groups = _groups(slots)
    pieces = []
    for (doctor, branch), dts in groups.items():
        described = [
            f"{p} ({_range([d for d in dts if period_of(d) == p])})"
            for p in PERIODS if any(period_of(d) == p for d in dts)
        ]
        pieces.append(_join(described) if len(groups) == 1 else f"{doctor} at {branch}: {_join(described)}")
    if len(groups) == 1:
        return f"The openings are in the {pieces[0]}."
    return "The openings are: " + "; ".join(pieces) + "."


def _nearest_sentence(nearest: List[Dict[str, Any]]) -> str:
    groups = _groups(nearest)
    if len(groups) == 1:
        (doctor, branch), dts = next(iter(groups.items()))
        return f"The closest times with {doctor} at {branch} are {times_phrase(dts)}."
    return "The closest times are: " + _list_text(nearest, "that day")


def _subject(slots: List[Dict[str, Any]]) -> str:
    doctors = list(dict.fromkeys(str(s.get("doctor_name") or "A doctor") for s in slots))
    return doctors[0] if len(doctors) == 1 else "These doctors"


def day_availability_speech(
    slots: List[Dict[str, Any]],
    *,
    day_label: str,
    period: Optional[str] = None,
    exact_time: Optional[Tuple[int, int]] = None,
    closing: str = "Would you like to book one?",
) -> Tuple[str, List[Dict[str, Any]], bool]:
    """Return (speech, slots to keep as the offered options, asks_which_period)."""
    ordered = sorted(slots, key=local_dt)

    if exact_time:
        target = exact_time[0] * 60 + exact_time[1]
        close = [s for s in ordered if abs(local_dt(s).hour * 60 + local_dt(s).minute - target) <= 15]
        if close:
            return f"{_list_text(close, day_label)} {closing}", close, False
        nearest = sorted(
            ordered, key=lambda s: abs(local_dt(s).hour * 60 + local_dt(s).minute - target)
        )[:3]
        nearest = sorted(nearest, key=local_dt)
        wanted = datetime(2000, 1, 1, exact_time[0], exact_time[1])
        return (
            f"There is no opening at {clock(wanted)} on {day_label}. {_nearest_sentence(nearest)} "
            f"Would you like one of those?",
            nearest,
            False,
        )

    if period:
        in_period = [s for s in ordered if period_of(local_dt(s)) == period]
        if in_period:
            return f"{_list_text(in_period, day_label)} {closing}", in_period, False
        present = [p for p in PERIODS if any(period_of(local_dt(s)) == p for s in ordered)]
        subject = _subject(ordered)
        verb = "don't" if subject == "These doctors" else "doesn't"
        return (
            f"{subject} {verb} have {period} slots on {day_label}. {_period_sentence(ordered)} "
            f"Would you like {_join([f'{_article(p)} {p} slot' for p in present], 'or')}?"
            if present else f"There are no openings on {day_label}.",
            ordered,
            True,
        )

    if len(ordered) <= DIRECT_LIST_LIMIT:
        return f"{_list_text(ordered, day_label)} {closing}", ordered, False
    return (
        f"{_period_summary(ordered, day_label)} Which time of day would you prefer?",
        ordered,
        True,
    )
