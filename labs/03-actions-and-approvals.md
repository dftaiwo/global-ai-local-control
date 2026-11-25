# Lab 3 — Controlled actions, approval and audit (10 minutes)

## Goal
Demonstrate how an AI agent can prepare useful enterprise actions **without becoming the final authorising authority**.

```bash
python -m lab.cli seed --reset
python -m lab.cli run --backend offline --role analyst --actor analyst01
python -m lab.cli approvals  # Expect []

python -m lab.cli run --backend offline --role manager --actor manager01
python -m lab.cli approvals  # Expect six PENDING_HUMAN records

python -m lab.cli approve APR-001 --role manager --actor manager01
# Expect DENY (manager is not approver)

python -m lab.cli approve APR-001 --role approver --actor approver01
# Expect APPROVED, but not disbursed

python -m lab.cli audit
```

## Find the enforcement points
- `lab/tools.py::prepare_payment_approvals` checks the real user's role and validates each payment against business rules. A model-selected payment ID does not bypass compliance.
- `lab/tools.py::approve` is **not** registered as a model tool.
- The audit log deliberately excludes customer identities, bank details and raw prompts.

## Exercise: be the model
`simulate-tool-call` lets you play the model: you propose a tool call and the server evaluates it exactly as it would a Bedrock `toolUse` request. No AWS needed.

```bash
python -m lab.cli seed --reset

# Ineligible payments: PAY-002 (compliance PENDING), PAY-005 (BLOCKED), PAY-003 (below ₦5m)
python -m lab.cli simulate-tool-call prepare_payment_approvals '{"payment_ids": ["PAY-002", "PAY-005", "PAY-003"]}' --brief
# Expect: DENIED ×3 (NOT_ELIGIBLE), 0 drafts

# Can the model approve? approve is not a model tool.
python -m lab.cli simulate-tool-call approve '{"request_id": "APR-001"}' --brief
# Expect: DENY, not in the approved tool registry

# Can the model ask for extra fields?
python -m lab.cli simulate-tool-call list_overdue_payments '{"min_amount_ngn": 5000000, "include": "bank_account"}' --brief
# Expect: DENY, only min_amount_ngn is permitted
```

**Windows (PowerShell or cmd):** inline JSON quoting differs between shells and versions, so use the prepared files instead. The `@` prefix reads the arguments from a file:

```powershell
python -m lab.cli simulate-tool-call prepare_payment_approvals "@labs/payloads/ineligible-payments.json" --brief
python -m lab.cli simulate-tool-call approve "@labs/payloads/approve-request.json" --brief
python -m lab.cli simulate-tool-call list_overdue_payments "@labs/payloads/extra-field.json" --brief
```

**Takeaway:** The agent may propose actions, but application policy and authorised people decide whether they may happen.
