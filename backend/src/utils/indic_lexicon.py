"""Offline English equivalents for the short answers patients give most often in Tamil and Telugu.

These replies ("yes", "no", "thank you") are the bulk of a booking call. Mapping them locally
keeps the call working, and fast, when the translation model is slow or out of quota.
"""
import re
from typing import Optional

_YES = (
    "ஆம்", "ஆமாம்", "சரி", "சரிங்க", "ஓகே", "உறுதி", "ஆமா",
    "అవును", "సరే", "ఔను", "ఓకే", "అలాగే", "సరే అండి",
    "aam", "aamam", "aama", "sari", "sarii", "sarringa", "avunu", "avunandi", "sare", "alage", "ok", "okay",
)
_NO = (
    "இல்லை", "வேண்டாம்", "இல்ல", "வேணாம்",
    "కాదు", "వద్దు", "లేదు", "వద్దండి",
    "illai", "illa", "venam", "vendam", "kaadu", "kadu", "vaddu", "ledu",
)
_THANKS = (
    "நன்றி", "மிக்க நன்றி", "ధన్యవాదాలు", "థాంక్స్", "థ్యాంక్యూ",
    "nandri", "nanri", "dhanyavadalu", "thank you", "thanks",
)
_GREET = ("வணக்கம்", "నమస్కారం", "నమస్తే", "vanakkam", "namaskaram", "namaste")
_BYE = ("bye", "goodbye", "సరే వస్తాను")

_LEXICON = (
    (_YES, "yes"),
    (_NO, "no"),
    (_THANKS, "thank you"),
    (_GREET, "hello"),
    (_BYE, "goodbye"),
)


def _clean(text: str) -> str:
    return re.sub(r"[\s.,!?।]+", " ", (text or "").strip().lower()).strip()


def quick_english(text: str) -> Optional[str]:
    """English for a whole utterance that is just a common short answer, else None."""
    cleaned = _clean(text)
    if not cleaned:
        return None
    for words, english in _LEXICON:
        if cleaned in {_clean(word) for word in words}:
            return english
    return None
