from agent.parsing import regex_extract
from agent.tools import verify_with


def test_correct_record_is_not_retried(emails):
    calls = []
    record = regex_extract(emails["electricity.txt"])
    result = verify_with(record, emails["electricity.txt"], lambda *a, **k: calls.append(k) or {})
    assert calls == []
    assert (result["corrected"], result["issues"], result["needs_review"]) == (False, [], False)


def test_wrong_field_is_retried_with_hint_and_corrected(emails):
    text = emails["electricity.txt"]
    hints = []

    def extractor(email_text, hint=""):
        hints.append(hint)
        return regex_extract(email_text)

    result = verify_with({**regex_extract(text), "amount": 214.0}, text, extractor)
    assert "amount 214.0 does not appear" in hints[0]
    assert result["amount"] == 1240.5
    assert (result["corrected"], result["needs_review"]) == (True, False)


def test_unresolved_issue_needs_review(emails):
    text = emails["electricity.txt"]
    bad = {**regex_extract(text), "vendor": "BESCOM"}
    result = verify_with(bad, text, lambda email_text, hint="": dict(bad))
    assert result["vendor"] == "BESCOM"
    assert result["needs_review"] and not result["corrected"]
    assert result["issues"] == ["vendor 'BESCOM' is not named in the email"]
