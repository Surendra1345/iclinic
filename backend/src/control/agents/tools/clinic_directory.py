"""Read-only, DB-backed directory of the clinic's branches, doctors and specialties.

Nodes call the synchronous helpers here instead of hardcoding names. The cache is
refreshed from the database (SELECT only) at the start of every graph node and
expires after a short TTL, so newly added branches/doctors are picked up without
a code change.
"""
import logging
import re
from difflib import SequenceMatcher
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.config.settings import settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60.0


@dataclass
class _Branch:
    name: str                    # canonical short name, e.g. "T. Nagar"
    full_name: str               # DB name, e.g. "T. Nagar Branch"
    spoken: List[str] = field(default_factory=list)
    compact: str = ""


@dataclass
class _Doctor:
    full_name: str
    specialty: str
    branch: str
    spoken: List[str] = field(default_factory=list)


_branches: List[_Branch] = []
_doctors: List[_Doctor] = []
_loaded_at: float = 0.0


def _norm(text: str) -> str:
    text = re.sub(r"[.\-_,]", " ", (text or "").lower())
    return " ".join(text.split())


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _short_branch(name: str) -> str:
    return re.sub(r"\s+branch$", "", name or "", flags=re.IGNORECASE).strip()


def _strip_title(name: str) -> str:
    return re.sub(r"^\s*dr\.?\s+", "", name or "", flags=re.IGNORECASE).strip()


async def ensure_directory(db: Any, force: bool = False) -> None:
    """Refresh the cache from the database if it is stale. Never raises."""
    global _branches, _doctors, _loaded_at
    if db is None:
        return
    if not force and _branches and (time.monotonic() - _loaded_at) < _TTL_SECONDS:
        return
    try:
        from src.data.models.postgres.location import Location
        from src.data.models.postgres.provider import Provider

        locations = list((await db.scalars(
            select(Location).where(Location.is_active.is_(True)).order_by(Location.name)
        )).all())
        providers = list((await db.scalars(
            select(Provider).where(Provider.is_active.is_(True)).order_by(Provider.full_name)
        )).all())
    except Exception:
        logger.warning("Could not refresh clinic directory", exc_info=True)
        return
    if not locations and not providers:
        return

    by_id = {loc.id: loc for loc in locations}
    branches = [
        _Branch(
            name=_short_branch(loc.name),
            full_name=loc.name,
            spoken=[_norm(_short_branch(loc.name))],
            compact=_compact(_short_branch(loc.name)),
        )
        for loc in locations
    ]
    first_names: Dict[str, int] = {}
    for p in providers:
        first = _norm(_strip_title(p.full_name)).split(" ")[0]
        first_names[first] = first_names.get(first, 0) + 1
    doctors = []
    for p in providers:
        loc = by_id.get(p.location_id)
        plain = _norm(_strip_title(p.full_name))
        spoken = [plain]
        first = plain.split(" ")[0] if plain else ""
        if len(first) > 2 and first_names.get(first) == 1:
            spoken.append(first)
        doctors.append(_Doctor(
            full_name=p.full_name,
            specialty=p.specialty or "",
            branch=_short_branch(loc.name) if loc else "",
            spoken=spoken,
        ))
    _branches, _doctors, _loaded_at = branches, doctors, time.monotonic()


def _fuzzy_contains(normalized_text: str, alias: str, threshold: float = 0.84) -> bool:
    """Typo-tolerant phrase match (e.g. 'tambarm' for 'tambaram') over same-length word windows."""
    if len(alias) < 5:
        return False
    words = normalized_text.split()
    size = len(alias.split())
    for i in range(len(words) - size + 1):
        window = " ".join(words[i:i + size])
        if SequenceMatcher(None, window, alias).ratio() >= threshold:
            return True
    return False


def match_branch(text: str) -> Optional[str]:
    """Return the canonical short name of a branch mentioned in text, if any."""
    normalized = _norm(text)
    compact_text = _compact(text)
    for branch in _branches:
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in branch.spoken):
            return branch.name
        if len(branch.compact) >= 5 and branch.compact in compact_text:
            return branch.name
    for branch in _branches:  # second pass: tolerate speech-to-text/typing errors
        if any(_fuzzy_contains(normalized, alias) for alias in branch.spoken):
            return branch.name
    return None


def match_doctor(text: str) -> Optional[str]:
    """Return the DB full name of a doctor mentioned in text, if any."""
    normalized = _norm(text)
    for doctor in _doctors:
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in doctor.spoken if alias):
            return doctor.full_name
    return None


def branch_names() -> List[str]:
    return [b.name for b in _branches]


def all_specialties() -> List[str]:
    return sorted({d.specialty for d in _doctors if d.specialty})


def _same_branch(a: str, b: str) -> bool:
    ca, cb = _compact(_short_branch(a)), _compact(_short_branch(b))
    return bool(ca and cb and (ca in cb or cb in ca))


def specialties_for_branch(branch_name: str) -> List[str]:
    return sorted({d.specialty for d in _doctors if d.specialty and _same_branch(d.branch, branch_name)})


def branches_for_specialty(specialty: str) -> List[str]:
    target = (specialty or "").lower().strip()
    found: List[str] = []
    for d in _doctors:
        s = d.specialty.lower()
        if s and (s == target or target in s or s in target) and d.branch not in found:
            found.append(d.branch)
    return found


def branch_doctors(branch_name: str) -> Dict[str, Any]:
    docs = [
        {"name": d.full_name, "specialty": d.specialty}
        for d in _doctors if _same_branch(d.branch, branch_name)
    ]
    if docs:
        canonical = next(b.name for b in _branches if _same_branch(b.name, branch_name))
        return {"branch": canonical, "doctors": docs}
    return {"branch": "All Branches", "doctors": []}


def join_names(names: List[str], conjunction: str = "and") -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", {conjunction} {names[-1]}"


def branches_sentence() -> str:
    """e.g. 'City Care Clinic has 4 branches: A, B, C, and D.' built from the DB."""
    names = branch_names()
    if not names:
        return f"Please tell me which {settings.CLINIC_NAME} branch you would prefer."
    noun = "branch" if len(names) == 1 else "branches"
    return f"{settings.CLINIC_NAME} has {len(names)} {noun}: {join_names(names)}."
