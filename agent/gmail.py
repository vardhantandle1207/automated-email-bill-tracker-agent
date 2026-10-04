"""OPTIONAL: read a real Gmail inbox instead of the sample emails.

Skip this file on a first read. It is only used when INBOX=gmail.
The only permission asked for is gmail.readonly, so this code cannot send,
delete, label or mark anything as read.
"""

import base64
import os
import re

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
QUERY = 'newer_than:30d {invoice bill receipt "amount due" "payment due" subscription}'


def _login():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    # Step 1: Reuse the saved login (token.json) if there is one, refreshing it if expired.
    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    creds = Credentials.from_authorized_user_file(token_path, SCOPES) if os.path.exists(token_path) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    # Step 2: Otherwise open the browser once to ask for read-only access, and save the login.
    if not creds or not creds.valid:
        secrets = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
        creds = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES).run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def _text(message: dict) -> str:
    """Turn one Gmail message into 'From / Subject / body' plain text."""
    headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
    parts, plain, html = [message["payload"]], [], []
    while parts:
        part = parts.pop(0)
        parts.extend(part.get("parts", []))
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") in ("text/plain", "text/html"):
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            (plain if part["mimeType"] == "text/plain" else html).append(decoded)
    body = "\n".join(plain) or re.sub(r"<[^>]+>", " ", "\n".join(html))  # no plain text: strip HTML tags
    return f"From: {headers.get('from', '')}\nSubject: {headers.get('subject', '')}\n\n{body.strip()}"


def read_gmail() -> list[dict]:
    from googleapiclient.discovery import build

    # Step 3: Search the last 30 days for bill-like emails and download up to 25 of them.
    gmail = build("gmail", "v1", credentials=_login(), cache_discovery=False).users().messages()
    found = gmail.list(userId="me", q=os.getenv("GMAIL_QUERY", QUERY), maxResults=25).execute()
    return [{"email_id": m["id"], "text": _text(gmail.get(userId="me", id=m["id"], format="full").execute())}
            for m in found.get("messages", [])]
