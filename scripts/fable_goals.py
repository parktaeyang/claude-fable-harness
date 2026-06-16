#!/usr/bin/env python3
"""claude-fable-harness goal ledger.

A small evidence-tracking ledger for multi-step work. Each goal is one phase with a
short description and moves through:

    pending -> in_progress -> complete   (or: failed / blocked)

Rules enforced by this tool:
  * Marking a goal ``complete`` requires non-empty ``--evidence``.
  * The FINAL goal additionally requires ``--verify-cmd`` and ``--verify-evidence``.
  * The FINAL goal cannot complete while any finding is still open/blocked
    (see fable_findings.py).
  * Every state change is appended to an append-only ledger (.claude-fable-harness/ledger.jsonl).

Independent implementation. Pure Python standard library; runs on Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional

STATE_DIR = Path(".claude-fable-harness")
GOALS_FILE = STATE_DIR / "goals.json"
FINDINGS_FILE = STATE_DIR / "findings.json"
LEDGER_FILE = STATE_DIR / "ledger.jsonl"

PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETE = "complete"
FAILED = "failed"
BLOCKED = "blocked"

ACTIVE_STATUSES = {PENDING, IN_PROGRESS}
CHECKPOINT_STATUSES = {COMPLETE, FAILED, BLOCKED, IN_PROGRESS}
BLOCKING_FINDING_STATUSES = {"open", "blocked"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(message: str) -> NoReturn:
    print(f"claude-fable-harness goals: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_plan() -> Dict[str, Any]:
    if not GOALS_FILE.exists():
        die("no goal plan; run `create` first.")
    try:
        return json.loads(GOALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        die(f"cannot read goals.json: {exc}")


def save_plan(plan: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    GOALS_FILE.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record(action: str, payload: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    entry = {"ts": now(), "kind": "goals", "action": action}
    entry.update(payload)
    with LEDGER_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def blocking_findings() -> List[Dict[str, Any]]:
    if not FINDINGS_FILE.exists():
        return []
    try:
        data = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [
        f for f in data.get("findings", [])
        if f.get("status") in BLOCKING_FINDING_STATUSES
    ]


def find_goal(plan: Dict[str, Any], goal_id: str) -> Optional[Dict[str, Any]]:
    for goal in plan.get("goals", []):
        if goal.get("id") == goal_id:
            return goal
    return None


def parse_goal_spec(index: int, raw: str) -> Dict[str, Any]:
    """Accept "phase::description" or just "description"."""
    if "::" in raw:
        phase, _, desc = raw.partition("::")
        phase, desc = phase.strip(), desc.strip()
    else:
        phase, desc = "", raw.strip()
    if not desc:
        die(f"goal #{index + 1} has an empty description.")
    return {
        "id": f"G{index + 1:03d}",
        "phase": phase,
        "desc": desc,
        "status": PENDING,
        "evidence": None,
        "verify_cmd": None,
        "verify_evidence": None,
        "updated_at": now(),
    }


# --- commands ---------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> int:
    if not args.goal:
        die("`create` needs at least one --goal.")
    goals = [parse_goal_spec(i, raw) for i, raw in enumerate(args.goal)]
    plan = {
        "brief": args.brief or "",
        "created_at": now(),
        "goals": goals,
    }
    save_plan(plan)
    record("create", {"brief": plan["brief"], "count": len(goals)})
    print(f"Created plan with {len(goals)} goal(s):")
    for goal in goals:
        label = f"[{goal['phase']}] " if goal["phase"] else ""
        print(f"  {goal['id']} {label}{goal['desc']}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    plan = load_plan()
    goals = plan.get("goals", [])
    in_progress = [g for g in goals if g.get("status") == IN_PROGRESS]
    if in_progress:
        goal = in_progress[0]
        print(f"In progress: {goal['id']} {goal['desc']}")
        return 0
    pending = [g for g in goals if g.get("status") == PENDING]
    if not pending:
        print("No pending goals. Plan complete or all goals terminal.")
        return 0
    goal = pending[0]
    goal["status"] = IN_PROGRESS
    goal["updated_at"] = now()
    save_plan(plan)
    record("next", {"id": goal["id"]})
    label = f"[{goal['phase']}] " if goal["phase"] else ""
    print(f"Next: {goal['id']} {label}{goal['desc']}")
    return 0


def cmd_checkpoint(args: argparse.Namespace) -> int:
    plan = load_plan()
    goals = plan.get("goals", [])
    goal = find_goal(plan, args.id)
    if goal is None:
        die(f"unknown goal id '{args.id}'.")
    if args.status not in CHECKPOINT_STATUSES:
        die(f"invalid --status '{args.status}'.")

    is_final = bool(goals) and goals[-1].get("id") == goal["id"]
    evidence = (args.evidence or "").strip()

    if args.status == COMPLETE:
        if not evidence:
            die(f"completing {goal['id']} requires non-empty --evidence.")
        if is_final:
            verify_cmd = (args.verify_cmd or "").strip()
            verify_evidence = (args.verify_evidence or "").strip()
            if not verify_cmd or not verify_evidence:
                die(
                    f"final goal {goal['id']} requires both --verify-cmd and "
                    "--verify-evidence before it can complete."
                )
            blockers = blocking_findings()
            if blockers:
                ids = ", ".join(str(f.get("id", "?")) for f in blockers)
                die(
                    f"cannot complete final goal {goal['id']}: "
                    f"{len(blockers)} blocking finding(s) remain ({ids}). "
                    "Resolve or reject them first (fable_findings.py)."
                )
            goal["verify_cmd"] = verify_cmd
            goal["verify_evidence"] = verify_evidence

    goal["status"] = args.status
    if evidence:
        goal["evidence"] = evidence
    goal["updated_at"] = now()
    save_plan(plan)
    record("checkpoint", {"id": goal["id"], "status": args.status})
    print(f"{goal['id']} -> {args.status}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if not GOALS_FILE.exists():
        print("claude-fable-harness: no goal plan")
        return 0
    plan = load_plan()
    goals = plan.get("goals", [])
    brief = plan.get("brief") or "(no brief)"
    print(f"Plan: {brief}")
    for goal in goals:
        label = f"[{goal['phase']}] " if goal.get("phase") else ""
        mark = {
            COMPLETE: "x", IN_PROGRESS: "~", PENDING: " ",
            FAILED: "!", BLOCKED: "B",
        }.get(goal.get("status", PENDING), "?")
        print(f"  [{mark}] {goal['id']} {label}{goal['desc']}  ({goal.get('status')})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fable_goals.py", description="Goal ledger with evidence gates.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a new goal plan.")
    p_create.add_argument("--brief", default="", help="One-line summary of the work.")
    p_create.add_argument("--goal", action="append", default=[],
                          help='Goal as "phase::description" (repeatable).')
    p_create.set_defaults(func=cmd_create)

    p_next = sub.add_parser("next", help="Advance to / show the next goal.")
    p_next.set_defaults(func=cmd_next)

    p_cp = sub.add_parser("checkpoint", help="Record a checkpoint for a goal.")
    p_cp.add_argument("--id", required=True)
    p_cp.add_argument("--status", required=True, choices=sorted(CHECKPOINT_STATUSES))
    p_cp.add_argument("--evidence", default="")
    p_cp.add_argument("--verify-cmd", dest="verify_cmd", default="")
    p_cp.add_argument("--verify-evidence", dest="verify_evidence", default="")
    p_cp.set_defaults(func=cmd_checkpoint)

    p_status = sub.add_parser("status", help="Show the current plan.")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
