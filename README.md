# Bill Tracker Agent

An LLM agent that goes through an inbox, picks out the bills, checks them, and
logs them. It flags bills that are overdue or noticeably higher than usual.

It runs on a folder of sample emails out of the box. With a one-time setup it
reads a real Gmail inbox (read-only) and logs to a Google Sheet.

There is no agent framework. The loop, tool calling, guardrails and tracing are
plain Python, about 750 lines.

```
goal -> plan -> [ think -> act -> observe ] up to 8 times -> summary

tools:  fetch_emails   read the inbox
        check_bill     verify against the email, convert to INR, flag anomalies
        log_bill       append one row to the log
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # add a Gemini key from https://aistudio.google.com/apikey
python run.py
```

This processes the 19 emails in `data/sample_emails/` and writes `data/bills.csv`.
Each step is printed as it happens:

```
[   7.5s] llm       {"step": 1, "wants": ["fetch_emails"]}
[  21.5s] llm       {"step": 2, "wants": ["check_bill", "check_bill", ...]}
[  25.1s] llm       {"step": 3, "wants": ["log_bill", "log_bill", ...]}
...
LIC of India: ₹12,450.00, due 2026-09-25 (logged)
   FLAG  OVERDUE: was due 2026-09-25, 8 days ago, not paid and not on autopay
```

Run it twice and the second run logs nothing new. One run is about 5 LLM
requests; on Gemini's free tier it can pause for a minute while it waits for quota.

`pytest` runs 12 offline tests that use a scripted fake LLM, so they need no key.

## How it works

The model writes a short plan, then works in a loop: it asks for a tool, the code
runs it, and the result goes back to the model. This is the ReAct pattern, using
the model's built-in function calling.

The model only reads and decides. Anything that has to be exact is done in code:

- `check_bill` rejects an amount or vendor that is not actually written in the email.
- Currency conversion and the two flags (overdue, more than 20% above the vendor's
  last three bills) are plain arithmetic.
- A bill can only be logged after it passed the check, and the log is append-only.
- Emails that contain obvious "ignore your instructions" text are blocked before
  the model sees them.

More detail, including what each file does: [docs/how-it-works.md](docs/how-it-works.md).

## Results

66 synthetic emails with hand-written labels: 42 bills and 24 non-bills, including
confusing amounts, foreign formats, look-alike non-bills and 7 prompt injections.

| gemini-3.5-flash, one run | |
|---|---|
| Emails fully correct | 65 of 66 |
| Prompt-injection emails with a correct result | 7 of 7 (3 blocked by the filter, 4 by the model) |
| Overdue flag | precision 1.00, recall 0.93 |
| Cost per 22-email run | 5 LLM calls, about 39k tokens |

The one miss was a reminder about a bill already in the same inbox, which the model
skipped by itself. Writing the harder cases also turned up a real bug: the
grounding check could not read a decimal comma (`11,31 €`), now fixed.

`gemini-3.6-flash`, the default model, has only been run on the first 22 emails
(22 of 22) because of free-tier quota. These are synthetic emails, so read the
numbers as a regression check, not as accuracy on a real inbox.

Full write-up: [docs/evaluation.md](docs/evaluation.md). To reproduce: `python eval.py`.

## Gmail, Google Sheets and deployment

`python run.py --gmail` reads your inbox once Google sign-in is set up, and setting
`GOOGLE_SHEET_ID` sends the log to a sheet. The agent also runs as a small FastAPI
service in a container; it was deployed and tested on Google Cloud Run with the
sample inbox. Steps for all three are in [docs/setup.md](docs/setup.md).

## Limits

- The injection filter is a short list of phrases and is easy to get around. The
  real protection is that the agent has no tool that can pay, send or delete.
- The check covers amount, vendor and currency. It does not verify the due date,
  or whether a bill is marked paid or on autopay.
- One email gives at most one bill.
- Two different bills from one vendor due on the same day are treated as duplicates.
- Exchange rates are a fixed table.
- `agent/llm.py` has a second provider entry for OmniRoute. It has not been tested.

## Layout

```
agent/        llm, tools, memory, guardrails, tracing, the loop, Gmail and Sheets
eval.py       evaluation
run.py        command line
main.py       web service
tests/        offline tests
data/         sample emails, harder eval emails, labels
docs/         how it works, evaluation, setup
```
