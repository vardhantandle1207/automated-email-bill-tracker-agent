"""CONCEPT 4: GUARDRAILS (rules enforced by code, not by asking the model nicely).

An LLM can misread an email, invent a number, or be tricked by text inside an
email. So we never just trust it:

    Input guardrail   clean_email()  checks what goes INTO the model
    Output guardrail  check_bill()   checks what comes OUT of the model
    Loop guardrail    MAX_STEPS      stops an agent that never finishes

The strongest guardrail is in tools.py: the agent simply has no tool that can
pay, delete or send anything, so no prompt can make it do that.
"""

import re
from datetime import date

MAX_STEPS = 8           # the agent loop may ask the LLM at most this many times
MAX_EMAIL_CHARS = 4000  # longer emails are cut, so one huge email cannot flood the model

# Phrases that try to give orders to the agent (a "prompt injection").
INJECTION = re.compile(
    r"(ignore|disregard|forget) (all |any |the |your )?(previous|prior|above|earlier) (instructions|rules)", re.I
)


def clean_email(text: str) -> str:
    """INPUT guardrail: an email is untrusted text written by a stranger."""
    # Step 1: Block emails that try to give the agent instructions.
    if INJECTION.search(text):
        return "[BLOCKED by guardrail: this email tries to give instructions to the agent. Skip it.]"
    # Step 2: Cut very long emails.
    return text[:MAX_EMAIL_CHARS]


def _simple(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def numbers_in(text: str) -> list[float]:
    """Every number written in the text, whichever way it is punctuated."""
    numbers = []
    for token in re.findall(r"\d[\d.,]*\d|\d", text):
        if re.fullmatch(r"[\d.]+,\d{2}", token):  # European style: 1.234,56 means 1234.56
            token = token.replace(".", "").replace(",", ".")
        try:
            numbers.append(float(token.replace(",", "")))  # Indian/US style: 1,24,503.22
        except ValueError:
            pass  # not a number after all, e.g. the date 31.10.2026
    return numbers


def check_bill(bill: dict, email_text: str, currencies: list[str]) -> list[str]:
    """OUTPUT guardrail: list what is wrong with a bill the model extracted. Empty list = OK."""
    issues = []

    # Step 1: The amount must be a number that is really written in the email.
    if not any(abs(n - bill["amount"]) < 0.01 for n in numbers_in(email_text)):
        issues.append(f"amount {bill['amount']} is not written in the email")

    # Step 2: The currency must be one we can convert.
    if bill["currency"] not in currencies:
        issues.append(f"currency {bill['currency']} is not one of {currencies}")

    # Step 3: The vendor must be named in the email (and start with a letter or digit).
    if not bill["vendor"][:1].isalnum() or _simple(bill["vendor"]) not in _simple(email_text):
        issues.append(f"vendor '{bill['vendor']}' is not named in the email")

    # Step 4: The due date, if given, must be a real date in YYYY-MM-DD form.
    try:
        date.fromisoformat(bill["due_date"] or "2000-01-01")
    except ValueError:
        issues.append(f"due_date {bill['due_date']} is not a valid YYYY-MM-DD date")

    return issues
