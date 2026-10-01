"""End-to-end over the sample inbox with the regex extractor standing in for Gemini."""

import json

import pytest
from fastapi.testclient import TestClient

from agent import tools
from agent.parsing import regex_extract
from agent.pipeline import run_batch


@pytest.fixture
def seeded_history(isolated_env):
    with open("data/history_seed.json", encoding="utf-8") as f:
        (isolated_env / "history.json").write_text(f.read())


def test_batch_logs_flags_and_dedupes(offline_extractor, seeded_history, monkeypatch, isolated_env):
    monkeypatch.setenv("MOCK_INBOX", "1")
    first = {r["source_id"]: r for r in run_batch()["records"]}
    assert set(first) == {"aws.txt", "electricity.txt", "netflix.txt"}
    assert all(r["logged"] for r in first.values())
    assert first["electricity.txt"]["above_trend"]
    assert first["aws.txt"]["autopay"] and not first["aws.txt"]["flagged"]
    assert not first["netflix.txt"]["flagged"]

    second = run_batch()
    assert not any(r["logged"] for r in second["records"])  # re-runs never duplicate rows
    history = json.loads((isolated_env / "history.json").read_text())
    assert len(history["tsspdcl"]) == 4  # 3 seeded + this month, added once


def test_one_bad_email_does_not_stop_the_batch(monkeypatch, emails):
    def extractor(email_text, hint=""):
        if "junk" in email_text:
            raise RuntimeError("503 UNAVAILABLE")
        return regex_extract(email_text)

    monkeypatch.setattr(tools, "_extract_many", tools.batched(extractor))
    result = run_batch([{"id": "junk", "text": "junk"}, {"id": "ok", "text": emails["netflix.txt"]}])
    assert [r["source_id"] for r in result["records"]] == ["ok"]
    assert result["errors"][0]["id"] == "junk"


def test_failed_extraction_request_logs_nothing(monkeypatch, emails, isolated_env):
    def down(email_texts, hints=None):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(tools, "_extract_many", down)
    result = run_batch([{"id": "a", "text": emails["aws.txt"]}, {"id": "b", "text": emails["netflix.txt"]}])
    assert result["records"] == [] and [e["id"] for e in result["errors"]] == ["a", "b"]
    assert not (isolated_env / "bills.csv").exists()


def test_log_to_sheet_reports_duplicates(offline_extractor, emails):
    record = tools.verify(tools.extract_invoice(emails["aws.txt"]), emails["aws.txt"])
    assert tools.log_to_sheet(record) == {"logged": True}
    assert tools.log_to_sheet(record) == {"logged": False}


def test_http_run_endpoint(offline_extractor, emails):
    from main import app

    client = TestClient(app)
    assert client.get("/healthz").json() == {"ok": True}
    body = client.post("/run", json={"emails": [{"id": "e1", "text": emails["electricity.txt"]}]}).json()
    assert body["processed"] == 1 and body["errors"] == []
    assert body["records"][0]["vendor"] == "TSSPDCL"
    assert client.post("/run", json={"mock": True}).json()["processed"] == 3
