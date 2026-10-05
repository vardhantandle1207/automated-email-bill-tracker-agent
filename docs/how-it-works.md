# How it works

## Where each part lives

| # | Concept | File | What it means here |
|---|---|---|---|
| 1 | LLM | [agent/llm.py](../agent/llm.py) | One function, `chat()`, that sends the conversation to Gemini and returns one reply (an OmniRoute entry exists but is untested) |
| 2 | Tools and tool calling | [agent/tools.py](../agent/tools.py) | Three Python functions the LLM may ask us to run, plus their descriptions |
| 3 | Short-term and long-term memory | [agent/memory.py](../agent/memory.py) | Short-term: the conversation and emails of this run. Long-term: the bill log (`data/bills.csv` or a Google Sheet), kept between runs |
| 4 | Guardrails | [agent/guardrails.py](../agent/guardrails.py) | Block prompt injection, reject values that are not in the email, limit the loop to 8 steps |
| 5 | Observability | [agent/tracing.py](../agent/tracing.py) | Every LLM call and tool call is printed and saved to `logs/trace.jsonl` with tokens and timing |
| 6 | Planning | [agent/agent.py](../agent/agent.py) | The LLM writes a numbered plan before it is given any tool |
| 7 | Agent loop | [agent/agent.py](../agent/agent.py) | ReAct style: think, act, observe, and repeat until the LLM says it is done |
| 8 | Evaluation | [eval.py](../eval.py) | Runs the agent on 66 labelled emails, many of them deliberately hard, and reports accuracy, precision, recall and cost |
| 9 | Deployment | [main.py](../main.py), [Dockerfile](../Dockerfile) | The agent as a web service with one endpoint, `POST /run` |

## How one run works

1. **Plan.** The agent gets the goal "Find the bills in my inbox and log them" and
   writes a numbered plan. No tools are offered yet, so it can only plan.
2. **Fetch.** It calls `fetch_emails`. The input guardrail blocks any email that
   tries to give the agent orders, and cuts very long emails.
3. **Check.** It decides which emails are bills and calls `check_bill` for each
   one, many in a single turn. The tool rejects any amount, vendor or currency
   that is not really in the email, and the agent must fix it and try again. For
   bills that pass, the tool converts the amount to rupees, looks up the vendor's
   past bills in long-term memory, and flags the bill if it is:
   - **overdue**: past its due date, not paid, and not on autopay
   - **above trend**: more than 20% above the average of that vendor's last 3 bills
4. **Log.** It calls `log_bill`, which appends the checked bill to the bill log:
   `data/bills.csv`, or your Google Sheet if you set one up.
   A bill that did not pass the check cannot be logged.
5. **Summarise.** With no tools left to call, it writes a summary and the loop ends.

## Safety

The agent can read emails and append rows to a log. That is all. This is
enforced by what exists, not by the prompt:

- There is no tool to pay, delete, send or edit, so no prompt can make it do so.
- Gmail access uses the `gmail.readonly` permission only.
- The log is append-only, and only a bill that passed `check_bill` can be saved.
  Values are written to the sheet as plain text, so email text cannot run as a formula.
- The Google Sheets permission covers all of your sheets, although the code only
  reads and appends rows in the one sheet you name.
