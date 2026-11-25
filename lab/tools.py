"""Local business tools. The LLM gets only narrow tool interfaces, not database access."""
from __future__ import annotations

from datetime import datetime, timezone

from . import database
from .policy import BoundaryViolation, validate_model_tool_args, validate_outbound

TOOL_CONFIG = {
    "tools": [
        {"toolSpec": {
            "name": "list_overdue_payments",
            "description": "Retrieve locally computed, privacy-minimised overdue payment summaries by minimum NGN amount; no vendor or bank details.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "min_amount_ngn": {"type": "integer", "description": "Non-negative minimum amount in Nigerian naira, e.g. 5000000"}
            }, "required": ["min_amount_ngn"]}}
        }},
        {"toolSpec": {
            "name": "prepare_payment_approvals",
            "description": "Create PENDING_HUMAN approval drafts for cleared, overdue payments. Does not make payments.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "payment_ids": {"type": "array", "items": {"type": "string"}}
            }, "required": ["payment_ids"]}}
        }}
    ]
}


APPROVAL_THRESHOLD_NGN = 5_000_000


def is_eligible(row) -> bool:
    """Single business rule for approval eligibility, shared by listing and preparation."""
    return row["overdue_days"] > 0 and row["amount_ngn"] >= APPROVAL_THRESHOLD_NGN and row["compliance_status"] == "CLEARED"


def list_overdue_payments(min_amount_ngn: int, actor: str) -> dict:
    records = []
    for raw in database.payment_rows(min_amount_ngn):
        # Trust boundary: raw rows stay local. Only deliberately selected fields leave.
        records.append({
            "payment_id": raw["payment_id"],
            "amount_ngn": raw["amount_ngn"],
            "overdue_days": raw["overdue_days"],
            "compliance_status": raw["compliance_status"],
            "eligible": is_eligible(raw),
        })
    output = {"min_amount_ngn": min_amount_ngn, "count": len(records), "records": records}
    validate_outbound(output)
    database.audit(actor, "LIST_PAYMENTS", "ALLOW", {"count": len(records), "minimum": min_amount_ngn})
    return output


def prepare_payment_approvals(payment_ids: list[str], role: str, actor: str) -> dict:
    if role != "manager":
        database.audit(actor, "PREPARE_APPROVALS", "DENY", {"reason": "role_required_manager"})
        raise BoundaryViolation("Only the manager role may prepare approval drafts.")
    outcomes = []
    with database.connection() as db:
        for payment_id in payment_ids:
            row = db.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
            if not row:
                outcomes.append({"payment_id": payment_id, "status": "DENIED", "reason": "NOT_FOUND"})
                continue
            if not is_eligible(row):
                outcomes.append({"payment_id": payment_id, "status": "DENIED", "reason": "NOT_ELIGIBLE"})
                continue
            existing = db.execute("SELECT request_id, status FROM approvals WHERE payment_id = ?", (payment_id,)).fetchone()
            if existing:
                outcomes.append({"payment_id": payment_id, "status": existing["status"], "request_id": existing["request_id"]})
                continue
            request_id = "APR-" + payment_id.split("-")[1]
            db.execute("INSERT INTO approvals(request_id,payment_id,prepared_by,status,created_at) VALUES (?,?,?,?,?)",
                       (request_id, payment_id, actor, "PENDING_HUMAN", datetime.now(timezone.utc).isoformat()))
            outcomes.append({"payment_id": payment_id, "status": "PENDING_HUMAN", "request_id": request_id})
    result = {"prepared_count": sum(v["status"] == "PENDING_HUMAN" for v in outcomes), "requests": outcomes}
    validate_outbound(result)
    database.audit(actor, "PREPARE_APPROVALS", "ALLOW", {"count": len(outcomes), "prepared_count": result["prepared_count"]})
    return result


def approve(request_id: str, role: str, actor: str) -> dict:
    """Not exposed as an agent tool. Separate human approval endpoint/CLI."""
    if role != "approver" or not actor.strip():
        database.audit(actor or "anonymous", "HUMAN_APPROVAL", "DENY", {"reason": "approver_role_required"})
        raise BoundaryViolation("Only an identified human approver can approve.")

    def deny(reason: str, message: str):
        database.audit(actor, "HUMAN_APPROVAL", "DENY", {"reason": reason, "request_id": request_id})
        return BoundaryViolation(message)

    with database.connection() as db:
        approval = db.execute("SELECT * FROM approvals WHERE request_id = ?", (request_id,)).fetchone()
    if not approval:
        raise deny("not_found", "Approval request not found.")
    if approval["prepared_by"] == actor:
        raise deny("separation_of_duties", "Separation of duties: preparer cannot approve their own request.")
    if approval["status"] != "PENDING_HUMAN":
        raise deny("not_pending", "Approval request is not pending.")
    with database.connection() as db:
        db.execute("UPDATE approvals SET status = 'APPROVED', approved_by = ?, approved_at = ? WHERE request_id = ?",
                   (actor, datetime.now(timezone.utc).isoformat(), request_id))
    database.audit(actor, "HUMAN_APPROVAL", "ALLOW", {"request_id": request_id})
    return {"request_id": request_id, "status": "APPROVED"}


def run_tool(name: str, arguments: dict, role: str, actor: str) -> dict:
    validate_model_tool_args(name, arguments)
    if name == "list_overdue_payments":
        result = list_overdue_payments(arguments["min_amount_ngn"], actor)
    else:
        result = prepare_payment_approvals(arguments["payment_ids"], role, actor)
    validate_outbound(result)
    return result
