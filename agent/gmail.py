"""OPTIONAL: read a real Gmail inbox instead of the sample emails.

Skip this file on a first read. It is only used when INBOX=gmail.
Gmail is opened read-only, so this code cannot send, delete, label or mark
anything as read.
"""

import base64
import html
import os
import re

from .google_login import google_login

QUERY = 'newer_than:30d {invoice bill receipt "amount due" "payment due" subscription}'


def _text(message: dict) -> str:
    """Turn one Gmail message into 'From / Subject / body' plain text."""
    # Step 1: Collect the plain-text and HTML parts of the email.
    headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}
    parts, plain, web = [message["payload"]], [], []
    while parts:
        part = parts.pop(0)
        parts.extend(part.get("parts", []))
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") in ("text/plain", "text/html"):
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            (plain if part["mimeType"] == "text/plain" else web).append(decoded)

    # Step 2: Prefer plain text. If there is none, strip the HTML down to its words.
    body = "\n".join(plain)
    if not body.strip():
        body = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(web))  # drop code and styling
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))                  # drop tags, decode &amp; etc.
    body = re.sub(r"[ \t\xa0]+", " ", body)       # squeeze runs of spaces
    body = re.sub(r"\n\s*\n+", "\n", body)        # squeeze blank lines
    return f"From: {headers.get('from', '')}\nSubject: {headers.get('subject', '')}\n\n{body.strip()}"


def read_gmail() -> list[dict]:
    from googleapiclient.discovery import build

    # Step 3: Search the last 30 days for bill-like emails and download up to 25 of them.
    gmail = build("gmail", "v1", credentials=google_login(), cache_discovery=False).users().messages()
    found = gmail.list(userId="me", q=os.getenv("GMAIL_QUERY", QUERY), maxResults=25).execute()
    return [{"email_id": m["id"], "text": _text(gmail.get(userId="me", id=m["id"], format="full").execute())}
            for m in found.get("messages", [])]
