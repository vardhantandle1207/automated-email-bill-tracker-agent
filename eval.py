"""CONCEPT 8: EVALUATION (measuring the agent instead of trusting it).

We run the agent on sample emails whose correct answers we wrote by hand in
data/labels.csv, then count how often it was right. Many of the emails are
deliberately hard: several amounts in one email, foreign number and date
formats, emails that look like bills but are not, and prompt injections.

    python eval.py                                      # Gemini
    python eval.py --model gemini-3.5-flash             # another Gemini model
    python eval.py --provider omniroute                 # OmniRoute, which picks the model ("auto")
    python eval.py --provider omniroute --model <id>    # a specific model behind OmniRoute

Each finished batch is saved in logs/eval_cache.json. If the provider runs out of
quota part-way, run the same command again later and it continues where it stopped.
Delete that file to start from scratch.
"""

import argparse
import csv
import glob
import json
import os
import shutil
import tempfile

from dotenv import load_dotenv

from agent import llm, memory
from agent.agent import run_agent
from agent.memory import vendor_key

load_dotenv(".env")
BATCH = 22  # emails per agent run. A real Gmail run reads at most 25, so we test at that size.

# Step 1: Choose which LLM to evaluate.
parser = argparse.ArgumentParser()
parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "gemini"), choices=list(llm.PROVIDERS))
parser.add_argument("--model", help="model id for that provider (default: the provider's default)")
args = parser.parse_args()
os.environ["LLM_PROVIDER"] = args.provider
if args.model:
    os.environ[llm.PROVIDERS[args.provider]["model_env"]] = args.model
model = os.getenv(llm.PROVIDERS[args.provider]["model_env"], llm.PROVIDERS[args.provider]["default_model"])

# Step 2: Build a sandbox so the eval never touches your real bill log:
#         a temporary memory file that starts with 3 past months of bills, and a fixed "today".
sandbox = tempfile.mkdtemp()
shutil.copy("data/history_seed.csv", os.path.join(sandbox, "bills.csv"))
os.environ.update(MEMORY_PATH=os.path.join(sandbox, "bills.csv"), GOOGLE_SHEET_ID="", INBOX="mock", TODAY="2026-10-20")

# Step 3: Split the emails into inbox-sized batches and run the agent once per batch.
#         The eval set is the 19 demo emails plus the harder ones in data/eval_emails/.
files = sorted(glob.glob("data/sample_emails/*.txt") + glob.glob("data/eval_emails/*.txt"), key=os.path.basename)
cache_path = "logs/eval_cache.json"
cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
found, runs, tested = {}, [], set()
for start in range(0, len(files), BATCH):
    names = [os.path.basename(path) for path in files[start:start + BATCH]]
    key = f"{args.provider}/{model}: {' '.join(names)}"
    if key in cache:  # finished in an earlier run: put its bills back into the sandbox memory
        for bill in cache[key]["bills"]:
            memory.remember(bill)
    else:
        inbox = os.path.join(sandbox, f"inbox{start}")
        os.makedirs(inbox)
        for path in files[start:start + BATCH]:
            shutil.copy(path, inbox)
        os.environ["SAMPLE_INBOX"] = os.path.join(inbox, "*.txt")
        try:
            result = run_agent()
        except RuntimeError as error:  # the LLM is unavailable or out of quota: keep what we have
            print(f"\nStopped early, run again later to continue. {str(error)[:120]}")
            break
        cache[key] = {k: result[k] for k in ("bills", "llm_calls", "tool_calls", "tokens", "seconds")}
        os.makedirs("logs", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    runs.append(cache[key])
    tested.update(names)
    found.update({bill["email_id"]: bill for bill in cache[key]["bills"]})
if not runs:
    raise SystemExit("No batch finished, so there is nothing to score yet.")

# Step 4: Compare every email with its label, field by field.
with open("data/labels.csv", encoding="utf-8") as f:
    labels = [label for label in csv.DictReader(f) if label["file"] in tested]
fields = ["is_bill", "vendor", "amount", "currency", "due_date", "paid", "autopay"]
correct, total, mistakes = dict.fromkeys(fields, 0), dict.fromkeys(fields, 0), []
flag_counts = {"OVERDUE": [0, 0, 0], "ABOVE TREND": [0, 0, 0]}  # [true pos, false pos, false neg]
perfect = {"all": 0, "injection": 0}  # emails where every field AND both flags were right

for label in labels:
    bill, is_bill = found.get(label["file"]), label["is_bill"] == "true"
    checks = {"is_bill": (bill is not None) == is_bill}
    if is_bill:  # the other fields only exist for real bills
        bill = bill or {"vendor": "", "amount": 0, "currency": "", "due_date": None, "paid": None, "autopay": None}
        got = vendor_key(bill["vendor"])
        names = [vendor_key(name) for name in label["vendor"].split("|")]  # a vendor may have several accepted names
        checks.update({
            "vendor": bool(got) and any(got in name or name in got for name in names),
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
    flags_ok = True
    for kind, column in (("OVERDUE", "overdue"), ("ABOVE TREND", "above_trend")):
        predicted, actual = any(flag.startswith(kind) for flag in flags), label[column] == "1"
        flag_counts[kind][0] += predicted and actual
        flag_counts[kind][1] += predicted and not actual
        flag_counts[kind][2] += actual and not predicted
        flags_ok = flags_ok and predicted == actual
        if predicted != actual:
            mistakes.append(f"{label['file']}: {kind} flag was {predicted}, expected {actual}")
    if all(checks.values()) and flags_ok:
        perfect["all"] += 1
        perfect["injection"] += "injection" in label["file"]

# Step 6: Print the report.
injections = sum("injection" in label["file"] for label in labels)
print(f"\n===== EVALUATION: {args.provider} / {model}, {len(labels)} of {len(files)} emails, {len(runs)} runs =====")
print(f"\nEmails handled fully correctly: {perfect['all']}/{len(labels)} ({perfect['all'] / len(labels):.0%})")
print(f"Prompt-injection emails handled correctly: {perfect['injection']}/{injections}")
print("\nExtraction accuracy")
for field in fields:
    print(f"  {field:<9} {correct[field]:>2}/{total[field]:<2} ({correct[field] / total[field]:.0%})")
print("\nAnomaly flags")
for kind, (tp, fp, fn) in flag_counts.items():
    print(f"  {kind:<12} precision {tp / (tp + fp or 1):.2f}  recall {tp / (tp + fn or 1):.2f}  "
          f"(correct {tp}, wrong {fp}, missed {fn})")
print("\nMistakes")
print("\n".join(f"  {m}" for m in mistakes) or "  none")
print("\nCost per run (average)")
for key in ("llm_calls", "tool_calls", "tokens", "seconds"):
    print(f"  {key:<10} {sum(run[key] for run in runs) / len(runs):,.0f}")
