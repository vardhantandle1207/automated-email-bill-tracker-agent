"""CONCEPT 5: OBSERVABILITY (being able to see what the agent did, and what it cost).

Every LLM call and every tool call becomes one "event". Each event is printed
to the screen and saved as one line of JSON in logs/trace.jsonl, so after a run
you can replay exactly what happened, step by step.
"""

import json
import os
import time
import uuid


class Tracer:
    def __init__(self):
        # Step 1: Give this run an id and start the clock and the counters.
        self.run_id = uuid.uuid4().hex[:8]
        self.started = time.time()
        self.totals = {"llm_calls": 0, "tool_calls": 0, "tokens": 0}

    def log(self, event: str, **details) -> None:
        """Record one event: 'llm', 'tool', 'guardrail' or 'done'."""
        # Step 2: Update the counters.
        if event == "llm":
            self.totals["llm_calls"] += 1
            self.totals["tokens"] += details.get("tokens", 0)
        if event == "tool":
            self.totals["tool_calls"] += 1

        # Step 3: Print a short line so you can watch the agent work.
        elapsed = round(time.time() - self.started, 1)
        print(f"[{elapsed:>6}s] {event:<9} {json.dumps(details, ensure_ascii=False)[:160]}")

        # Step 4: Save the full event to the trace file.
        path = os.getenv("TRACE_PATH", "logs/trace.jsonl")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            record = {"run_id": self.run_id, "elapsed": elapsed, "event": event, **details}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def summary(self) -> dict:
        """The cost of the whole run."""
        return {"run_id": self.run_id, **self.totals, "seconds": round(time.time() - self.started, 1)}
