"""Projector-friendly summary of an agent run: what the model asked, what the server decided."""
from __future__ import annotations

import json
import textwrap
from collections import Counter

LABEL_WIDTH = 14
LINE_WIDTH = 96


def _block(label: str, text: str, max_lines: int | None = None) -> list[str]:
    lines = textwrap.wrap(" ".join(str(text).split()), LINE_WIDTH - LABEL_WIDTH) or [""]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: LINE_WIDTH - LABEL_WIDTH - 1].rstrip() + "…"
    return [(label if i == 0 else "").ljust(LABEL_WIDTH) + line for i, line in enumerate(lines)]


def _describe_call(trace: dict) -> str:
    args = trace.get("input", {})
    if isinstance(args, dict) and isinstance(args.get("payment_ids"), list):
        shown = ", ".join(map(str, args["payment_ids"]))
    elif isinstance(args, dict):
        shown = ", ".join(f"{k}={v:,}" if type(v) is int else f"{k}={v}" for k, v in args.items())
    else:
        shown = json.dumps(args, default=str)[:80]
    outcome = trace["status"]
    result = trace.get("result") or {}
    if "count" in result:
        outcome += f" · {result['count']} records"
    elif "requests" in result:
        statuses = Counter(r["status"] for r in result["requests"])
        outcome = f"{statuses['PENDING_HUMAN']} pending, {statuses['DENIED']} denied"
    prefix = "(simulated) " if trace.get("simulated") else ""
    return f"{prefix}{trace['tool']}({shown}) → {outcome}"


def _server_summary(traces: list[dict]) -> tuple[str, int]:
    statuses, reasons, denials = Counter(), Counter(), []
    for trace in traces:
        if trace["status"] == "DENY":
            denials.append(trace.get("reason", "policy denied the tool call"))
            continue
        if trace["tool"] != "prepare_payment_approvals":
            continue
        for request in (trace.get("result") or {}).get("requests", []):
            statuses[request["status"]] += 1
            if request["status"] == "DENIED":
                reasons[request.get("reason", "?")] += 1
    drafts = statuses["PENDING_HUMAN"]
    if denials:
        return "DENY — " + "; ".join(denials), drafts
    if not statuses:
        return "no approval drafts requested", drafts
    parts = [f"PENDING_HUMAN ×{drafts}"] if drafts else []
    if statuses["DENIED"]:
        parts.append(f"DENIED ×{statuses['DENIED']} ({', '.join(sorted(reasons))})")
    return " · ".join(parts) or "no new drafts (requested records already have drafts)", drafts


def render_brief(result: dict, request: str) -> str:
    traces = result.get("tool_traces", [])
    lines = _block("REQUEST", request, max_lines=2)
    if traces:
        for i, trace in enumerate(traces):
            lines += _block("MODEL ASKED" if i == 0 else "", _describe_call(trace))
    else:
        lines += _block("MODEL ASKED", "no tool calls")
    server, pending = _server_summary(traces)
    drafts = len(result["new_drafts"]) if "new_drafts" in result else pending
    lines += _block("SERVER", server)
    lines += _block("DRAFTS MADE", f"{drafts} (approval drafts only — nothing paid)")
    if result.get("mode") == "bedrock":
        lines += _block("SENT TO AWS", f"{result.get('outbound_requests', '?')} requests · "
                                       f"restricted values: {result.get('restricted_values_sent', '?')}")
        if result.get("model_reasoning"):
            lines += _block("MODEL PLAN", result["model_reasoning"][0], max_lines=2)
    lines += _block("ANSWER", result.get("message", ""), max_lines=6)
    return "\n".join(lines)
