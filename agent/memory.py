"""Agent memory.

Short-term: state for one run (conversation, fetched emails, checked bills).
Long-term: the bill log, one row per bill, in data/bills.csv or in a Google
Sheet when GOOGLE_SHEET_ID is set.
"""

import csv
import os
import re
from datetime import datetime


class ShortTermMemory:
    def __init__(self):
        self.messages = []  # the conversation: system prompt, plan, tool calls, tool results
        self.emails = {}    # email_id -> email text, filled in by the fetch_emails tool
        self.bills = {}     # email_id -> bill that passed check_bill


COLUMNS = ["logged_at", "email_id", "vendor", "amount", "currency",
           "amount_inr", "due_date", "paid", "autopay", "flags"]


def _path() -> str:
    return os.getenv("MEMORY_PATH", "data/bills.csv")


def vendor_key(name: str) -> str:
    """'HDFC Bank' and 'hdfc-bank' are the same vendor: compare lowercase letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def recall(vendor: str | None = None) -> list[dict]:
    """Read past bills, oldest first. Give a vendor to get only that vendor's bills."""
    if os.getenv("GOOGLE_SHEET_ID"):
        from .sheets import read_sheet
        rows = read_sheet()
    elif os.path.exists(_path()):
        with open(_path(), newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = []  # nothing logged yet
    return [r for r in rows if vendor is None or vendor_key(r["vendor"]) == vendor_key(vendor)]


def remember(bill: dict) -> bool:
    """Append one bill to the log. Returns False if it was already there."""
    # a duplicate is the same email, or the same vendor with the same due date
    for row in recall(bill["vendor"]):
        if row["email_id"] == bill["email_id"] or (bill["due_date"] and row["due_date"] == bill["due_date"]):
            return False
    row = {**bill, "logged_at": datetime.now().isoformat(timespec="seconds"),
           "due_date": bill["due_date"] or "", "flags": "; ".join(bill["flags"])}
    # append only: rows are never edited or deleted
    if os.getenv("GOOGLE_SHEET_ID"):
        from .sheets import append_to_sheet
        append_to_sheet(COLUMNS, [row[column] for column in COLUMNS])
        return True
    os.makedirs(os.path.dirname(_path()) or ".", exist_ok=True)
    with open(_path(), "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
    return True
