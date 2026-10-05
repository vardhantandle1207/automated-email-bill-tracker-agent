"""The three tools the model can call, and their descriptions.

    fetch_emails  read the inbox (sample folder or Gmail, read-only)
    check_bill    verify one extracted bill, convert to INR, flag anomalies
    log_bill      append a checked bill to the log

There is deliberately no tool that pays, sends or deletes.
"""

import glob
import os
from datetime import date

from . import guardrails
from . import memory as long_term

RATES_TO_INR = {"INR": 1.0, "USD": 83.0, "EUR": 90.0, "GBP": 105.0}
SAMPLE_INBOX = os.path.join(os.path.dirname(__file__), "..", "data", "sample_emails", "*.txt")


def today() -> date:
    """Today's date. The eval and tests pin it with TODAY so results are repeatable."""
    return date.fromisoformat(os.getenv("TODAY") or date.today().isoformat())


def fetch_emails(memory) -> list[dict]:
    if os.getenv("INBOX", "mock") == "gmail":
        from .gmail import read_gmail
        emails = read_gmail()
    else:
        emails = []
        for path in sorted(glob.glob(os.getenv("SAMPLE_INBOX", SAMPLE_INBOX))):
            with open(path, encoding="utf-8") as f:
                emails.append({"email_id": os.path.basename(path), "text": f.read()})

    # keep the cleaned text: check_bill verifies against exactly what the model saw
    for email in emails:
        memory.emails[email["email_id"]] = guardrails.clean_email(email["text"])
    return [{"email_id": email_id, "text": text} for email_id, text in memory.emails.items()]


def find_flags(bill: dict, history: list[dict]) -> list[str]:
    """Overdue and above-trend rules. Plain arithmetic, no LLM."""
    flags = []
    # overdue: past the due date, not paid, not on autopay
    due = date.fromisoformat(bill["due_date"]) if bill["due_date"] else None
    if due and due < today() and not bill["paid"] and not bill["autopay"]:
        flags.append(f"OVERDUE: was due {due}, {(today() - due).days} days ago, not paid and not on autopay")
    # above trend: over 20% more than the mean of this vendor's last 3 bills (needs 2)
    past = [float(row["amount_inr"]) for row in history][-3:]
    if len(past) >= 2:
        average = sum(past) / len(past)
        if bill["amount_inr"] > average * 1.20:
            percent = (bill["amount_inr"] / average - 1) * 100
            flags.append(f"ABOVE TREND: ₹{bill['amount_inr']:,.2f} is {percent:.0f}% above "
                         f"the ₹{average:,.2f} average of the last {len(past)} bills")
    return flags


def check_bill(memory, email_id, vendor, amount, currency, due_date=None, paid=False, autopay=False) -> dict:
    bill = {"email_id": email_id, "vendor": vendor, "amount": float(amount), "currency": currency.upper(),
            "due_date": due_date or None, "paid": bool(paid), "autopay": bool(autopay)}

    # on failure the issues go back to the model so it can correct the values and retry
    if email_id not in memory.emails:
        return {"ok": False, "issues": [f"unknown email_id {email_id}"]}
    issues = guardrails.check_bill(bill, memory.emails[email_id], list(RATES_TO_INR))
    if issues:
        return {"ok": False, "issues": issues}

    bill["amount_inr"] = round(bill["amount"] * RATES_TO_INR[bill["currency"]], 2)

    # leave out this email's own row so a re-run is not compared with itself
    history = [row for row in long_term.recall(vendor) if row["email_id"] != email_id]
    bill["flags"] = find_flags(bill, history)

    # log_bill saves this exact copy, so the model cannot change it after the check
    memory.bills[email_id] = bill
    return {"ok": True, "amount_inr": bill["amount_inr"], "flags": bill["flags"]}


def log_bill(memory, email_id) -> dict:
    bill = memory.bills.get(email_id)
    if bill is None:
        return {"logged": False, "error": "Call check_bill for this email first."}
    # False means it was already in the log
    if "logged" not in bill:
        bill["logged"] = long_term.remember(bill)
    return {"logged": bill["logged"]}


def describe(name: str, description: str, arguments: dict, required: list[str]) -> dict:
    """One tool description in the OpenAI function-calling format."""
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": arguments, "required": required}}}


EMAIL_ID = {"type": "string", "description": "The email_id returned by fetch_emails"}

TOOL_SCHEMAS = [
    describe("fetch_emails", "Read the inbox (read-only). Returns a list of {email_id, text}.", {}, []),
    describe(
        "check_bill",
        "Check the details you extracted from ONE bill email against the email itself, convert the "
        "amount to INR and flag anomalies. Returns {ok, issues} if a value is wrong, else {ok, amount_inr, flags}.",
        {
            "email_id": EMAIL_ID,
            "vendor": {"type": "string", "description": "Company that issued the bill, e.g. Netflix"},
            "amount": {"type": "number", "description": "Total amount due or charged, exactly as written. "
                       "Use the total, not the minimum due or a line item."},
            "currency": {"type": "string", "description": "INR, USD, EUR or GBP, from the symbol or context"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD date the bill must be paid or will be "
                         "charged. For a receipt of a subscription, use the next billing or renewal date if "
                         "the email states one. Indian senders write day first: 12-10-2026 is 12 October. "
                         "Leave this out if the email states no such date."},
            "paid": {"type": "boolean", "description": "True only if the email confirms the payment already went through"},
            "autopay": {"type": "boolean", "description": "True only if the email says this amount WILL be charged "
                        "or debited automatically. False for payments already made."},
        },
        ["email_id", "vendor", "amount", "currency", "paid", "autopay"],
    ),
    describe("log_bill", "Save a bill that passed check_bill to the bill log. Append-only.",
             {"email_id": EMAIL_ID}, ["email_id"]),
]

# allowlist: act() refuses any name that is not here
TOOLS = {"fetch_emails": fetch_emails, "check_bill": check_bill, "log_bill": log_bill}
