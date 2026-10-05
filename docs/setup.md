# Setup beyond the sample inbox

## Real Gmail and Google Sheet

By default the agent reads the sample emails and writes a CSV file. With a
one-time setup it reads your real Gmail (read-only) and logs to a Google Sheet.

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the
   **Gmail API** and the **Google Sheets API**.
2. Set up the OAuth consent screen (user type External) and add yourself as a test user.
3. Create an OAuth client ID of type **Desktop app** and save the downloaded
   file as `credentials.json` in this folder.
4. Create an empty Google Sheet and copy its id from the address bar
   (`docs.google.com/spreadsheets/d/<id>/edit`) into `.env` as `GOOGLE_SHEET_ID=<id>`.
5. Run `python run.py --gmail`. A browser opens once to ask for permission, and the
   login is saved in `token.json`.

The sheet gets a header row on the first run and one new row per bill after
that. Setting only `GOOGLE_SHEET_ID` (without `--gmail`) logs the sample emails
to the sheet.

Real emails are sent to the LLM provider to be read. On a free API tier the
provider may use that text to improve its products, so check its terms first.

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
  --set-secrets GEMINI_API_KEY=gemini-key:latest \
  --no-allow-unauthenticated --max-instances 1 --timeout 900
```

The service is private, so call it with your Google identity:

```bash
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" <service-url>/run
```

This project was deployed and tested on Cloud Run with exactly these commands,
using the sample inbox. A container's disk is temporary. To keep long-term memory between restarts,
mount a storage volume and point `MEMORY_PATH` at it.
