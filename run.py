"""Run the agent once from the command line.

    python run.py           # sample inbox in data/sample_emails/ (no Google account needed)
    python run.py --gmail   # your real Gmail, read-only (one-time setup: docs/setup.md)

Bills are saved to data/bills.csv, or to your Google Sheet if GOOGLE_SHEET_ID is set in .env.
"""

import os
import sys

from dotenv import load_dotenv

from agent.agent import run_agent

load_dotenv(".env")
if "--gmail" in sys.argv:
    os.environ["INBOX"] = "gmail"

result = run_agent()

print("\n===== PLAN =====\n" + result["plan"])
print("\n===== BILLS =====")
for bill in result["bills"]:
    status = "logged" if bill["logged"] else "already logged"
    print(f"{bill['vendor']}: ₹{bill['amount_inr']:,.2f}, due {bill['due_date'] or 'no date'} ({status})")
    for flag in bill["flags"]:
        print(f"   FLAG  {flag}")
print(f"\nSkipped (not bills): {', '.join(result['skipped']) or 'none'}")
print("\n===== AGENT'S SUMMARY =====\n" + result["answer"])
print(f"\n===== RUN {result['run_id']} =====")
print(f"{result['llm_calls']} LLM calls, {result['tool_calls']} tool calls, "
      f"{result['tokens']} tokens, {result['seconds']} seconds")
where = "your Google Sheet" if os.getenv("GOOGLE_SHEET_ID") else "data/bills.csv"
print(f"Bills are saved in {where}. The full trace is in logs/trace.jsonl.")
