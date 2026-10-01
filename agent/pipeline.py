"""Deterministic batch pipeline over the same tools the ADK agent uses.

    fetch_emails -> extract_invoice -> verify -> flag_anomalies -> log_to_sheet

Extraction is batched: one Gemini request for every email, plus one for any
re-extractions verify asks for. flag_anomalies runs before log_to_sheet so the
sheet row carries the flag and its reasons (the sheet is append-only, so rows
are never updated afterwards).
Used by main.py (Cloud Run) and run.py. `adk run agent` exposes the same tools
to the ReAct loop instead.
"""

from typing import Optional

from .storage import append_row
from .tools import extract_and_verify, fetch_emails, flag_anomalies


def run_batch(emails: Optional[list[dict]] = None) -> dict:
    """Process a batch (default: fetch_emails()). One bad email never stops the batch.

    All emails are extracted in one Gemini request, and any that fail verify are
    re-extracted together in one more, so a run costs at most two requests.
    """
    emails = fetch_emails() if emails is None else emails
    records, errors = [], []
    try:
        results = extract_and_verify([e["text"] for e in emails]) if emails else []
    except Exception as exc:  # the extraction request failed: nothing was logged, so a re-run is safe
        error = f"{type(exc).__name__}: {exc}"
        return {"records": [], "errors": [{"id": e.get("id"), "error": error} for e in emails]}
    for email, record in zip(emails, results):
        try:
            if isinstance(record, Exception):
                raise record
            record["source_id"] = email["id"]
            record.update(flag_anomalies(record))
            record["logged"] = append_row(record)  # False = duplicate (vendor, due_date), skipped
            records.append(record)
        except Exception as exc:  # report and continue; nothing irreversible has happened
            errors.append({"id": email.get("id"), "error": f"{type(exc).__name__}: {exc}"})
    return {"records": records, "errors": errors}
