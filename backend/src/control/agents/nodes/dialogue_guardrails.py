"""Small deterministic guards for patient consent and ambiguous replies."""
import re


_YES = {
    "yes", "yes please", "yeah", "yeah please", "yep", "yup", "sure",
    "okay", "ok", "all right", "alright", "correct", "that is right",
    "that's right", "that works", "sounds good", "perfect", "go ahead",
    "proceed", "do it", "book it", "book that", "confirm", "confirm it",
    "ok do it", "okay do it", "yes do it", "yes please do it",
    "schedule it", "lock it in", "move it", "reschedule it", "cancel it",
    "cancel that appointment", "yes book it", "yes cancel it", "yes move it",
    "yes ok book it", "yes okay book it", "yes please book it",
    "yes please", "yes okay", "yes ok", "okay please", "ok please",
    "please confirm", "yes confirm", "yes please confirm", "please confirm it",
    "please confirm and book it", "please confirm and move it",
    "yes please confirm and move it", "yes please confirm and book it",
    "i am sure", "i'm sure", "yes i am sure", "yes i'm sure",
    "yes please cancel it", "please cancel it", "yes i am sure please cancel it",
    "yes i'm sure please cancel it", "yes i am sure cancel it", "yes i'm sure cancel it",
}
_NO = {
    "no", "no thanks", "no thank you", "nope", "not now", "keep it",
    "leave it", "do not", "don't", "different time", "another time",
    "another slot", "alternative", "show alternatives",
}


def _normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower())
    return " ".join(text.split())


def is_explicit_confirmation(text: str) -> bool:
    """Return true only for a clear affirmative, not incidental words like 'please'."""
    normalized = _normalize(text)
    if not normalized or "?" in text or is_explicit_rejection(normalized):
        return False
    if normalized in _YES:
        return True
    # Allow a clear affirmative plus an explicit action, but do not treat any
    # sentence beginning with "yes" as consent (for example, "yes, but ...").
    return bool(re.fullmatch(
        r"(?:yes|yeah|yep|yup|sure|okay|ok)?(?: please)?(?: i am sure| i'm sure)?\s*(?:confirm(?: and)?\s*)?"
        r"(?:book it|book that|move it|reschedule it|cancel it|confirm it|confirm that|confirm|do that|book|please cancel it)",
        normalized,
    ))


def is_reschedule_confirmation(text: str) -> bool:
    """Recognize clear confirmations plus common ASR rendering of “move it”.

    Callers must use this only while a replacement appointment is awaiting
    confirmation; the ASR variants are intentionally context-specific.
    """
    normalized = _normalize(text)
    return is_explicit_confirmation(text) or normalized in {
        "yes move", "yeah move", "yep move", "yup move", "ok move", "okay move",
    }


def is_explicit_rejection(text: str) -> bool:
    normalized = _normalize(text)
    return normalized in _NO or bool(
        re.match(r"^(?:no|nope|not that|don't|do not|keep my appointment)\b", normalized)
    )


_REPEAT_EXACT = {
    "what", "huh", "pardon", "pardon me", "sorry", "come again", "excuse me", "say again",
    "repeat", "repeat please", "can you repeat", "could you repeat", "please repeat",
    "what was that", "say what", "one more time", "again", "again please",
}
# Lenient on purpose: speech-to-text and typing errors are common ("counldn't understad").
_NOT_UNDERSTOOD = re.compile(
    r"\b(?:not|no|can't|couldn't|didn't|don't|won't|cant|cannot|couldnt|couldn|counldn|didnt|dont|wont|unable|hard)\b[^.?!]{0,25}"
    r"\b(?:und\w*st\w*|follow|catch|hear|get)\b"
)
_ASKS_REPEAT = re.compile(
    r"\b(?:repeat|say (?:that|it|this)(?: again)?|read (?:that|it|this)(?: again| out)?|"
    r"tell me (?:that |it )?again|once more|one more time|what did you say|what was that|"
    r"speak (?:more )?(?:slowly|slower|clearly|simply|loudly|louder|up)|louder|slow(?:er| down)|"
    r"too fast|not clear|unclear|confusing|confused|make it simple|in simple words|"
    r"what do you mean|hard to hear)\b"
)
_LEADING_FILLER = re.compile(r"^(?:(?:yeah|yes|yep|yup|okay|ok|sure|hey|hi|hello|um|uh|so|well|please|sorry)\b[\s,]*)+")


def is_repeat_request(text: str) -> bool:
    """True when the patient says they did not understand and wants the assistant to say it again.

    A leading "yeah/okay/please" is just a filler here ("Yeah, can you please read that?").
    """
    normalized = _normalize(text)
    stripped = _LEADING_FILLER.sub("", normalized).strip()
    for candidate in {normalized, stripped}:
        if not candidate:
            continue
        if candidate in _REPEAT_EXACT:
            return True
        if _NOT_UNDERSTOOD.search(candidate) or _ASKS_REPEAT.search(candidate):
            return True
    return False
