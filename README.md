# Autonomous Bill & Subscription Tracker Agent

A ReAct agent (Gemini + Google ADK) that reads invoice emails, extracts the
vendor / amount / currency / due date / autopay, checks the extraction against the email,
normalizes to a base currency, flags overdue or above-trend bills with a
checkable explanation, and logs everything to a Google Sheet.

Emails that aren't bills (promotions, newsletters, shipping updates, card
alerts, price-change notices) come back with `is_bill: false` and are listed under
`skipped`. They never reach the sheet or the history.

**Safety boundary by design:** the agent has read-only inbox access
(`gmail.readonly`), and its only writes are *appends*: to a sheet and to its own
history store. Paying, deleting, and any irreversible action sit *outside* its
toolset, and there is no auto-pay and no chatbot UI. The Google Sheet is the
interface.

```
fetch_emails -> extract_invoice -> verify -> flag_anomalies -> log_to_sheet
   Gmail (RO)      Gemini           regex+retry   Firestore       Sheet (append)
```

See [docs/architecture.md](docs/architecture.md) for the diagram and design.

## Tools

| Tool | What it does |
|---|---|
| `fetch_emails()` | Gmail search (read-only scope) → `[{id, text}]`. `MOCK_INBOX=1` / `--mock` reads `data/sample_emails/` |
| `extract_invoice(email_text)` | Gemini structured output into `InvoiceFields` (+ `amount_base` in INR). Batch runs use `extract_and_verify`: one request for all emails |
| `verify(record, email_text)` | Checks amount / currency / vendor / date actually appear in the email; re-extracts once if not. Adds `corrected`, `issues`, `needs_review` |
| `flag_anomalies(record)` | Overdue (past due, not paid, not on autopay) and above-trend (over N-month rolling avg by X%), with reasons that quote their numbers |
| `log_to_sheet(record)` | Appends a row (logs `amount_base`), deduped on `(vendor, due_date)`; CSV fallback. Returns `{"logged": bool}` |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # then paste your key from https://aistudio.google.com/apikey
```

Everything below the key is optional. With nothing configured, the agent runs
fully locally: sample inbox → `data/bills.csv` + `data/history.json`.

### Gmail OAuth (read-only)

1. In [Google Cloud Console](https://console.cloud.google.com/), pick or create a project and
   enable the **Gmail API**.
2. **OAuth consent screen**: set user type External, publishing status Testing,
   and add your own Gmail address as a test user. Add the scope
   `https://www.googleapis.com/auth/gmail.readonly` and nothing else.
3. **Credentials → Create credentials → OAuth client ID → Desktop app**.
   Download the JSON as `credentials.json` in the repo root. It is gitignored.
4. Run `python run.py` once. A browser opens for consent, and afterwards
   `token.json` is written next to it (also gitignored).

The app only ever requests `gmail.readonly`, so the token cannot send, delete,
label, or mark mail as read. Note that while the consent screen is in *Testing*
status, Google expires refresh tokens after 7 days, so re-run step 4 when that
happens (or publish the app for longer-lived tokens).

### Google Sheet (optional; the default is CSV)

1. Enable the **Google Sheets API**. Create a service account and download its
   key as `service-account.json` (gitignored).
2. Create a Sheet and share it with the service account's email as **Editor**.
3. In `.env`, set `GOOGLE_SHEET_ID=<id from the sheet URL>` and
   `GOOGLE_APPLICATION_CREDENTIALS=service-account.json`.

The header row is written on first append. Values are written `RAW`, so text from
an email can never execute as a formula.

### Firestore history (optional; the default is local JSON)

Set `HISTORY_BACKEND=firestore` and `GOOGLE_CLOUD_PROJECT`, and make sure the
credentials can access Firestore (Native mode). Documents live in
`vendor_history/{vendor_key}`.

To try the anomaly rules locally with some past months:
`cp data/history_seed.json data/history.json`.

### Exchange rates (optional; the default is a static table)

`FX_SOURCE=live` converts with the day's ECB reference rates from the free
[Frankfurter](https://frankfurter.dev) API (no key). Rates are fetched once per
process per day. If the fetch fails, or a currency is missing, the static table
in `agent/currency.py` is used for that day. Live rates are recommended in prod.
The default stays static so runs are reproducible, and `eval.py` always uses
static rates because the labels and `history_seed.json` were made with them.

## Run

```bash
python run.py --mock          # full pipeline over data/sample_emails/, no Gmail needed
python run.py                 # full pipeline over your Gmail (read-only)
adk run agent                 # ADK ReAct loop over the same five tools
uvicorn main:app --port 8080  # HTTP: curl -X POST localhost:8080/run -d '{"mock": true}' -H 'Content-Type: application/json'
python run_day1.py            # Day 1: extract_invoice only
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs fully offline: the regex baseline stands in for Gemini, local
state goes to a temp dir, and the FX API is stubbed. It covers parsing, verify's
retry, the anomaly rules, append-only storage and dedupe, FX fallback, the batch
pipeline, and `POST /run`.

`POST /run` accepts `{}` (fetch from Gmail), `{"mock": true}`, or
`{"emails": [{"id": "...", "text": "..."}]}`. It returns every record with its
flags, reasons, `corrected`, `needs_review`, and `logged` (false means a duplicate
that was skipped).

## Eval

```bash
python eval.py                    # Gemini extraction (needs GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT)
python eval.py --extractor regex  # offline no-LLM baseline
python eval.py --no-cache         # force fresh Gemini calls
```

**Gemini cost per run: at most 2 requests**, however many emails there are.
All emails go out in one request, and any that fail `verify` are re-extracted
together in one more. `GEMINI_BATCH_SIZE` (default 25, the Gmail fetch cap) splits
very large batches. This applies to `run.py`, `POST /run`, and `eval.py`.
`adk run agent` is different: there the model calls the tools one email at a
time, so it costs a request per tool call.

Gemini outputs are cached per email in `data/.cache/extractions.jsonl`
(gitignored), and only uncached emails are sent. The key covers the model, the
email, the verify hint, and the extraction prompt/schema. Editing the prompt or
switching `GEMINI_MODEL` re-extracts. On the free tier, consider
`GEMINI_RETRY_ATTEMPTS=2` so retries of an overloaded (503) request don't use up
the daily quota.

The eval set is 18 synthetic emails in `data/sample_emails/`: 13 bills and 5
non-bills. They cover the hard cases:
- several amounts in one email (subtotal/GST/total, total vs. minimum due, a usage breakdown)
- INR/USD/EUR/GBP
- `DD/MM` vs `MM/DD` dates and dates like `18-Oct-2026`
- paid receipts, autopay, and undated invoices
- promotions, a price-change notice, a shipping update, a card transaction alert, and a newsletter

The eval runs extract → verify → anomaly detection over all of them and reports:

- **(a) per-field extraction accuracy**, against `data/ground_truth.csv`
- **(b) accuracy before vs. after `verify`**, plus how many records were corrected or left `needs_review`
- **(c) anomaly precision / recall**, against `data/anomaly_labels.csv`

The eval has no side effects: it writes nothing to the sheet or history.
Anomalies are judged against `data/history_seed.json` at each label row's
`as_of` date.

Matching rules: amount within 0.01; vendor equal or contained after lowercasing
and stripping non-alphanumerics; currency, due_date, paid, autopay and is_bill
exact. Non-bills are scored on `is_bill` only. For receipts, `due_date` is the
next billing date written in the email.

To add a labelled email:
1. Drop `name.txt` (with `From:`/`Subject:` headers) into `data/sample_emails/`.
2. Add a row to `ground_truth.csv` (`file,vendor,amount,currency,due_date,paid,autopay,is_bill`).
   For a non-bill, leave everything but `is_bill` (`false`) empty.
3. Add a row to `anomaly_labels.csv` (`file,as_of,overdue,above_trend,notes`).
4. If you want above-trend cases, add that vendor's past months to `history_seed.json`.

## Deploy to Cloud Run

When `GOOGLE_CLOUD_PROJECT` is set, both the extractor and the ADK agent switch
from the API key to **Vertex AI**, authenticating as the Cloud Run service
account. No API key is deployed.

```bash
PROJECT=your-project-id REGION=asia-south1 SA=bill-tracker@$PROJECT.iam.gserviceaccount.com
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com \
  firestore.googleapis.com sheets.googleapis.com gmail.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com
gcloud firestore databases create --location=$REGION

gcloud iam service-accounts create bill-tracker
for role in roles/aiplatform.user roles/datastore.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=$role
done
# Share your Sheet with $SA (Editor).

# Gmail token created locally (see OAuth above) -> Secret Manager
gcloud secrets create gmail-token --data-file=token.json

gcloud run deploy bill-tracker --source . --region $REGION \
  --service-account $SA --no-allow-unauthenticated \
  --set-env-vars GEMINI_MODEL=gemini-3.8-flash,FX_SOURCE=live,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=us-central1,HISTORY_BACKEND=firestore,GOOGLE_SHEET_ID=<sheet-id>,GMAIL_TOKEN_PATH=/secrets/gmail/token.json \
  --set-secrets /secrets/gmail/token.json=gmail-token:latest

# Run it daily at 08:00 IST
gcloud run services add-iam-policy-binding bill-tracker --region $REGION \
  --member=serviceAccount:$SA --role=roles/run.invoker
gcloud scheduler jobs create http bill-tracker-daily --location $REGION \
  --schedule "0 8 * * *" --time-zone Asia/Kolkata --http-method POST \
  --uri "$(gcloud run services describe bill-tracker --region $REGION --format 'value(status.url)')/run" \
  --headers Content-Type=application/json --message-body '{}' \
  --oidc-service-account-email $SA
```

Notes:
- The service is private (`--no-allow-unauthenticated`); only Scheduler's OIDC token can call it.
- Local JSON/CSV on Cloud Run is ephemeral, so set `HISTORY_BACKEND=firestore` and `GOOGLE_SHEET_ID` in prod.
- If the Gmail token is missing or invalid, the service fails fast. It never tries a browser consent flow on Cloud Run.

## Structure

```
bill-tracker-agent/
├── agent/
│   ├── schemas.py     # typed InvoiceFields (Gemini response schema)
│   ├── currency.py    # normalization to base currency (static or daily live rates)
│   ├── parsing.py     # regex evidence for verify + no-LLM baseline extractor
│   ├── storage.py     # sheet/CSV and Firestore/JSON backends (append-only)
│   ├── tools.py       # the five ADK tools
│   ├── pipeline.py    # deterministic batch: fetch -> extract -> verify -> flag -> log
│   ├── agent.py       # ADK agent: registers tools, runs the ReAct loop
│   └── __init__.py
├── data/
│   ├── sample_emails/       # labelled eval emails
│   ├── ground_truth.csv     # extraction labels
│   ├── anomaly_labels.csv   # anomaly labels (with as_of date)
│   └── history_seed.json    # synthetic past bills for above-trend eval
├── docs/architecture.md
├── tests/             # offline pytest suite
├── eval.py            # extraction + verify + anomaly metrics
├── run.py             # CLI batch run (--mock)
├── main.py            # FastAPI entrypoint (Cloud Run)
├── run_day1.py        # Day 1 direct tool test
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```
