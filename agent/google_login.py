"""One Google sign-in shared by gmail.py and sheets.py.

Scopes requested:
    gmail.readonly   read mail only
    spreadsheets     read and write sheets (this code only reads and appends)
"""

import os

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/spreadsheets"]


def google_login():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    creds = Credentials.from_authorized_user_file(token_path, SCOPES) if os.path.exists(token_path) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if creds and creds.valid:
        return creds

    # first run: open the browser for consent, then save the login to token.json
    secrets = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if not os.path.exists(secrets):
        raise RuntimeError(f"{secrets} not found. Follow docs/setup.md, "
                           "then run `python run.py --gmail` on your own computer once.")
    creds = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES).run_local_server(port=0)
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    return creds
