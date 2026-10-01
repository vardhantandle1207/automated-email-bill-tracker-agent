"""State backends: the sheet (the user-facing log) and per-vendor bill history.

Both are append-only from the agent's side: rows and history entries are added,
never edited or deleted. Each has a cloud backend and a local-file fallback so
the whole pipeline runs offline:

    sheet:   Google Sheet if GOOGLE_SHEET_ID is set, else SHEET_CSV_PATH (CSV)
    history: Firestore if HISTORY_BACKEND=firestore, else HISTORY_PATH (JSON)
"""

import csv
import json
import os
from datetime import datetime, timezone

from .parsing import vendor_key

SHEET_COLUMNS = [
    "logged_at", "vendor", "amount_base", "base_currency", "due_date", "paid",
    "flagged", "flag_reasons", "needs_review", "source_id", "autopay",
]


def _dedupe_key(vendor: str, due_date) -> tuple[str, str]:
    return vendor_key(vendor), due_date or ""


def _row(record: dict) -> list:
    return [
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        record["vendor"], record["amount_base"], record["base_currency"],
        record.get("due_date") or "", record.get("paid", False),
        record.get("flagged", False), "; ".join(record.get("reasons", [])),
        record.get("needs_review", False), record.get("source_id", ""),
        record.get("autopay", False),
    ]


def _csv_safe(value):
    """Stop spreadsheet apps from evaluating email-derived text as a formula."""
    return f"'{value}" if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value


def append_row(record: dict) -> bool:
    """Append one bill row unless (vendor, due_date) is already logged. Returns True if appended."""
    key = _dedupe_key(record["vendor"], record.get("due_date"))
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if sheet_id:
        import google.auth
        import gspread

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
        ws = gspread.authorize(creds).open_by_key(sheet_id).sheet1
        rows = ws.get_all_values()
        if not rows:
            ws.append_row(SHEET_COLUMNS)
            rows = [SHEET_COLUMNS]
        v, d = rows[0].index("vendor"), rows[0].index("due_date")
        if any(_dedupe_key(r[v], r[d]) == key for r in rows[1:] if len(r) > max(v, d)):
            return False
        ws.append_row(_row(record), value_input_option="RAW")  # RAW: never evaluate as formulas
        return True

    path = os.environ.get("SHEET_CSV_PATH", "data/bills.csv")
    rows = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    if any(_dedupe_key(r["vendor"], r["due_date"]) == key for r in rows):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(SHEET_COLUMNS)
        writer.writerow([_csv_safe(v) for v in _row(record)])
    return True


def _firestore_doc(vendor: str):
    from google.cloud import firestore

    collection = os.environ.get("FIRESTORE_COLLECTION", "vendor_history")
    return firestore.Client().collection(collection).document(vendor_key(vendor))


def _history_path() -> str:
    return os.environ.get("HISTORY_PATH", "data/history.json")


def _read_json() -> dict:
    if not os.path.exists(_history_path()):
        return {}
    with open(_history_path(), encoding="utf-8") as f:
        return json.load(f)


def load_history(vendor: str) -> list[dict]:
    """All stored bills for a vendor as [{due_date, amount_base, source_id}]."""
    if os.environ.get("HISTORY_BACKEND") == "firestore":
        doc = _firestore_doc(vendor).get()
        return (doc.to_dict() or {}).get("entries", []) if doc.exists else []
    return _read_json().get(vendor_key(vendor), [])


def add_history(vendor: str, entry: dict) -> None:
    """Record a bill in the vendor's history unless that due_date is already stored."""
    if any(e.get("due_date") == entry.get("due_date") for e in load_history(vendor)):
        return
    if os.environ.get("HISTORY_BACKEND") == "firestore":
        from google.cloud import firestore

        _firestore_doc(vendor).set({"vendor": vendor, "entries": firestore.ArrayUnion([entry])}, merge=True)
        return
    data = _read_json()
    data.setdefault(vendor_key(vendor), []).append(entry)
    os.makedirs(os.path.dirname(_history_path()) or ".", exist_ok=True)
    with open(_history_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
