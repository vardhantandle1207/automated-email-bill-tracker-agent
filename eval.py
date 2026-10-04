"""CONCEPT 8: EVALUATION (measuring the agent instead of trusting it).

We run the agent on sample emails whose correct answers we wrote by hand in
data/labels.csv, then count how often it was right.

    python eval.py                                      # Gemini
    python eval.py --provider openrouter                # OpenRouter, default free model
    python eval.py --provider openrouter --model <id>   # any model on OpenRouter
"""

import argparse
import csv
import os
import shutil
import tempfile

from dotenv import load_dotenv

from agent import llm
from agent.agent import run_agent
from agent.memory import vendor_key

load_dotenv(".env")

# Step 1: Choose which LLM to evaluate.
parser = argparse.ArgumentParser()
parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "gemini"), choices=list(llm.PROVIDERS))
parser.add_argument("--model", help="model id for that provider (default: the provider's default)")
args = parser.parse_args()
os.environ["LLM_PROVIDER"] = args.provider
if args.model:
    os.environ[llm.PROVIDERS[args.provider]["model_env"]] = args.model

# Step 2: Build a sandbox so the eval never touches your real bill log:
#         a temporary memory file that starts with 3 past months of bills, and a fixed "today".
sandbox = os.path.join(tempfile.mkdtemp(), "bills.csv")
shutil.copy("data/history_seed.csv", sandbox)
os.environ.update(MEMORY_PATH=sandbox, INBOX="mock", TODAY="2026-10-20")

# Step 3: Run the agent once over the sample inbox.
result = run_agent()
found = {bill["email_id"]: bill for bill in result["bills"]}

# Step 4: Compare every email with its label, field by field.
with open("data/labels.csv", encoding="utf-8") as f:
    labels = list(csv.DictReader(f))
fields = ["is_bill", "vendor", "amount", "currency", "due_date", "paid", "autopay"]
correct, total, mistakes = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0), []
flag_counts = {"OVERDUE": [0, 0, 0], "ABOVE TREND": [0, 0, 0]}  # [true pos, false pos, false neg]

for label in labels:
    bill, is_bill = found.get(label["file"]), label["is_bill"] == "true"
    checks = {"is_bill": (bill is not None) == is_bill}
    if is_bill:  # the other fields only exist for real bills
        bill = bill or {"vendor": "", "amount": 0, "currency": "", "due_date": None, "paid": None, "autopay": None}
        got, want = vendor_key(bill["vendor"]), vendor_key(label["vendor"])
        checks.update({
            "vendor": bool(got) and (got in want or want in got),
            "amount": abs(bill["amount"] - float(label["amount"])) < 0.01,
            "currency": bill["currency"] == label["currency"],
            "due_date": (bill["due_date"] or "") == label["due_date"],
            "paid": bill["paid"] == (label["paid"] == "true"),
            "autopay": bill["autopay"] == (label["autopay"] == "true"),
        })
    for field, ok in checks.items():
        total[field] += 1
        correct[field] += ok
        if not ok:
            got = (label["file"] in found) if field == "is_bill" else bill[field]
            mistakes.append(f"{label['file']}: {field} was {got}, expected {label[field]}")

    # Step 5: Compare the anomaly flags with the labels.
    flags = (found.get(label["file"]) or {}).get("flags", [])
    for kind, column in (("OVERDUE", "overdue"), ("ABOVE TREND", "above_trend")):
        predicted, actual = any(flag.startswith(kind) for flag in flags), label[column] == "1"
        flag_counts[kind][0] += predicted and actual
        flag_counts[kind][1] += predicted and not actual
        flag_counts[kind][2] += actual and not predicted

# Step 6: Print the report.
model = os.getenv(llm.PROVIDERS[args.provider]["model_env"], llm.PROVIDERS[args.provider]["default_model"])
print(f"\n===== EVALUATION: {args.provider} / {model}, {len(labels)} emails =====")
print("\nExtraction accuracy")
for field in fields:
    print(f"  {field:<9} {correct[field]:>2}/{total[field]:<2} ({correct[field] / total[field]:.0%})")
print("\nAnomaly flags")
for kind, (tp, fp, fn) in flag_counts.items():
    print(f"  {kind:<12} precision {tp / (tp + fp or 1):.2f}  recall {tp / (tp + fn or 1):.2f}  "
          f"(correct {tp}, wrong {fp}, missed {fn})")
print("\nMistakes")
print("\n".join(f"  {m}" for m in mistakes) or "  none")
print(f"\nCost: {result['llm_calls']} LLM calls, {result['tool_calls']} tool calls, "
      f"{result['tokens']} tokens, {result['seconds']} seconds")
