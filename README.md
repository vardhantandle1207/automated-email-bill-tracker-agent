# Bill Tracker Agent

A small AI agent that reads your emails, finds the bills, checks them, flags the
ones that are overdue or unusually high, and saves them to a log.

It is written in plain Python with **no agent framework**, so every agentic
concept is visible in about 700 lines of code that you can read in one sitting.

```
            ┌──────────────── the agent loop ────────────────┐
 goal ─► PLAN ─► THINK (LLM) ─► ACT (run tools) ─► OBSERVE ──┘─► summary
                                  │
                 fetch_emails ────┤  read the inbox (read-only)
                 check_bill ──────┤  verify against the email, convert to ₹, flag anomalies
                 log_bill ────────┘  append one row to data/bills.csv
```

## The 9 concepts, and where each one lives

Read the files in this order. Every file is split into `Step 1`, `Step 2`, ... comments.

| # | Concept | File | What it means here |
|---|---|---|---|
| 1 | LLM | [agent/llm.py](agent/llm.py) | One function, `chat()`, that sends the conversation to Gemini or OpenRouter and returns one reply |
| 2 | Tools and tool calling | [agent/tools.py](agent/tools.py) | Three Python functions the LLM may ask us to run, plus their descriptions |
| 3 | Short-term and long-term memory | [agent/memory.py](agent/memory.py) | Short-term: the conversation and emails of this run. Long-term: `data/bills.csv`, kept between runs |
| 4 | Guardrails | [agent/guardrails.py](agent/guardrails.py) | Block prompt injection, reject values that are not in the email, limit the loop to 8 steps |
| 5 | Observability | [agent/tracing.py](agent/tracing.py) | Every LLM call and tool call is printed and saved to `logs/trace.jsonl` with tokens and timing |
| 6 | Planning | [agent/agent.py](agent/agent.py) | The LLM writes a numbered plan before it is given any tool |
| 7 | Agent loop | [agent/agent.py](agent/agent.py) | Think, act, observe, and repeat until the LLM says it is done |
| 8 | Evaluation | [eval.py](eval.py) | Runs the agent on 19 labelled emails and reports accuracy, precision, recall and cost |
| 9 | Deployment | [main.py](main.py), [Dockerfile](Dockerfile) | The agent as a web service with one endpoint, `POST /run` |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then paste a free key from https://aistudio.google.com/apikey
python run.py               # runs on the 19 sample emails in data/sample_emails/
```

You will see each step as it happens, then the plan, the bills and the cost:

```
[   4.4s] llm       {"step": 0, ... "wants": "Here is my plan ..."}           <- PLAN
[   7.5s] llm       {"step": 1, ... "wants": ["fetch_emails"]}                <- THINK
[   7.5s] tool      {"step": 1, "name": "fetch_emails", ...}                  <- ACT
[  21.5s] llm       {"step": 2, ... "wants": ["check_bill", "check_bill", ...]}
[  25.1s] llm       {"step": 3, ... "wants": ["log_bill", "log_bill", ...]}
...
LIC of India: ₹12,450.00, due 2026-09-25 (logged)
   FLAG  OVERDUE: was due 2026-09-25, 8 days ago, not paid and not on autopay
...
5 LLM calls, 27 tool calls, 30818 tokens
```

Open `data/bills.csv` to see the saved bills. Run it a second time and every bill
says "already logged": that is long-term memory at work.

To see "above trend" flags too, start with three months of past bills:
`cp data/history_seed.csv data/bills.csv`, then run again.

One run costs about 5 LLM requests. The free Gemini tier allows only a few
requests per minute, so a run can pause for 20 to 60 seconds while it waits.

## How one run works

1. **Plan.** The agent gets the goal "Find the bills in my inbox and log them" and
   writes a numbered plan. No tools are offered yet, so it can only plan.
2. **Fetch.** It calls `fetch_emails`. The input guardrail blocks any email that
   tries to give the agent orders, and cuts very long emails.
3. **Check.** It decides which emails are bills and calls `check_bill` for each
   one, many in a single turn. The tool rejects any amount, vendor or currency
   that is not really in the email, and the agent must fix it and try again. For
   bills that pass, the tool converts the amount to rupees, looks up the vendor's
   past bills in long-term memory, and flags the bill if it is:
   - **overdue**: past its due date, not paid, and not on autopay
   - **above trend**: more than 20% above the average of that vendor's last 3 bills
4. **Log.** It calls `log_bill`, which appends the checked bill to `data/bills.csv`.
   A bill that did not pass the check cannot be logged.
5. **Summarise.** With no tools left to call, it writes a summary and the loop ends.

## Evaluation

```bash
python eval.py                                      # Gemini
python eval.py --provider openrouter                # OpenRouter (needs OPENROUTER_API_KEY in .env)
python eval.py --provider openrouter --model <id>   # compare any model on OpenRouter
```

The eval set is 19 synthetic emails: 13 bills and 6 non-bills (a promotion, a
newsletter, a shipping update, a card alert, a price-change notice and a fake
invoice containing a prompt injection). The correct answers are in
[data/labels.csv](data/labels.csv). The eval runs in a sandbox, so it never
touches your real `data/bills.csv`.

Result with `gemini-3.6-flash`:

| Metric | Score |
|---|---|
| Is it a bill? | 19/19 |
| Vendor, amount, currency, due date, paid, autopay | 13/13 each |
| Overdue flag | precision 1.00, recall 1.00 |
| Above-trend flag | precision 1.00, recall 1.00 |
| Cost | 6 LLM calls, 27 tool calls, about 36,500 tokens |

The emails are synthetic and few, so treat this as a regression check, not as
proof of accuracy on a real inbox.

## Tests

```bash
pytest
```

Nine offline tests, no API key needed. A scripted fake LLM stands in for the real
one, so the tests can check things like "a wrong amount is rejected and cannot be
logged" and "the loop stops at the step limit".

## Your real Gmail (optional)

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Gmail API**.
2. On the OAuth consent screen, add yourself as a test user and add only the
   scope `gmail.readonly`.
3. Create an OAuth client ID of type **Desktop app** and save the JSON as
   `credentials.json` in this folder.
4. Run `python run.py --gmail`. A browser opens once to ask for read-only access.

## Deployment

The agent runs as a small web service. Locally:

```bash
uvicorn main:app --port 8080
curl -X POST localhost:8080/run
```

In a container:

```bash
docker build -t bill-tracker .
docker run -p 8080:8080 -e GEMINI_API_KEY=your_key bill-tracker
```

On Google Cloud Run, with the key stored in Secret Manager:

```bash
printf 'your_key' | gcloud secrets create gemini-key --data-file=-
gcloud run deploy bill-tracker --source . --region asia-south1 \
  --set-secrets GEMINI_API_KEY=gemini-key:latest --no-allow-unauthenticated
```

A container's disk is temporary. To keep long-term memory between restarts,
mount a storage volume and point `MEMORY_PATH` at it.

## Safety

The agent can read emails and append rows to a log. That is all. This is
enforced by what exists, not by the prompt:

- There is no tool to pay, delete, send or edit, so no prompt can make it do so.
- Gmail access uses the `gmail.readonly` permission only.
- The log is append-only, and only a bill that passed `check_bill` can be saved.

## Known limits

- The injection guardrail is a short list of phrases. It catches obvious attacks only.
- The output guardrail checks the amount, vendor and currency against the email.
  It checks that the due date is a valid date, but not that it matches the email.
- Exchange rates are a fixed table in `agent/tools.py`.

## Project structure

```
agent/
  llm.py          1. the LLM
  tools.py        2. tools and tool calling
  memory.py       3. short-term and long-term memory
  guardrails.py   4. guardrails
  tracing.py      5. observability
  agent.py        6. planning and 7. the agent loop
  gmail.py        optional: real Gmail inbox, read-only
eval.py           8. evaluation
main.py           9. deployment: the web service
Dockerfile        9. deployment: the container
run.py            run the agent from the command line
tests/            offline tests
data/
  sample_emails/      19 sample emails
  labels.csv          the correct answers for the eval
  history_seed.csv    3 months of past bills, used by the eval
```
