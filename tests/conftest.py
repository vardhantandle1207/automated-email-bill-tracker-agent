"""Shared fixtures. Every test runs offline: no Gemini, Gmail, Sheets, Firestore, or FX API."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Point all local state at tmp_path and switch off every cloud backend."""
    monkeypatch.chdir(ROOT)  # data/sample_emails/ is read relative to the repo root
    for var in ("GOOGLE_SHEET_ID", "HISTORY_BACKEND", "MOCK_INBOX", "FX_SOURCE", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SHEET_CSV_PATH", str(tmp_path / "bills.csv"))
    monkeypatch.setenv("HISTORY_PATH", str(tmp_path / "history.json"))
    return tmp_path


@pytest.fixture
def offline_extractor(monkeypatch):
    """Replace the Gemini extractors (one-email and batch) with the regex baseline."""
    from agent import tools
    from agent.parsing import regex_extract

    monkeypatch.setattr(tools, "_extract", regex_extract)
    monkeypatch.setattr(tools, "_extract_many", tools.batched(regex_extract))


@pytest.fixture
def emails():
    from agent.tools import load_sample_emails

    return {e["id"]: e["text"] for e in load_sample_emails()}
