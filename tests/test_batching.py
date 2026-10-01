"""Gemini is called once per batch, not once per email."""

from types import SimpleNamespace

import pytest

from agent import tools
from agent.parsing import regex_extract
from agent.schemas import BatchInvoice


@pytest.fixture
def fake_gemini(monkeypatch, emails):
    """Answer each request from the regex baseline, keyed by the '=== EMAIL n ===' blocks it contains."""
    requests = []

    def generate(contents, **_):
        requests.append(contents)
        items = []
        for block in contents.split("\n=== EMAIL ")[1:]:
            n, text = block.split(" ===\n", 1)
            rec = regex_extract(text)
            if "NOTE FOR EMAIL" not in contents and "AWS" in text:
                rec["vendor"] = "Acme"  # wrong on the first pass so verify has to retry it
            fields = {k: v for k, v in rec.items() if k in BatchInvoice.model_fields}
            items.append(BatchInvoice(**fields, email_id=int(n)))
        return SimpleNamespace(parsed=items)

    monkeypatch.setattr(tools, "_generate", generate)
    return requests


def test_whole_batch_costs_two_requests(fake_gemini, emails):
    texts = list(emails.values())
    results = tools.extract_and_verify(texts)
    assert len(fake_gemini) == 2  # one for all emails, one for the single retry
    assert fake_gemini[0].count("\n=== EMAIL ") == 3 and fake_gemini[1].count("\n=== EMAIL ") == 1
    assert "NOTE FOR EMAIL 1: a previous extraction was rejected because: vendor 'Acme'" in fake_gemini[1]
    aws = results[list(emails).index("aws.txt")]
    assert aws["corrected"] and not aws["needs_review"]
    assert [r["needs_review"] for r in results] == [False, False, False]


def test_clean_batch_costs_one_request(fake_gemini, emails):
    texts = [emails["electricity.txt"], emails["netflix.txt"]]
    assert all(isinstance(r, dict) for r in tools.extract_and_verify(texts))
    assert len(fake_gemini) == 1


def test_batch_size_splits_requests(fake_gemini, emails, monkeypatch):
    monkeypatch.setenv("GEMINI_BATCH_SIZE", "2")
    tools._extract_many(list(emails.values()))
    assert [r.count("\n=== EMAIL ") for r in fake_gemini] == [2, 1]


def test_skipped_email_fails_alone(monkeypatch, emails):
    reply = BatchInvoice(vendor="TSSPDCL", amount=1240.5, currency="INR", due_date="2026-10-12", email_id=2)
    monkeypatch.setattr(tools, "_generate", lambda **_: SimpleNamespace(parsed=[reply]))
    first, second = tools._extract_many([emails["aws.txt"], emails["electricity.txt"]])
    assert isinstance(first, ValueError) and "no result for email 1" in str(first)
    assert second["vendor"] == "TSSPDCL" and second["amount_base"] == 1240.5


def test_failed_retry_request_keeps_first_attempt(emails):
    text = emails["electricity.txt"]
    bad = {**regex_extract(text), "vendor": "BESCOM"}

    def down(email_texts, hints=None):
        raise RuntimeError("503 UNAVAILABLE")

    (result,) = tools.verify_many([bad], [text], down)
    assert result["vendor"] == "BESCOM" and result["needs_review"]
