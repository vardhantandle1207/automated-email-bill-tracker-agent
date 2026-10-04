"""CONCEPT 9: DEPLOYMENT (the agent as a web service).

The Dockerfile starts this file. A scheduler, or you with curl, calls POST /run
to make the agent process the inbox once.

    uvicorn main:app --port 8080
    curl -X POST localhost:8080/run
"""

from dotenv import load_dotenv
from fastapi import FastAPI

from agent.agent import run_agent

load_dotenv(".env")
app = FastAPI(title="Bill Tracker Agent")


# Step 1: A cheap endpoint so the hosting platform can check the service is alive.
@app.get("/health")
def health() -> dict:
    return {"ok": True}


# Step 2: The one real endpoint: run the agent once and return what it did.
#         There is deliberately no endpoint that pays, deletes or edits anything.
@app.post("/run")
def run() -> dict:
    return run_agent()
