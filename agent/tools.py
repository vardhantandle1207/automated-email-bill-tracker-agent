"""CONCEPT 2: TOOLS and TOOL CALLING (the agent's hands).

An LLM can only write text. A "tool" is a normal Python function that we let the
LLM ask us to run. Tool calling works like this:

    1. We describe each tool to the LLM (name, what it does, its arguments).
    2. The LLM replies "please call check_bill with these arguments".
    3. OUR code runs the function and sends the result back to the LLM.

This agent has only three tools. It can read emails and append rows to a log.
It has no tool to pay, delete or send anything.
"""

import glob
import os
from datetime import date

from . import guardrails
from . import memory as long_term

RATES_TO_INR = {"INR": 1.0, "USD": 83.0, "EUR": 90.0, "GBP": 105.0}
SAMPLE_INBOX = os.path.join(os.path.dirname(__file__), "..", "data", "sample_emails", "*.txt")


def today() -> date:
    """Today's date. The eval and the tests set TODAY so results never change."""
    return date.fromisoformat(os.getenv("TODAY") or date.today().isoformat())


# ---------------- Tool 1: read the inbox ----------------

def fetch_emails(memory) -> list[dict]:
    # Step 1: Read the emails: the sample folder by default, or real Gmail (read-only).
    if os.getenv("INBOX", "mock") == "gmail":
        from .gmail import read_gmail
        emails = read_gmail()
    else:
        emails = []
        for path in sorted(glob.glob(os.getenv("SAMPLE_INBOX", SAMPLE_INBOX))):
            with open(path, encoding="utf-8") as f:
                emails.append({"email_id": os.path.basename(path), "text": f.read()})

    # Step 2: Input guardrail: block injected instructions, cut very long emails.
    # Step 3: Keep the emails in short-term memory so check_bill can re-read them.
    for email in emails:
        memory.emails[email["email_id"]] = guardrails.clean_email(email["text"])
    return [{"email_id": email_id, "text": text} for email_id, text in memory.emails.items()]


# ---------------- Tool 2: check one bill ----------------

def find_flags(bill: dict, history: list[dict]) -> list[str]:
    """Plain Python rules (no LLM): is this bill overdue, or higher than usual?"""
    flags = []
    # Rule 1: Overdue = the due date has passed, and it is neither paid nor on autopay.
    due = date.fromisoformat(bill["due_date"]) if bill["due_date"] else None
    if due and due < today() and not bill["paid"] and not bill["autopay"]:
        flags.append(f"OVERDUE: was due {due}, {(today() - due).days} days ago, not paid and not on autopay")
    # Rule 2: Above trend = more than 20% above the average of this vendor's last 3 bills.
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

    # Step 1: Output guardrail: do these values really appear in the email?
    #         If not, tell the LLM what is wrong so it can fix it and try again.
    if email_id not in memory.emails:
        return {"ok": False, "issues": [f"unknown email_id {email_id}"]}
    issues = guardrails.check_bill(bill, memory.emails[email_id], list(RATES_TO_INR))
    if issues:
        return {"ok": False, "issues": issues}

    # Step 2: Convert the amount to rupees so all bills can be compared.
    bill["amount_inr"] = round(bill["amount"] * RATES_TO_INR[bill["currency"]], 2)

    # Step 3: Look up this vendor's past bills in long-term memory and apply the rules.
    history = [row for row in long_term.recall(vendor) if row["email_id"] != email_id]
    bill["flags"] = find_flags(bill, history)

    # Step 4: Keep the checked bill in short-term memory. log_bill will save this exact copy.
    memory.bills[email_id] = bill
    return {"ok": True, "amount_inr": bill["amount_inr"], "flags": bill["flags"]}


# ---------------- Tool 3: save one bill ----------------

def log_bill(memory, email_id) -> dict:
    # Step 1: Guardrail: only a bill that passed check_bill can be saved.
    bill = memory.bills.get(email_id)
    if bill is None:
        return {"logged": False, "error": "Call check_bill for this email first."}
    # Step 2: Append it to long-term memory. False means it was already logged before.
    if "logged" not in bill:
        bill["logged"] = long_term.remember(bill)
    return {"logged": bill["logged"]}


# ---------------- What the LLM is told about the tools ----------------

def describe(name: str, description: str, arguments: dict, required: list[str]) -> dict:
    """Describe one tool in the JSON format the LLM expects."""
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

# The only functions the LLM is allowed to run.
TOOLS = {"fetch_emails": fetch_emails, "check_bill": check_bill, "log_bill": log_bill}
