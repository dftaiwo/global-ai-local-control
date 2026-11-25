# Lab 2 — Build a Data Boundary Gateway (15 minutes)

## Goal
Understand exactly which fields would be sent out of the local trust boundary before a remote inference call.

## The deliberately unsafe shape
```bash
python -m lab.cli unsafe-preview
```

This prints a **local-only simulation** of the risky JSON payload. It NEVER sends the record to AWS. Spot `vendor_name`, `vendor_email` and `bank_account`.

## The safe projection
Open `lab/tools.py::list_overdue_payments` and find the projection dictionary. Only selected records (`payment_id`, `amount_ngn`, `overdue_days`, `compliance_status`, `eligible`) are allowed through.

Inspect `lab/policy.py::validate_outbound`, which enforces an allowlist for results that may go to a remote model.

```bash
python -m lab.cli try-leak --kind tool-result
python -m lab.cli try-leak --kind prompt
```

Both should exit with decision **DENY**. That is an expected, successful security test.

## Participant exercise
In `lab/tools.py`, add `"vendor_email": raw["vendor_email"],` to the projection dictionary in `list_overdue_payments` and run `pytest -q`. Confirm that tests fail with `BoundaryViolation: Unapproved outbound field: vendor_email`. Then revert the change immediately (`git checkout -- lab/tools.py`, or undo the edit) and confirm `pytest -q` passes again.

Then send a request containing an email address and confirm it is blocked before any model call:

```bash
python -m lab.cli run --backend offline --message "Find payments for alpha@example.invalid"
# Expect DENY
```

## Reality check
This demo uses simple regex and field allowlists, **not production DLP**. Existing Bedrock Guardrails are useful defense-in-depth, but AWS documentation specifies that sensitive-information filtering does **not** inspect tool results or tool-call arguments. Application-level validation remains required.

**Takeaway:** The location of a database says nothing about what information you are transmitting to an inference endpoint.
