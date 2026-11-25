"""Simple deterministic policy gate. Teaching example, NOT full PII detection or a DLP product.

Important: NEVER let the model decide what data is safe to transmit. Validate
both model-generated tool arguments and tool results in application code.
"""
from __future__ import annotations

import json
import re

class BoundaryViolation(ValueError):
    pass

# Strict allowlists. Every key sent to a remote model must be explicitly approved.
OUTBOUND_PAYMENT_FIELDS = {
    "payment_id", "amount_ngn", "overdue_days", "compliance_status", "eligible"
}
OUTBOUND_RESULT_FIELDS = {
    "payment_id", "amount_ngn", "overdue_days", "compliance_status", "eligible",
    "count", "records", "min_amount_ngn", "status", "request_id", "requests",
    "reason", "error", "policy", "prepared_count"
}
DENIED_FIELDS = {"vendor_name", "vendor_email", "bank_account", "nin", "bvn", "full_name"}
# This is a deliberately narrow lab input check. Production: enterprise DLP, contextual
# policy classification, data inventory, and checks on ALL outputs/log sinks.
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
LONG_DIGITS = re.compile(r"(?<!\d)\d{10,11}(?!\d)")
PAYMENT_ID = re.compile(r"^PAY-\d{3}$")


def screen_user_prompt(prompt: str) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise BoundaryViolation("The request must be non-empty text.")
    if len(prompt) > 600:
        raise BoundaryViolation("Request exceeds the 600-character demo limit.")
    if EMAIL.search(prompt) or LONG_DIGITS.search(prompt):
        raise BoundaryViolation("Raw email/account/NIN-like information is blocked from remote prompts.")
    return prompt.strip()


def validate_model_tool_args(name: str, arguments: dict) -> None:
    if not isinstance(arguments, dict):
        raise BoundaryViolation("Tool arguments must be a JSON object.")
    if name == "list_overdue_payments":
        if set(arguments) != {"min_amount_ngn"}:
            raise BoundaryViolation("Only min_amount_ngn is permitted for list_overdue_payments.")
        amount = arguments["min_amount_ngn"]
        if type(amount) is not int or not 0 <= amount <= 1_000_000_000:
            raise BoundaryViolation("min_amount_ngn must be an integer between 0 and 1 billion.")
    elif name == "prepare_payment_approvals":
        if set(arguments) != {"payment_ids"}:
            raise BoundaryViolation("Only payment_ids is permitted for prepare_payment_approvals.")
        ids = arguments["payment_ids"]
        if not isinstance(ids, list) or not (1 <= len(ids) <= 20):
            raise BoundaryViolation("Provide 1–20 distinct payment IDs.")
        if not all(isinstance(v, str) and PAYMENT_ID.fullmatch(v) for v in ids):
            raise BoundaryViolation("Payment references must use the PAY-### format.")
        if len(set(ids)) != len(ids):
            raise BoundaryViolation("Provide 1–20 distinct payment IDs.")
    else:
        raise BoundaryViolation(f"Tool {name!r} is not in the approved tool registry.")


def validate_outbound(value) -> None:
    """Reject forbidden fields or unmistakable PII in a tool result before Bedrock."""
    def walk(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in DENIED_FIELDS or key not in OUTBOUND_RESULT_FIELDS:
                    raise BoundaryViolation(f"Unapproved outbound field: {key}")
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            if EMAIL.search(node) or LONG_DIGITS.search(node):
                raise BoundaryViolation("Potential direct identifier detected in outbound tool result.")
        elif node is not None and type(node) not in (int, bool, float):
            raise BoundaryViolation("Unsupported outbound data type.")
    walk(value)
    json.dumps(value)
