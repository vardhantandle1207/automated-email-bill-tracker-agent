"""OPTIONAL: sign in to Google once. Used by gmail.py and sheets.py.

Skip this file on a first read. We ask for exactly two permissions:
    gmail.readonly   read emails; cannot send, delete, label or mark as read
    spreadsheets     read and write Google Sheets (our code only reads and appends rows)
"""

import os

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/spreadsheets"]


def google_login():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    # Step 1: Reuse the saved login (token.json) if there is one, refreshing it if it expired.
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    creds = Credentials.from_authorized_user_file(token_path, SCOPES) if os.path.exists(token_path) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if creds and creds.valid:
        return creds

    # Step 2: Otherwise open the browser once to ask for permission, and save the login.
    secrets = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if not os.path.exists(secrets):
        raise RuntimeError(f"{secrets} not found. Follow 'Real Gmail and Google Sheet' in the README, "
                           "then run `python run.py --gmail` on your own computer once.")
    creds = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES).run_local_server(port=0)
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    return creds
