import asyncio

import pytest

from src.config.settings import settings
from src.control.agents.nodes import faq


class _ScalarsResult:
    def all(self):
        return []


class _EmptyDatabase:
    async def scalars(self, _query):
        return _ScalarsResult()


@pytest.mark.parametrize(
    "question",
    [
        "what is the timings of clinic",
        "what are the clinic timings",
        "what are clinic hours",
        "when does the clinic open",
        "what time is the clinic open",
        "clinic opening time",
    ],
)
def test_clinic_hours_questions_are_answered_without_llm(monkeypatch, question):
    async def unexpected_llm_call(*_args, **_kwargs):
        raise AssertionError("Clinic hours should use the configured deterministic answer")

    monkeypatch.setattr(faq.GeminiService, "generate_content", unexpected_llm_call)
    state = {"latest_user_speech": question}
    result = asyncio.run(faq.faq_agent_node(state, _EmptyDatabase()))

    assert result["intent"] == "faq_response"
    assert result["latest_agent_speech"] == (
        f"{settings.CLINIC_NAME} is open from {settings.CLINIC_HOURS_START:02d}:00 "
        f"to {settings.CLINIC_HOURS_END:02d}:00 local time."
    )


def test_appointment_timing_is_not_misclassified_as_clinic_hours():
    assert not faq._asks_clinic_hours("What appointment timings are available?")
