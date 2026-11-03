import asyncio
import uuid
from types import SimpleNamespace

from src.control.agents.tools import clinic_directory as cd


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    """Returns locations first, then providers (the order ensure_directory queries)."""

    def __init__(self, locations, providers):
        self._batches = [locations, providers]

    async def scalars(self, _query):
        return _Result(self._batches.pop(0))


def _load():
    north, south = uuid.uuid4(), uuid.uuid4()
    locations = [SimpleNamespace(id=north, name="Riverside Branch"), SimpleNamespace(id=south, name="St. Mary Branch")]
    providers = [
        SimpleNamespace(full_name="Dr. Kavya Menon", specialty="Cardiology", location_id=north),
        SimpleNamespace(full_name="Dr. Omar Shaikh", specialty="ENT", location_id=south),
        SimpleNamespace(full_name="Dr. Omar Rao", specialty="Cardiology", location_id=south),
    ]
    asyncio.run(cd.ensure_directory(_FakeDb(locations, providers), force=True))


def test_names_come_from_the_database_not_code():
    _load()
    assert cd.match_branch("can I come to st mary tomorrow") == "St. Mary"
    assert cd.match_branch("riverside please") == "Riverside"
    assert cd.match_doctor("I want Dr Kavya") == "Dr. Kavya Menon"
    assert cd.match_doctor("omar shaikh") == "Dr. Omar Shaikh"
    # first name shared by two doctors is ambiguous, so it must not guess
    assert cd.match_doctor("omar") is None
    assert cd.match_branch("anna nagar") is None


def test_specialty_and_branch_lookups_and_sentence():
    _load()
    assert cd.specialties_for_branch("Riverside") == ["Cardiology"]
    assert cd.branches_for_specialty("cardiology") == ["Riverside", "St. Mary"]
    assert cd.branch_doctors("St. Mary")["branch"] == "St. Mary"
    assert cd.canonical_branch("riverside") == "Riverside"
    assert cd.canonical_doctor("Dr. Omar Shaikh") == "Dr. Omar Shaikh"
    assert cd.canonical_specialty("cardiology") == "Cardiology" or cd.canonical_specialty("cardiology") == "cardiology"


def test_typos_still_match_branches_and_doctors():
    _load()
    assert cd.match_branch("riversde") == "Riverside"
    assert cd.match_doctor("kavya menan") == "Dr. Kavya Menon"
    assert cd.match_branch("hello there") is None
