"""Gmail inbox reader, used when INBOX=gmail.

The login only carries the gmail.readonly scope, so nothing here can send,
delete, label or mark mail as read.
"""

import base64
import html
import os
import re

from .google_login import google_login

QUERY = 'newer_than:30d {invoice bill receipt "amount due" "payment due" subscription}'


def _text(message: dict) -> str:
    """Turn one Gmail message into 'From / Subject / body' plain text."""
    headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
    parts, plain, web = [message["payload"]], [], []
    while parts:
        part = parts.pop(0)
        parts.extend(part.get("parts", []))
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") in ("text/plain", "text/html"):
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            (plain if part["mimeType"] == "text/plain" else web).append(decoded)

    # many bills are HTML-only: fall back to the HTML part with its markup stripped
    body = "\n".join(plain)
    if not body.strip():
        body = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(web))
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    body = re.sub(r"[ \t\xa0]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n", body)
    return f"From: {headers.get('from', '')}\nSubject: {headers.get('subject', '')}\n\n{body.strip()}"


def read_gmail() -> list[dict]:
    from googleapiclient.discovery import build

    gmail = build("gmail", "v1", credentials=google_login(), cache_discovery=False).users().messages()
    found = gmail.list(userId="me", q=os.getenv("GMAIL_QUERY", QUERY), maxResults=25).execute()
    return [{"email_id": m["id"], "text": _text(gmail.get(userId="me", id=m["id"], format="full").execute())}
            for m in found.get("messages", [])]
