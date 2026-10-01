"""Deterministic text evidence used to check (and baseline) extractions.

Nothing here calls a model. These are regex readers for the amounts, currencies,
and dates that literally appear in an email. `verify` uses them to catch fields
the model got wrong; `regex_extract` is the no-LLM baseline that eval.py can run
offline.
"""

import re
from datetime import date
from typing import Optional

from .currency import BASE_CURRENCY, to_base

FIELDS = ("vendor", "amount", "currency", "due_date", "paid", "autopay")

_CURRENCY_MARKERS = {
    "INR": r"₹|\bRs\.?|\bINR\b",
    "USD": r"\$|\bUSD\b",
    "EUR": r"€|\bEUR\b",
    "GBP": r"£|\bGBP\b",
}
_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_MONEY_WORDS = re.compile(r"amount|total|due|charged|payable|bill|balance", re.I)
_DUE_WORDS = re.compile(r"due|next billing|pay by|payable by|renews?", re.I)
_PAID_WORDS = re.compile(
    r"\b(?:was|been) (?:charged|paid|received)\b|payment received|thank you for your payment", re.I
)
_AUTOPAY_WORDS = re.compile(
    r"\b(?:automatically|auto-?)\s*(?:be\s+)?(?:charged|debited|deducted|paid)\b|"
    r"\bwill be (?:charged|debited) (?:automatically|to your (?:card|account) on file)\b|"
    r"\bauto-?pay\b|\bauto-?debit\b|\bstanding instruction\b",
    re.I,
)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON = "|".join(_MONTHS)
_DMY_NAME = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})[a-z]*\.?,?\s+(\d{{4}})\b", re.I)
_MDY_NAME = re.compile(rf"\b({_MON})[a-z]*\.?\s+(\d{{1,2}})\b(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")


def vendor_key(vendor: str) -> str:
    """Canonical vendor id used for history lookups and dedupe: lowercase alphanumerics."""
    return re.sub(r"[^a-z0-9]", "", (vendor or "").lower())


def parse_iso(value: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD, returning None for missing or malformed values."""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _to_float(num: str) -> float:
    return float(num.replace(",", ""))


def _safe_date(y: str, m: int, d: str) -> Optional[date]:
    try:
        return date(int(y), m, int(d))
    except ValueError:
        return None


def _line_at(text: str, pos: int) -> str:
    end = text.find("\n", pos)
    return text[text.rfind("\n", 0, pos) + 1 : end if end != -1 else len(text)]


def money_mentions(text: str) -> list[tuple[float, str, str]]:
    """(amount, currency, line) for every number written next to a currency marker, in order."""
    found = []
    for code, marker in _CURRENCY_MARKERS.items():
        for m in re.finditer(rf"(?:{marker})[ \t]?({_NUM})|({_NUM})[ \t]?(?:{marker})", text):
            found.append((m.start(), _to_float(m.group(1) or m.group(2)), code, _line_at(text, m.start())))
    return [f[1:] for f in sorted(found)]


def dates_mentioned(text: str) -> list[tuple[date, str]]:
    """(date, line) for every date in the text. Ambiguous 12-10-2026 yields DMY then MDY."""
    out = []
    for line in text.splitlines():
        for d, mon, y in _DMY_NAME.findall(line):
            out.append((_safe_date(y, _MONTHS.index(mon[:3].lower()) + 1, d), line))
        for mon, d, y in _MDY_NAME.findall(line):
            out.append((_safe_date(y, _MONTHS.index(mon[:3].lower()) + 1, d), line))
        for y, m, d in _ISO.findall(line):
            out.append((_safe_date(y, int(m), d), line))
        for a, b, y in _NUMERIC.findall(line):
            out += [(_safe_date(y, int(b), a), line), (_safe_date(y, int(a), b), line)]
    return [(d, line) for d, line in out if d]


def find_issues(record: dict, email_text: str) -> list[str]:
    """One specific, human-readable issue per field that the email text does not support."""
    issues = []
    mentions = money_mentions(email_text)
    amounts = {a for a, _, _ in mentions} or {
        _to_float(n) for line in email_text.splitlines() if _MONEY_WORDS.search(line)
        for n in re.findall(_NUM, line)
    }
    amount = record.get("amount")
    if amount is None or not any(abs(a - float(amount)) < 0.01 for a in amounts):
        issues.append(f"amount {amount} does not appear in the email (candidates: {sorted(amounts)})")
    currencies = {c for _, c, _ in mentions}
    if currencies and (record.get("currency") or "").upper() not in currencies:
        issues.append(f"currency {record.get('currency')} conflicts with symbols in the email ({sorted(currencies)})")
    vendor = record.get("vendor") or ""
    tokens = re.findall(r"[a-z0-9]{3,}", vendor.lower())
    if not vendor or not (vendor_key(vendor) in vendor_key(email_text) or
                          (tokens and all(t in email_text.lower() for t in tokens))):
        issues.append(f"vendor {vendor!r} is not named in the email")
    due = record.get("due_date")
    mentioned = dates_mentioned(email_text)
    if due and parse_iso(due) not in {d for d, _ in mentioned}:
        issues.append(f"due_date {due} does not match any date in the email")
    elif not due and any(_DUE_WORDS.search(line) for _, line in mentioned):
        issues.append("due_date is null but the email has a dated due/next-billing line")
    return issues


def regex_extract(email_text: str, hint: str = "") -> dict:
    """No-LLM baseline extractor with the same output shape as extract_invoice.

    Vendor = From-header display name; amount = first currency-marked number on a
    money line; due_date = first date on a due/next-billing line. `hint` is ignored
    (accepted so it can stand in for the Gemini extractor inside verify).
    """
    sender = re.search(r"^From:\s*\"?([^<\"\n]+?)\"?\s*<", email_text, re.M)
    mentions = money_mentions(email_text)
    best = next((m for m in mentions if _MONEY_WORDS.search(m[2])), mentions[0] if mentions else None)
    amount, currency = (best[0], best[1]) if best else (0.0, BASE_CURRENCY)
    due = next((d for d, line in dates_mentioned(email_text) if _DUE_WORDS.search(line)), None)
    return {
        "vendor": sender.group(1).strip() if sender else "",
        "amount": amount,
        "currency": currency,
        "due_date": due.isoformat() if due else None,
        "paid": bool(_PAID_WORDS.search(email_text)),
        "autopay": bool(_AUTOPAY_WORDS.search(email_text)),
        "amount_base": to_base(amount, currency),
        "base_currency": BASE_CURRENCY,
    }
