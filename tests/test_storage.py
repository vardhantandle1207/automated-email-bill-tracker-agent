import csv
import json

from agent.storage import SHEET_COLUMNS, add_history, append_row, load_history


def record(**kw):
    return {"vendor": "Netflix", "amount_base": 649.0, "base_currency": "INR", "due_date": "2026-10-28",
            "paid": True, "autopay": False, "flagged": False, "reasons": [], "needs_review": False,
            "source_id": "netflix.txt"} | kw


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_append_writes_header_and_dedupes_on_vendor_and_due_date(isolated_env):
    assert append_row(record()) is True
    assert append_row(record(vendor="NETFLIX", source_id="again")) is False  # same vendor_key + due_date
    assert append_row(record(due_date="2026-11-28")) is True
    rows = read_csv(isolated_env / "bills.csv")
    assert list(rows[0]) == SHEET_COLUMNS
    assert [r["due_date"] for r in rows] == ["2026-10-28", "2026-11-28"]


def test_undated_bills_dedupe_on_email_id(isolated_env):
    assert append_row(record(vendor="GitHub", due_date=None, source_id="sep")) is True
    assert append_row(record(vendor="GitHub", due_date=None, source_id="oct")) is True  # next month's receipt
    assert append_row(record(vendor="GitHub", due_date=None, source_id="sep")) is False  # same email again
    assert [r["source_id"] for r in read_csv(isolated_env / "bills.csv")] == ["sep", "oct"]


def test_csv_cells_cannot_become_formulas(isolated_env):
    append_row(record(vendor="=HYPERLINK(\"http://x\")", reasons=["-1 above"]))
    row = read_csv(isolated_env / "bills.csv")[0]
    assert row["vendor"].startswith("'=")
    assert row["flag_reasons"] == "'-1 above"


def test_history_appends_once_per_due_date(isolated_env):
    entry = {"due_date": "2026-10-12", "amount_base": 1240.5, "source_id": "a"}
    add_history("TSSPDCL", entry)
    add_history("tsspdcl", {**entry, "source_id": "b"})
    assert load_history("TSSPDCL") == [entry]
    assert list(json.loads((isolated_env / "history.json").read_text())) == ["tsspdcl"]
