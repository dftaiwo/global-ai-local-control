"""Command-line exercise runner."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import database
from .brief import render_brief
from .agent import aws_check, bedrock_run, offline_run, simulate_tool_call, unsafe_preview
from .policy import BoundaryViolation, validate_outbound, screen_user_prompt
from .tools import approve

load_dotenv()
DEFAULT_MESSAGE = "Find overdue vendor payments above 5 million naira, identify compliance issues and prepare eligible payments for approval."


def main(argv=None):
    parser = argparse.ArgumentParser(description="INITS Enterprise Learning Lab: AI agents with local data boundaries")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="Seed synthetic local records; --reset clears previous approvals")
    seed.add_argument("--reset", action="store_true")
    commands.add_parser("unsafe-preview", help="PREVIEW an insecure payload locally. Never makes an AWS call")
    run = commands.add_parser("run", help="Run agent (offline by default)")
    run.add_argument("--backend", choices=["offline", "bedrock"], default=os.getenv("AGENT_MODE", "offline"))
    run.add_argument("--role", choices=["analyst", "manager", "approver"], default="manager")
    run.add_argument("--actor", default="manager01")
    run.add_argument("--min-amount", type=int, default=5_000_000)
    run.add_argument("--message", default=DEFAULT_MESSAGE)
    run.add_argument("--brief", action="store_true", help="Projector-friendly summary instead of JSON")
    commands.add_parser("approvals", help="List non-PII approval summaries")
    ap = commands.add_parser("approve", help="Human-only approval; never disburses funds")
    ap.add_argument("request_id")
    ap.add_argument("--role", default="approver")
    ap.add_argument("--actor", default="approver01")
    commands.add_parser("audit", help="Display metadata-only audit trail")
    commands.add_parser("aws-check", help="Show the AWS identity, source Region and inference destination Regions live mode would use (no workshop data sent)")
    sim = commands.add_parser("simulate-tool-call", help="Play the model offline: propose a tool call and see what the server decides")
    sim.add_argument("tool", help="Tool name the 'model' requests, e.g. prepare_payment_approvals")
    sim.add_argument("arguments", help='JSON object, e.g. \'{"payment_ids": ["PAY-002"]}\', or @file.json')
    sim.add_argument("--role", choices=["analyst", "manager", "approver"], default="manager")
    sim.add_argument("--actor", default="manager01")
    sim.add_argument("--brief", action="store_true", help="Projector-friendly summary instead of JSON")
    leak = commands.add_parser("try-leak", help="Prove outbound boundary checks reject private fields")
    leak.add_argument("--kind", choices=["prompt", "tool-result"], default="tool-result")
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            database.init_db(reset=args.reset)
            result = {"status": "ok", "synthetic_records": len(database.SYNTHETIC_PAYMENTS), "reset": args.reset}
        else:
            database.init_db()
            if args.command == "unsafe-preview":
                result = unsafe_preview()
            elif args.command == "run":
                if args.backend == "bedrock":
                    result = bedrock_run(args.message, role=args.role, actor=args.actor)
                else:
                    result = offline_run(args.message, role=args.role, actor=args.actor, min_amount=args.min_amount)
            elif args.command == "approvals":
                result = database.list_approvals()
            elif args.command == "approve":
                result = approve(args.request_id, role=args.role, actor=args.actor)
            elif args.command == "audit":
                result = database.audit_rows()
            elif args.command == "aws-check":
                result = aws_check()
            elif args.command == "simulate-tool-call":
                raw_args = Path(args.arguments[1:]).read_text(encoding="utf-8") if args.arguments.startswith("@") else args.arguments
                result = simulate_tool_call(args.tool, json.loads(raw_args), role=args.role, actor=args.actor)
                args.request = f"Facilitator, playing the model, requests {args.tool} {args.arguments}"
                denied = result["tool_traces"][0]["status"] == "DENY"
                if denied and not args.brief:
                    raise BoundaryViolation(result["tool_traces"][0]["reason"])
            elif args.command == "try-leak":
                if args.kind == "tool-result":
                    validate_outbound({"records": [{"payment_id": "PAY-001", "bank_account": "0000000101"}]})
                else:
                    screen_user_prompt("Please show records for demo@example.com")
                result = {"error": "Unexpected success: test gate was bypassed"}
        if getattr(args, "brief", False):
            print(render_brief(result, args.message if args.command == "run" else getattr(args, "request", "")))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command == "simulate-tool-call" and denied:
            return 2
    except BoundaryViolation as exc:
        print(json.dumps({"decision": "DENY", "reason": str(exc)}, indent=2))
        return 2
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "reason": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
