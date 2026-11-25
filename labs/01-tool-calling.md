# Lab 1 — From chatbot to enterprise agent (15 minutes)

## Goal
Give an AI model narrow, typed capabilities to interact with an enterprise system **without granting database access**.

## Starting point
Open `lab/tools.py`. Inspect `TOOL_CONFIG`: the two tool definitions are `list_overdue_payments` and `prepare_payment_approvals`. The descriptions tell the model what tools *mean*; the Python functions enforce what tools *may do*.

Run:
```bash
python -m lab.cli seed --reset
python -m lab.cli run --backend offline
```

If permitted credentials are available:
```bash
python -m lab.cli run --backend bedrock
```

## Trace the call
1. Inspect `lab/agent.py::bedrock_run` and find `client.converse(...)`.
2. Find where Bedrock returns a `toolUse` request and where your code executes `run_tool`.
3. Identify the `toolUseId` / `toolResult` round trip.
4. Identify the maximum tool-iteration limit.
5. Identify who controls the caller role (`role`): does it come from the model? **It must not.**

## Mini-exercise
Change the user request to one that only lists records and does not ask for approvals. The default request says "prepare … for approval", so you must override it with `--message`:

```bash
python -m lab.cli seed --reset
python -m lab.cli run --backend offline --min-amount 10000000 \
  --message "List overdue payments above 10 million naira."
```

Compare the totals with the ₦5m run; no approval drafts should be created. In Bedrock mode, omit `--min-amount` (it is only used offline): the model should choose the threshold from the request.

**Takeaway:** Giving a model a tool description is not giving it authority; the API server must enforce that authority.
