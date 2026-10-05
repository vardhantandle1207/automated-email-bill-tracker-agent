"""Web service wrapper around the agent. The Dockerfile starts this.

    uvicorn main:app --port 8080
    curl -X POST localhost:8080/run
"""

from dotenv import load_dotenv
from fastapi import FastAPI

from agent.agent import run_agent

load_dotenv(".env")
app = FastAPI(title="Bill Tracker Agent")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


# runs the agent once over the inbox and returns what it did
@app.post("/run")
def run() -> dict:
    return run_agent()
