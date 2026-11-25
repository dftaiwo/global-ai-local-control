# Incident card: Moment 6 (print one per pair)

## What happened

> **PAY-008 · ₦17,250,000 · 58 days overdue · compliance status CLEARED**
>
> The workshop agent listed overdue payments and prepared an approval draft (`APR-008`) for the operations manager, `manager01`. A human approver, `approver01`, approved it. Three weeks later, Finance discovers that the vendor is a shell company.
>
> The CFO asks: **"Did the AI approve this?"**

## Your evidence

Approval record (`python -m lab.cli approvals`):

```json
{ "request_id": "APR-008", "payment_id": "PAY-008", "prepared_by": "manager01",
  "status": "APPROVED", "approved_by": "approver01" }
```

Audit log (`python -m lab.cli audit`, offline run):

```text
1  2026-11-24T11:37:32  manager01   LIST_PAYMENTS      ALLOW {"count": 8, "minimum": 5000000}
2  2026-11-24T11:37:32  manager01   PREPARE_APPROVALS  ALLOW {"count": 6, "prepared_count": 6}
3  2026-11-24T11:37:32  approver01  HUMAN_APPROVAL     ALLOW {"request_id": "APR-008"}
```

In a live Bedrock run, each model request also adds a line like:

```text
manager01   BEDROCK_OUTBOUND   ALLOW {"aws_profile": "workshop", "model_id": "eu.amazon.nova-2-lite-v1:0",
                                      "payload_sha12": "c71ff9953480", "source_region": "eu-west-1"}
```

## In pairs (2 minutes)

1. What can you **prove** from this evidence?
2. What can you **not** prove?
3. What would you change, and what would that change cost in privacy?
