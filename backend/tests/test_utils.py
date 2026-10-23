from src.utils.pii import redact_pii
from src.utils.text import short_branch_name


def test_pii_is_masked_before_text_reaches_the_llm():
    text = "I am Meera Nair, email meera@example.com, phone +91 98765 43210, born 14-12-2003 and on March 5th, 2004"
    cleaned = redact_pii(text, "Meera Nair")
    assert "[patient]" in cleaned and "[email]" in cleaned and "[phone]" in cleaned
    assert "[date]" in cleaned  # the written date; the numeric DOB is caught by the phone/date masks
    for secret in ("meera@example.com", "98765", "14-12-2003", "2004", "Meera Nair"):
        assert secret not in cleaned


def test_ordinary_text_is_left_alone():
    assert redact_pii("I want a morning slot on the 27th") == "I want a morning slot on the 27th"


def test_short_branch_name():
    assert short_branch_name("T. Nagar Branch") == "T. Nagar"
    assert short_branch_name("velachery branch") == "velachery"
    assert short_branch_name(None) == "clinic"
    assert short_branch_name("", "our clinic") == "our clinic"
