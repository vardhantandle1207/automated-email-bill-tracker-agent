"""FastAPI entrypoint (Cloud Run).

POST /run  processes a batch end to end and returns the records with their flags:
    {}                              -> fetch from Gmail (read-only)
    {"mock": true}                  -> use data/sample_emails/
    {"emails": [{"id", "text"}]}    -> process the given emails

There is deliberately no endpoint that pays, deletes, or edits anything.
Run locally:  uvicorn main:app --reload --port 8080
"""

from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402  (import after env is loaded)
from pydantic import BaseModel  # noqa: E402

from agent.pipeline import run_batch  # noqa: E402
from agent.tools import load_sample_emails  # noqa: E402

app = FastAPI(title="Bill & Subscription Tracker Agent")


class Email(BaseModel):
    id: str
    text: str


class RunRequest(BaseModel):
    emails: Optional[list[Email]] = None
    mock: bool = False


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/run")
def run(req: Optional[RunRequest] = None) -> dict:
    req = req or RunRequest()
    if req.emails is not None:
        emails = [e.model_dump() for e in req.emails]
    else:
        emails = load_sample_emails() if req.mock else None  # None -> fetch_emails()
    result = run_batch(emails)
    return {"processed": len(result["records"]), **result}
