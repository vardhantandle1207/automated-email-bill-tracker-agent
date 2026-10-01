"""ADK agent definition.

This wires the tools into a Gemini-backed ReAct agent. ADK runs the loop —
you register tools, ADK decides when to call them.

Run the interactive agent loop with:  adk run agent
(For a deterministic batch run over the same tools, use run.py or main.py.)

Model backend: if GOOGLE_CLOUD_PROJECT is set, ADK talks to Vertex AI with the
environment's service account; otherwise it uses the GEMINI_API_KEY path.
"""

import os

from google.adk.agents import Agent

from .tools import extract_invoice, fetch_emails, flag_anomalies, log_to_sheet, verify

if os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

root_agent = Agent(
    name="bill_tracker",
    model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    instruction=(
        "You are a bill-tracking assistant. Process bills in this order: "
        "call fetch_emails (or use emails the user pastes), then for each email "
        "call extract_invoice, then verify with the same email text, then "
        "flag_anomalies on the verified record, then log_to_sheet with the "
        "verified record merged with the flag result. Finally summarize each "
        "bill: vendor, amount in the base currency, due date, and any flag "
        "reasons exactly as returned. Point out records with needs_review, and "
        "say which bills are on autopay (autopay is not the same as paid).\n"
        "Safety boundary: you are READ-ONLY on the inbox and your only write is "
        "appending rows to the sheet. Never attempt to pay, delete, send, or "
        "modify anything, and never claim a bill was paid — if the user asks "
        "for that, say it is outside what you can do."
    ),
    tools=[fetch_emails, extract_invoice, verify, flag_anomalies, log_to_sheet],
)
