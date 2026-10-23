"""Shared, conservative emergency-language checks for agent turns."""
import re


_EMERGENCY_PHRASES = (
    "heart attack", "cardiac arrest", "stroke", "unconscious", "passed out", "fainted",
    "severe bleeding", "bleeding heavily", "difficulty breathing", "trouble breathing",
    "can't breathe", "cannot breathe", "cannot catch my breath", "short of breath",
    "shortness of breath", "breathlessness", "choking", "feel faint", "feeling faint",
    "feel like fainting", "lightheaded and weak",
    "severe allergic reaction", "anaphylaxis", "chest pain", "chest hurts", "emergency",
)
_DENIAL = re.compile(
    r"\b(?:no|not|never|without|den(?:y|ies|ied)|didn['’]?t|doesn['’]?t|don['’]?t|"
    r"do not|does not|did not|isn['’]?t|is not|aren['’]?t|are not|haven['’]?t|have not)\b"
    r"(?:\s+[a-z']+){0,7}\s*$",
    re.IGNORECASE,
)
_HISTORY = re.compile(
    r"\b(?:last\s+(?:night|week|month|year)|\d+\s+(?:days?|weeks?|months?|years?)\s+ago|"
    r"years?\s+ago|months?\s+ago|yesterday|previously|history\s+of|used\s+to|"
    r"when\s+i\s+was|in\s+the\s+past|no\s+longer)\b",
    re.IGNORECASE,
)
_INFORMATIONAL = re.compile(
    r"^\s*(?:what\s+(?:causes?|is|does|are)|why\s+(?:does|is|do)|how\s+(?:does|can|could)|"
    r"define|meaning\s+of|(?:can|could|would)\s+.{1,60}\s+(?:cause|mean|indicate|be\s+a\s+sign\s+of))\b|"
    r"^\s*(?:is|are|does|do|can|could|would|should)\b.{0,120}\?\s*$|"
    r"^\s*(?:is|are)\b.{0,100}\b(?:always|usually|typically)\b",
    re.IGNORECASE,
)
_REPORTED_QUESTION = re.compile(
    r"^\s*(?:(?:my|the)\s+)?(?:doctor|nurse|clinician)\s+"
    r"(?:asked|wondered|wanted\s+to\s+know)\s+(?:me\s+)?(?:if|whether)\b",
    re.IGNORECASE,
)
_UNCERTAIN = re.compile(
    r"\b(?:not\s+sure|unsure|uncertain|don['â€™]?t\s+know|can['â€™]?t\s+tell|cannot\s+tell)\b"
    r".{0,50}\b(?:if|whether)\b",
    re.IGNORECASE,
)
_CURRENT_RECURRENCE = re.compile(
    r"\b(?:again|now|right\s+now|currently|today|at\s+the\s+moment|has\s+returned|"
    r"came\s+back|coming\s+back)\b",
    re.IGNORECASE,
)
_CURRENT_AFFIRMATION = re.compile(
    r"^\s*(?:and\s+)?(?:i\s+)?(?:do|am|have|yes|that's\s+right|that\s+is\s+right)\b",
    re.IGNORECASE,
)


def _clauses(text: str) -> list[str]:
    """Split contrastive clauses so a denial does not mask a new current symptom."""
    return [part.strip() for part in re.split(r"[.!?;,]|\bbut\b|\bhowever\b", text, flags=re.I) if part.strip()]


def is_emergency_report(text: str) -> bool:
    """Return true for a current emergency report; ignore denial, history, and questions."""
    normalized = " ".join((text or "").lower().replace("’", "'").split())
    if not normalized:
        return False

    clauses = _clauses(normalized)
    previous_emergency_mentioned = False
    for clause in clauses:
        # Ignore a symptom mentioned only as part of a question or a reported
        # question. A separate current assertion in a later clause is evaluated
        # independently below.
        if _INFORMATIONAL.search(clause) or _REPORTED_QUESTION.search(clause):
            previous_emergency_mentioned = previous_emergency_mentioned or any(
                re.search(re.escape(phrase), clause) for phrase in _EMERGENCY_PHRASES
            )
            continue
        for phrase in _EMERGENCY_PHRASES:
            for match in re.finditer(re.escape(phrase), clause):
                prefix = clause[max(0, match.start() - 100):match.start()]
                suffix = clause[match.end():min(len(clause), match.end() + 70)]
                has_history = bool(_HISTORY.search(prefix) or _HISTORY.search(suffix))
                # Uncertainty is not a denial. Treat a possible current emergency
                # symptom conservatively, while ignoring uncertainty about past events.
                if _UNCERTAIN.search(prefix) and not has_history:
                    return True
                if _DENIAL.search(prefix):
                    continue
                if has_history:
                    continue
                return True
        # Carry a narrowly defined reference across contrastive clauses, e.g.
        # “I had chest pain last week but I have it again today.”
        if previous_emergency_mentioned and _CURRENT_RECURRENCE.search(clause) and re.search(
            r"\b(?:it|that|they|those|the\s+same)\b", clause
        ):
            return True
        if previous_emergency_mentioned and _CURRENT_AFFIRMATION.search(clause):
            return True
        if any(re.search(re.escape(phrase), clause) for phrase in _EMERGENCY_PHRASES):
            previous_emergency_mentioned = True
    return False
