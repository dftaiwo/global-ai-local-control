"""Offline deterministic exercise + live Amazon Bedrock Converse tool-use implementation."""
from __future__ import annotations

import hashlib
import json
import os
import re

from . import database
from .policy import BoundaryViolation, screen_user_prompt, validate_outbound
from .tools import TOOL_CONFIG, run_tool

SYSTEM_PROMPT = """You are an enterprise payments workflow assistant.
Follow the user's request through available business tools. For requests about
payments over a threshold, first call list_overdue_payments. Only request
prepare_payment_approvals for records whose eligible flag is true.
Never request or reproduce vendor identities, emails, bank accounts, or NIN/BVN.
Do not claim that any money has been disbursed. Approval drafts are not payments.
Tools, access control, and business rules are enforced by the application server.
Summarise your work and mention which records require human approval.
"""


THINKING = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
RESPONSE_WRAPPER = re.compile(r"</?response>")


REGISTERED_TOOLS = {t["toolSpec"]["name"] for t in TOOL_CONFIG["tools"]}


def _audit_tool_name(name: object) -> str:
    # Model-supplied names are untrusted text: never write them into the metadata-only audit log.
    return name if name in REGISTERED_TOOLS else "unregistered"


def _pending_drafts() -> set[str]:
    return {a["request_id"] for a in database.list_approvals() if a["status"] == "PENDING_HUMAN"}


def _require_usable_profile() -> None:
    if "AWS_PROFILE" in os.environ and not os.environ["AWS_PROFILE"].strip():
        raise RuntimeError("AWS_PROFILE is blank (usually from .env). Set it to the AWS CLI profile you intend to use, "
                           "or delete the line to use this machine's default credentials.")


def _aws_profile() -> str:
    return os.getenv("AWS_PROFILE", "").strip() or "default"


def _outbound_event(actor: str, payload: object, region: str, model_id: str) -> None:
    # Telemetry is metadata-only; don't store prompts, tool results or raw private records.
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
    database.audit(actor, "BEDROCK_OUTBOUND", "ALLOW", {"source_region": region, "model_id": model_id,
                                                         "aws_profile": _aws_profile(), "payload_sha12": digest})


RESTRICTED_SYNTHETIC_VALUES = [value for row in database.SYNTHETIC_PAYMENTS for value in row[1:4]]


def _restricted_values_in(sent: object) -> int:
    """Runtime self-check: how many synthetic vendor names/emails/accounts appear in what was sent."""
    body = json.dumps(sent, default=str) + SYSTEM_PROMPT
    return sum(value in body for value in RESTRICTED_SYNTHETIC_VALUES)


def _split_reasoning(text: str) -> tuple[str, list[str]]:
    """Some models (e.g. Amazon Nova) wrap planning in <thinking> tags. Keep it out of the answer."""
    reasoning = [r.strip() for r in THINKING.findall(text)]
    answer = RESPONSE_WRAPPER.sub("", THINKING.sub("", text)).strip()
    return answer, reasoning


def offline_run(message: str, actor: str = "manager01", role: str = "manager", min_amount: int = 5_000_000) -> dict:
    screen_user_prompt(message)
    before = _pending_drafts()
    list_args = {"min_amount_ngn": min_amount}
    payment_result = run_tool("list_overdue_payments", list_args, role, actor)
    traces = [{"tool": "list_overdue_payments", "input": list_args, "status": "ALLOW",
               "result": payment_result, "simulated": True}]
    eligible = [v["payment_id"] for v in payment_result["records"] if v["eligible"]]
    blocked = [v["payment_id"] for v in payment_result["records"] if not v["eligible"]]
    results = []
    if eligible and ("prepar" in message.lower() or "approval" in message.lower()):
        prepare_args = {"payment_ids": eligible}
        try:
            result = run_tool("prepare_payment_approvals", prepare_args, role, actor)
            results = result["requests"]
            traces.append({"tool": "prepare_payment_approvals", "input": prepare_args, "status": "ALLOW",
                           "result": result, "simulated": True})
        except BoundaryViolation as exc:
            traces.append({"tool": "prepare_payment_approvals", "input": prepare_args, "status": "DENY",
                           "reason": str(exc), "simulated": True})
            return {"mode": "offline", "message": str(exc), "records": payment_result["records"], "prepared": [],
                    "blocked": blocked, "tool_traces": traces, "new_drafts": []}
    return {
        "mode": "offline",
        "message": f"Found {payment_result['count']} overdue payments >= NGN {min_amount:,}. "
                   f"{len(eligible)} passed compliance checks; {len(blocked)} did not. "
                   f"{'Created pending human approvals, not payments.' if results else 'No approval drafts were created.'}",
        "records": payment_result["records"], "prepared": results, "blocked": blocked, "tool_traces": traces,
        "new_drafts": sorted(_pending_drafts() - before),
    }


def bedrock_run(message: str, actor: str = "manager01", role: str = "manager") -> dict:
    """Live tool calling using AWS credentials from standard boto3 credential chain."""
    import boto3

    safe_message = screen_user_prompt(message)
    _require_usable_profile()
    before = _pending_drafts()
    region = os.getenv("AWS_REGION", "eu-west-1")
    model_id = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
    client = boto3.client("bedrock-runtime", region_name=region)
    messages = [{"role": "user", "content": [{"text": safe_message}]}]
    tool_traces = []
    outbound_requests = 0
    for _ in range(6):
        outbound_requests += 1
        _outbound_event(actor, {"messages": messages, "system": SYSTEM_PROMPT, "tools": TOOL_CONFIG}, region, model_id)
        response = client.converse(
            modelId=model_id,
            messages=messages,
            system=[{"text": SYSTEM_PROMPT}],
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"maxTokens": 700, "temperature": 0},
        )
        response_message = response["output"]["message"]
        messages.append(response_message)
        if response.get("stopReason") != "tool_use":
            raw_text = "\n".join(b["text"] for b in response_message.get("content", []) if "text" in b)
            answer, reasoning = _split_reasoning(raw_text)
            return {"mode": "bedrock", "message": answer or "Model returned no text.", "model_reasoning": reasoning,
                    "tool_traces": tool_traces, "region": region, "model_id": model_id, "aws_profile": _aws_profile(),
                    "outbound_requests": outbound_requests, "new_drafts": sorted(_pending_drafts() - before),
                    "restricted_values_sent": _restricted_values_in(messages[:-1])}
        result_blocks = []
        for block in response_message["content"]:
            if "toolUse" not in block:
                continue
            tool = block["toolUse"]
            try:
                output = run_tool(tool["name"], tool["input"], role, actor)
                validate_outbound(output)
                result_blocks.append({"toolResult": {"toolUseId": tool["toolUseId"],
                                                       "content": [{"json": output}], "status": "success"}})
                tool_traces.append({"tool": tool["name"], "input": tool["input"], "status": "ALLOW", "result": output})
            except (BoundaryViolation, ValueError) as exc:
                database.audit(actor, "TOOL_EXECUTION", "DENY", {"tool": _audit_tool_name(tool["name"]), "reason": type(exc).__name__})
                safe_error = {"error": "Policy denied the requested tool operation."}
                result_blocks.append({"toolResult": {"toolUseId": tool["toolUseId"],
                                                       "content": [{"json": safe_error}], "status": "error"}})
                tool_traces.append({"tool": tool["name"], "input": tool["input"], "status": "DENY", "reason": str(exc)})
        if not result_blocks:
            raise RuntimeError("Model requested tool use without toolUse blocks.")
        messages.append({"role": "user", "content": result_blocks})
    raise RuntimeError("Tool iteration limit reached (6); request aborted for safety.")


def simulate_tool_call(tool: str, arguments: object, role: str = "manager", actor: str = "manager01") -> dict:
    """Offline 'be the model': the facilitator proposes a tool call; the server decides as it would for Bedrock."""
    trace = {"tool": tool, "input": arguments}
    before = _pending_drafts()
    try:
        output = run_tool(tool, arguments, role, actor)
        trace.update(status="ALLOW", result=output)
    except BoundaryViolation as exc:
        database.audit(actor, "TOOL_EXECUTION", "DENY", {"tool": _audit_tool_name(tool), "reason": type(exc).__name__})
        trace.update(status="DENY", reason=str(exc))
    prepared = [r for r in (trace.get("result") or {}).get("requests", []) if r["status"] == "PENDING_HUMAN"]
    return {"mode": "simulated-model", "tool_traces": [trace], "prepared": prepared,
            "new_drafts": sorted(_pending_drafts() - before),
            "message": "The server evaluated the requested tool call exactly as it would a Bedrock toolUse block."}


GEO_PROFILE_PREFIXES = ("eu.", "us.", "apac.", "us-gov.", "ca.", "jp.", "au.", "global.")


def aws_check() -> dict:
    """Pre-flight for live mode: WHO will call AWS, from WHERE, and where inference MAY run.

    Makes read-only control-plane calls (STS + Bedrock); never sends workshop data.
    """
    import boto3

    _require_usable_profile()
    region = os.getenv("AWS_REGION", "eu-west-1")
    model_id = os.getenv("BEDROCK_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
    identity = boto3.client("sts", region_name=region).get_caller_identity()
    if model_id.startswith(GEO_PROFILE_PREFIXES):
        try:
            profile = boto3.client("bedrock", region_name=region).get_inference_profile(inferenceProfileIdentifier=model_id)
            destinations = sorted({m["modelArn"].split(":")[3] for m in profile.get("models", [])})
        except Exception as exc:  # e.g. AccessDenied on bedrock:GetInferenceProfile
            destinations = [f"unknown ({type(exc).__name__}) - check the AWS model card"]
    else:
        destinations = [region]
    return {
        "aws_profile": _aws_profile(),
        "account": "********" + identity["Account"][-4:],
        "principal_type": identity["Arn"].split(":")[5].split("/")[0],
        "source_region": region,
        "model_id": model_id,
        "destination_regions": destinations,
        "note": "Live mode may process screened prompts and allowlisted tool results in any of the destination "
                "Regions above. Raw records stay in the local SQLite database.",
    }


def unsafe_preview() -> dict:
    """Show the risky JSON shape; intentionally NEVER calls a model or network."""
    row = database.payment_by_id("PAY-001")
    if not row:
        raise RuntimeError("Run `python -m lab.cli seed` first.")
    return {"WARNING": "LOCAL SIMULATION ONLY - THIS DATA IS NOT SENT TO AWS",
            "would_have_sent_to_remote_model": row,
            "risk": "Vendor identity, email, account number, and commercial record would leave the local trust boundary."}
