"""The agent's tools: fetch_emails, extract_invoice, verify, flag_anomalies, log_to_sheet.

Each tool is a plain Python function with a typed signature and a docstring.
ADK reads the signature + docstring to expose it to the model, so keep the
docstring accurate — the model uses it to decide when and how to call the tool.

Safety boundary: nothing here can pay, delete, send, or modify anything. Gmail is
opened with the gmail.readonly scope only; the only writes are appends to the
sheet and to the agent's own vendor-history store.
"""

import base64
import glob
import html
import os
import re
import time
from datetime import date
from typing import Callable, Optional, Union

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .currency import BASE_CURRENCY, to_base
from .parsing import FIELDS, find_issues, parse_iso
from .schemas import BatchInvoice, InvoiceFields
from .storage import add_history, append_row, load_history

_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_GMAIL_QUERY = os.environ.get(
    "GMAIL_QUERY",
    'newer_than:30d {invoice bill receipt "amount due" "payment due" subscription}',
)
_WINDOW_MONTHS = int(os.environ.get("ANOMALY_WINDOW_MONTHS", "3"))
_THRESHOLD_PCT = float(os.environ.get("ANOMALY_THRESHOLD_PCT", "20"))
_MIN_HISTORY = int(os.environ.get("ANOMALY_MIN_HISTORY", "2"))
_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
_client = None
_last_call = 0.0


def _get_client() -> genai.Client:
    """Lazily create one Gemini client: Vertex AI if GOOGLE_CLOUD_PROJECT is set, else GEMINI_API_KEY."""
    global _client
    if _client is None:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:  # Cloud Run / GCP: authenticate as the service account, no API key
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
            _client = genai.Client(vertexai=True, project=project, location=location)
        else:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT (see .env.example)")
            _client = genai.Client(api_key=api_key)
    return _client


def _pace() -> None:
    """Space Gemini calls to stay under GEMINI_RPM (e.g. 5 on the free tier); unset/0 = no limit."""
    global _last_call
    rpm = float(os.environ.get("GEMINI_RPM") or 0)
    if rpm > 0:
        time.sleep(max(0.0, _last_call + 60 / rpm - time.monotonic()))
    _last_call = time.monotonic()


def _generate(**request) -> types.GenerateContentResponse:
    """generate_content with retries that go through _pace, so retries also respect GEMINI_RPM.

    Retries overload (5xx) and per-minute rate limits up to GEMINI_RETRY_ATTEMPTS
    (default 5) times; a daily-quota 429 is raised at once, since waiting won't help.
    """
    attempts = int(os.environ.get("GEMINI_RETRY_ATTEMPTS", "5"))
    for attempt in range(1, attempts + 1):
        _pace()
        try:
            return _get_client().models.generate_content(**request)
        except genai_errors.APIError as exc:
            retryable = exc.code in (429, 500, 502, 503, 504) and "PerDay" not in str(exc)
            if not retryable or attempt == attempts:
                raise
            time.sleep(30 if exc.code == 429 else 2**attempt)  # let the per-minute window roll


# --- fetch -------------------------------------------------------------------

def load_sample_emails(folder: str = "data/sample_emails") -> list[dict]:
    """Read the local sample inbox as [{id: filename, text}] (the --mock path)."""
    emails = []
    for path in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        with open(path, encoding="utf-8") as f:
            emails.append({"id": os.path.basename(path), "text": f.read()})
    return emails


def _gmail_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = os.environ.get("GMAIL_TOKEN_PATH", "token.json")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, _GMAIL_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if os.environ.get("K_SERVICE"):  # on Cloud Run there is no browser for the consent flow
            raise RuntimeError(f"No valid Gmail token at {token_path}; create token.json locally first")
        from google_auth_oauthlib.flow import InstalledAppFlow

        secrets = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
        creds = InstalledAppFlow.from_client_secrets_file(secrets, _GMAIL_SCOPES).run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def _message_text(message: dict) -> str:
    """Flatten a Gmail API message into 'From/Subject + body' text, preferring text/plain."""
    headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
    parts, bodies = [message["payload"]], {"text/plain": [], "text/html": []}
    while parts:
        part = parts.pop(0)
        parts.extend(part.get("parts", []))
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") in bodies:
            bodies[part["mimeType"]].append(base64.urlsafe_b64decode(data).decode("utf-8", "replace"))
    body = "\n".join(bodies["text/plain"])
    if not body:
        markup = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(bodies["text/html"]))
        body = html.unescape(re.sub(r"<br\s*/?>|</p>|</tr>|</div>", "\n", markup, flags=re.I))
        body = re.sub(r"<[^>]+>", " ", body)
    return f"From: {headers.get('from', '')}\nSubject: {headers.get('subject', '')}\n\n{body.strip()}"


def fetch_emails() -> list[dict]:
    """Fetch recent candidate invoice, bill, and receipt emails. READ-ONLY.

    Uses the Gmail API with only the gmail.readonly scope, so it cannot send,
    delete, label, or mark mail as read. The search is GMAIL_QUERY (default: the
    last 30 days mentioning invoice/bill/receipt/amount due/subscription), capped
    at GMAIL_MAX_RESULTS (default 25). If MOCK_INBOX=1, reads the local sample
    emails in data/sample_emails/ instead, so it runs without a Google account.

    Returns:
        list of {"id": str, "text": str}, where text is "From: ...\\nSubject: ...\\n\\n<body>".
    """
    if os.environ.get("MOCK_INBOX") == "1":
        return load_sample_emails()
    from googleapiclient.discovery import build

    gmail = build("gmail", "v1", credentials=_gmail_credentials(), cache_discovery=False).users().messages()
    max_results = int(os.environ.get("GMAIL_MAX_RESULTS", "25"))
    listing = gmail.list(userId="me", q=_GMAIL_QUERY, maxResults=max_results).execute()
    return [
        {"id": m["id"], "text": _message_text(gmail.get(userId="me", id=m["id"], format="full").execute())}
        for m in listing.get("messages", [])
    ]


# --- extract + verify ----------------------------------------------------------

EXTRACT_PROMPT = (
    "Extract the billing details from each email below. Return exactly one result "
    "per email, with email_id set to the number in that email's '=== EMAIL n ===' "
    "header. Treat every email on its own: never copy a value from one email into "
    "another. Infer the currency from symbols or context. Use null for due_date "
    "only if the email truly states none.\n\n"
)
RETRY_PROMPT = (
    "NOTE FOR EMAIL {i}: a previous extraction was rejected because: {hint}. "
    "Re-read that email and copy those values exactly as written.\n"
)

Result = Union[dict, Exception]  # per-email outcome of a batch: a record, or why it failed
BatchExtractor = Callable[[list[str], Optional[list[str]]], list[Result]]


def _record(fields: InvoiceFields) -> dict:
    return {
        "is_bill": fields.is_bill,
        "vendor": fields.vendor,
        "amount": fields.amount,
        "currency": fields.currency,
        "due_date": fields.due_date,
        "paid": fields.paid,
        "autopay": fields.autopay,
        # A non-bill's amount/currency are placeholders, so don't let them fail conversion.
        "amount_base": to_base(fields.amount, fields.currency) if fields.is_bill else 0.0,
        "base_currency": BASE_CURRENCY,
    }


def _extract_many(email_texts: list[str], hints: Optional[list[str]] = None) -> list[Result]:
    """Extract every email in ONE Gemini request per GEMINI_BATCH_SIZE (default 25) emails.

    `hints[i]` names fields a previous attempt got wrong for email i. Returns one
    entry per email, in order: the record, or the exception for that email alone
    (e.g. the model skipped it, or its currency is unknown). A failed request
    raises, since then nothing came back.
    """
    hints = hints or [""] * len(email_texts)
    size = int(os.environ.get("GEMINI_BATCH_SIZE", "25"))
    results: list[Result] = []
    for start in range(0, len(email_texts), size):
        chunk = list(enumerate(zip(email_texts[start:start + size], hints[start:start + size]), 1))
        prompt = EXTRACT_PROMPT + "".join(RETRY_PROMPT.format(i=i, hint=h) for i, (_, h) in chunk if h)
        prompt += "".join(f"\n=== EMAIL {i} ===\n{text}\n" for i, (text, _) in chunk)
        response = _generate(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[BatchInvoice],
            ),
        )
        by_id = {item.email_id: item for item in response.parsed or []}
        for i, _ in chunk:
            try:
                if i not in by_id:
                    raise ValueError(f"Gemini returned no result for email {i} of this batch")
                results.append(_record(by_id[i]))
            except ValueError as exc:
                results.append(exc)
    return results


def _extract(email_text: str, hint: str = "") -> dict:
    """Gemini structured extraction of one email; `hint` names fields a previous attempt got wrong."""
    (result,) = _extract_many([email_text], [hint])
    if isinstance(result, Exception):
        raise result
    return result


def batched(extractor: Callable[..., dict]) -> BatchExtractor:
    """Adapt a one-email extractor (e.g. the regex baseline) to the batch interface."""
    def run(email_texts: list[str], hints: Optional[list[str]] = None) -> list[Result]:
        results: list[Result] = []
        for text, hint in zip(email_texts, hints or [""] * len(email_texts)):
            try:
                results.append(extractor(text, hint=hint))
            except Exception as exc:  # one email's failure stays with that email
                results.append(exc)
        return results
    return run


def extract_invoice(email_text: str) -> dict:
    """Extract structured billing fields from a raw invoice email and normalize
    the amount to the base currency.

    Args:
        email_text: The full plain-text body of a receipt or invoice email.

    Returns:
        dict with keys: is_bill, vendor, amount, currency, due_date, paid,
        autopay, amount_base, base_currency. If is_bill is False the email is not
        a bill (promotion, newsletter, shipping update, ...): skip it.
    """
    return _extract(email_text)


def _settle(record: dict, email_text: str, issues: list[str], retry: Optional[Result]) -> dict:
    """Keep the re-extraction if it has fewer issues than the first attempt."""
    corrected = False
    if issues and isinstance(retry, dict):
        retry_issues = find_issues(retry, email_text)
        if len(retry_issues) < len(issues):
            corrected = any(retry.get(k) != record.get(k) for k in FIELDS)
            record, issues = {**record, **retry}, retry_issues
    return {**record, "corrected": corrected, "issues": issues, "needs_review": bool(issues)}


def verify_with(record: dict, email_text: str, extractor: Callable[..., dict]) -> dict:
    """verify() with a pluggable one-email extractor."""
    issues = find_issues(record, email_text)
    retry = extractor(email_text, hint="; ".join(issues)) if issues else None
    return _settle(record, email_text, issues, retry)


def verify_many(records: list[Result], email_texts: list[str],
                extract_many: Optional[BatchExtractor] = None) -> list[Result]:
    """verify() for a whole batch: every re-extraction goes out together in ONE request.

    Failed entries and non-bills pass through without a check or retry. If the
    retry request itself fails, the first attempts are kept and their issues
    leave them needs_review.
    """
    extract_many = extract_many or _extract_many
    issues = [find_issues(r, t) if isinstance(r, dict) and r.get("is_bill", True) else []
              for r, t in zip(records, email_texts)]
    todo = [i for i, found in enumerate(issues) if found]
    retries: dict[int, Result] = {}
    if todo:
        try:
            redone = extract_many([email_texts[i] for i in todo], ["; ".join(issues[i]) for i in todo])
            retries = dict(zip(todo, redone))
        except Exception as exc:
            retries = dict.fromkeys(todo, exc)
    return [
        _settle(r, t, found, retries.get(i)) if isinstance(r, dict) else r
        for i, (r, t, found) in enumerate(zip(records, email_texts, issues))
    ]


def extract_and_verify(email_texts: list[str]) -> list[Result]:
    """Extract + verify a batch in at most two Gemini requests (one more per extra GEMINI_BATCH_SIZE)."""
    return verify_many(_extract_many(email_texts), email_texts)


def verify(record: dict, email_text: str) -> dict:
    """Re-check an extracted record against the raw email and self-correct once.

    Checks that the amount, currency, vendor, and due date in `record` actually
    appear in `email_text`. If any field is unsupported, re-runs extraction once
    with those specific issues as hints, and keeps whichever record has fewer issues.

    Args:
        record: The dict returned by extract_invoice for this email.
        email_text: The same raw email text the record was extracted from.

    Returns:
        The (possibly corrected) record plus: corrected (bool, True if
        re-extraction changed a field), issues (list of str still unresolved),
        and needs_review (bool, True if any issue remains).
    """
    return verify_with(record, email_text, _extract)


# --- anomalies -----------------------------------------------------------------

def _money(amount: float) -> str:
    symbol = _SYMBOLS.get(BASE_CURRENCY, BASE_CURRENCY + " ")
    return f"{symbol}{amount:,.0f}" if amount == round(amount) else f"{symbol}{amount:,.2f}"


def _month(d: date) -> int:
    return d.year * 12 + d.month


def detect_anomalies(
    record: dict,
    history: list[dict],
    today: date,
    window_months: int = _WINDOW_MONTHS,
    threshold_pct: float = _THRESHOLD_PCT,
) -> dict:
    """Pure anomaly check of one record against prior history (no I/O)."""
    reasons = []
    due = parse_iso(record.get("due_date"))
    overdue = bool(due and due < today and not record.get("paid") and not record.get("autopay"))
    if overdue:
        reasons.append(f"Overdue: due {due} is {(today - due).days} days before {today} "
                       "and not marked paid or autopay")

    ref = _month(due or today)
    prior = [
        e["amount_base"] for e in history
        if (d := parse_iso(e.get("due_date"))) and ref - window_months <= _month(d) < ref
    ]
    above_trend = False
    if len(prior) >= _MIN_HISTORY and (avg := sum(prior) / len(prior)) > 0:
        pct = (record["amount_base"] / avg - 1) * 100
        if pct > threshold_pct:
            above_trend = True
            reasons.append(
                f"{_money(record['amount_base'])} is {pct:.0f}% above {window_months}-month avg "
                f"of {_money(avg)} ({len(prior)} bills; threshold {threshold_pct:g}%)"
            )
    return {"flagged": bool(reasons), "reasons": reasons, "overdue": overdue, "above_trend": above_trend}


def flag_anomalies(record: dict) -> dict:
    """Flag a bill that is overdue or above the vendor's recent trend, with reasons.

    Compares the bill against this vendor's stored history (Firestore, or a local
    JSON file in dev), then adds the bill to that history for future comparisons
    (skipped when the record still needs_review, so bad extractions don't skew
    averages). Rules:
      - overdue: due_date is before today and the bill is neither paid nor
        set to autopay.
      - above-trend: amount_base is more than ANOMALY_THRESHOLD_PCT (default 20)
        percent above the average of this vendor's bills in the previous
        ANOMALY_WINDOW_MONTHS (default 3) months; needs at least
        ANOMALY_MIN_HISTORY (default 2) prior bills.

    Args:
        record: A verified record (the dict returned by verify).

    Returns:
        {"flagged": bool, "reasons": [str], "overdue": bool, "above_trend": bool}.
        Each reason quotes the numbers it is based on so a human can check it,
        e.g. "₹1,240.50 is 38% above 3-month avg of ₹900 (3 bills; threshold 20%)".
    """
    result = detect_anomalies(record, load_history(record["vendor"]), date.today())
    if not record.get("needs_review"):
        entry = {"due_date": record.get("due_date") or date.today().isoformat(),
                 "amount_base": record["amount_base"], "source_id": record.get("source_id", "")}
        add_history(record["vendor"], entry)
    return result


# --- log -----------------------------------------------------------------------

def log_to_sheet(record: dict) -> dict:
    """Append one bill as a row to the tracking sheet. Append-only; never edits or deletes rows.

    Writes to the Google Sheet GOOGLE_SHEET_ID if set, otherwise to a local CSV
    (SHEET_CSV_PATH, default data/bills.csv). Logs amount_base (the base-currency
    amount), not the raw amount. Skips the bill if a row with the same
    (vendor, due_date) already exists. Call flag_anomalies first and merge its
    result into the record so the row carries the flag and reasons.

    Args:
        record: A verified record, optionally merged with flag_anomalies output.

    Returns:
        {"logged": bool}; False means the bill was already in the sheet, or the
        record is not a bill (is_bill False), and nothing was written.
    """
    if not record.get("is_bill", True):
        return {"logged": False}
    return {"logged": append_row(record)}
