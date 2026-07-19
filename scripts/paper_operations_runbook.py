#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.phase3.paper_portfolio_operations import OperationsMode


COMMANDS = (
    "preflight",
    "status",
    "open-validation-session",
    "open-observation-session",
    "open-manual-session",
    "reconcile",
    "checkpoint",
    "backup",
    "verify-backup",
    "test-restore",
    "halt",
    "close-session",
    "daily-report",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper-only operations runbook interface")
    parser.add_argument("command", nargs="?", default="preflight", choices=COMMANDS)
    parser.add_argument("--mode", default=OperationsMode.VALIDATION_ONLY.value)
    parser.add_argument("--operator", default="unknown")
    parser.add_argument("--approval-ref", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--db", default="data/paper_ops/paper.sqlite")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Default is VALIDATION_ONLY to prevent silent activation.
    requested_mode = args.mode.upper()
    if requested_mode not in {mode.value for mode in OperationsMode}:
        raise SystemExit("Unsupported mode")

    if args.command == "open-manual-session" and not args.approval_ref.strip():
        raise SystemExit("Manual session requires --approval-ref")

    payload = {
        "command": args.command,
        "mode": requested_mode,
        "operator": args.operator,
        "approval_ref": args.approval_ref,
        "session_id": args.session_id,
        "db": args.db,
        "paper_only": True,
        "autonomous_execution": False,
        "broker_access": False,
        "production_portfolio_access": False,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
