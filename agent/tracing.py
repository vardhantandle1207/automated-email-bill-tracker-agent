"""Run tracing.

Every LLM call and tool call is printed and appended as one JSON line to
logs/trace.jsonl, with the run id, step, tokens and timing.
"""

import json
import os
import time
import uuid


class Tracer:
    def __init__(self):
        self.run_id = uuid.uuid4().hex[:8]
        self.started = time.time()
        self.totals = {"llm_calls": 0, "tool_calls": 0, "tokens": 0}

    def log(self, event: str, **details) -> None:
        """Record one event: 'llm', 'tool', 'guardrail' or 'done'."""
        if event == "llm":
            self.totals["llm_calls"] += 1
            self.totals["tokens"] += details.get("tokens", 0)
        if event == "tool":
            self.totals["tool_calls"] += 1

        elapsed = round(time.time() - self.started, 1)
        print(f"[{elapsed:>6}s] {event:<9} {json.dumps(details, ensure_ascii=False)[:160]}")

        path = os.getenv("TRACE_PATH", "logs/trace.jsonl")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            record = {"run_id": self.run_id, "elapsed": elapsed, "event": event, **details}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def summary(self) -> dict:
        """The cost of the whole run."""
        return {"run_id": self.run_id, **self.totals, "seconds": round(time.time() - self.started, 1)}
