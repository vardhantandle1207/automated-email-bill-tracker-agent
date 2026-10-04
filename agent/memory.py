"""CONCEPT 3: MEMORY.

Short-term memory: what the agent knows during ONE run. It is gone when the run ends.
Long-term memory:  what the agent remembers BETWEEN runs. Here it is a CSV file
                   with one row per logged bill, which you can open in Excel.
"""

import csv
import os
import re
from datetime import datetime


# ---------------- Short-term memory (one run) ----------------

class ShortTermMemory:
    def __init__(self):
        self.messages = []  # the conversation: system prompt, plan, tool calls, tool results
        self.emails = {}    # email_id -> email text, filled in by the fetch_emails tool
        self.bills = {}     # email_id -> bill that passed check_bill


# ---------------- Long-term memory (across runs) ----------------

COLUMNS = ["logged_at", "email_id", "vendor", "amount", "currency",
           "amount_inr", "due_date", "paid", "autopay", "flags"]


def _path() -> str:
    return os.getenv("MEMORY_PATH", "data/bills.csv")


def vendor_key(name: str) -> str:
    """'HDFC Bank' and 'hdfc-bank' are the same vendor: compare lowercase letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def recall(vendor: str | None = None) -> list[dict]:
    """Read past bills, oldest first. Give a vendor to get only that vendor's bills."""
    # Step 1: No file yet means the agent has no memories.
    if not os.path.exists(_path()):
        return []
    # Step 2: Read every row, then keep the ones for this vendor.
    with open(_path(), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if vendor is None or vendor_key(r["vendor"]) == vendor_key(vendor)]


def remember(bill: dict) -> bool:
    """Append one bill to the file. Returns False if it was already there."""
    # Step 1: Skip duplicates: the same email, or the same vendor with the same due date.
    for row in recall(bill["vendor"]):
        if row["email_id"] == bill["email_id"] or (bill["due_date"] and row["due_date"] == bill["due_date"]):
            return False
    # Step 2: Add one row at the end. We only ever append: no edits, no deletes.
    os.makedirs(os.path.dirname(_path()) or ".", exist_ok=True)
    with open(_path(), "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow({**bill, "logged_at": datetime.now().isoformat(timespec="seconds"),
                         "due_date": bill["due_date"] or "", "flags": "; ".join(bill["flags"])})
    return True
