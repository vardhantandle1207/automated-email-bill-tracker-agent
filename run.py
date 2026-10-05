"""Run the agent once from the command line.

    python run.py           # sample inbox in data/sample_emails/ (no Google account needed)
    python run.py --gmail   # your real Gmail, read-only (see README for the one-time setup)

Bills are saved to data/bills.csv, or to your Google Sheet if GOOGLE_SHEET_ID is set in .env.
"""

import os
import sys

from dotenv import load_dotenv

from agent.agent import run_agent

# Step 1: Load the API key from .env and choose the inbox.
load_dotenv(".env")
if "--gmail" in sys.argv:
    os.environ["INBOX"] = "gmail"

# Step 2: Run the agent. It prints every step while it works.
result = run_agent()

# Step 3: Show the plan, the bills and the cost of the run.
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
