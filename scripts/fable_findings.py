#!/usr/bin/env python3
"""claude-fable-harness findings ledger.

Record review findings that must be resolved (or explicitly rejected) before work is
considered done. A finding moves through:

    open / blocked  ->  resolved / rejected

The ``gate`` command exits non-zero while any finding is still open or blocked; the
Stop hook (hooks/fable_stop_gate.py) uses the same rule to block turn completion.
Every state change is appended to an append-only ledger (.claude-fable-harness/ledger.jsonl).

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
FINDINGS_FILE = STATE_DIR / "findings.json"
LEDGER_FILE = STATE_DIR / "ledger.jsonl"

OPEN = "open"
BLOCKED = "blocked"
RESOLVED = "resolved"
REJECTED = "rejected"

BLOCKING_STATUSES = {OPEN, BLOCKED}
SEVERITIES = ["low", "medium", "high", "critical"]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(message: str) -> NoReturn:
    print(f"claude-fable-harness findings: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_store() -> Dict[str, Any]:
    if not FINDINGS_FILE.exists():
        return {"findings": []}
    try:
        data = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        die(f"cannot read findings.json: {exc}")
    data.setdefault("findings", [])
    return data


def save_store(store: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    FINDINGS_FILE.write_text(
        json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def record(action: str, payload: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    entry = {"ts": now(), "kind": "findings", "action": action}
    entry.update(payload)
    with LEDGER_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def next_id(store: Dict[str, Any]) -> str:
    return f"F{len(store['findings']) + 1:03d}"


def find(store: Dict[str, Any], finding_id: str) -> Optional[Dict[str, Any]]:
    for finding in store["findings"]:
        if finding.get("id") == finding_id:
            return finding
    return None


# --- commands ---------------------------------------------------------------

def cmd_add(args: argparse.Namespace) -> int:
    title = (args.title or "").strip()
    if not title:
        die("`add` requires a non-empty --title.")
    store = load_store()
    finding = {
        "id": next_id(store),
        "title": title,
        "severity": args.severity,
        "source": (args.source or "").strip(),
        "location": (args.location or "").strip(),
        "evidence": (args.evidence or "").strip(),
        "status": OPEN,
        "resolution": None,
        "verify_cmd": None,
        "verify_evidence": None,
        "created_at": now(),
        "updated_at": now(),
    }
    store["findings"].append(finding)
    save_store(store)
    record("add", {"id": finding["id"], "severity": finding["severity"]})
    print(f"Added {finding['id']} [{finding['severity']}] {title}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    store = load_store()
    finding = find(store, args.id)
    if finding is None:
        die(f"unknown finding id '{args.id}'.")
    evidence = (args.evidence or "").strip()
    if not evidence:
        die(f"resolving {args.id} requires non-empty --evidence describing the fix.")
    finding["status"] = RESOLVED
    finding["resolution"] = evidence
    finding["verify_cmd"] = (args.verify_cmd or "").strip() or None
    finding["verify_evidence"] = (args.verify_evidence or "").strip() or None
    finding["updated_at"] = now()
    save_store(store)
    record("resolve", {"id": finding["id"]})
    print(f"{finding['id']} -> resolved")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    store = load_store()
    finding = find(store, args.id)
    if finding is None:
        die(f"unknown finding id '{args.id}'.")
    reason = (args.reason or "").strip()
    if not reason:
        die(f"rejecting {args.id} requires a non-empty --reason.")
    finding["status"] = REJECTED
    finding["resolution"] = reason
    finding["updated_at"] = now()
    save_store(store)
    record("reject", {"id": finding["id"]})
    print(f"{finding['id']} -> rejected")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    store = load_store()
    blocking = [f for f in store["findings"] if f.get("status") in BLOCKING_STATUSES]
    if blocking:
        ids = ", ".join(str(f.get("id", "?")) for f in blocking)
        print(
            f"findings gate: FAIL -- {len(blocking)} blocking finding(s) remain ({ids}).",
            file=sys.stderr,
        )
        return 1
    print("findings gate: PASS -- no open/blocked findings.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = load_store()
    findings = store["findings"]
    if not findings:
        print("claude-fable-harness: no findings")
        return 0
    for finding in findings:
        loc = f" @ {finding['location']}" if finding.get("location") else ""
        print(
            f"  {finding['id']} [{finding.get('severity')}] "
            f"({finding.get('status')}){loc}: {finding.get('title')}"
        )
    blocking = sum(1 for f in findings if f.get("status") in BLOCKING_STATUSES)
    print(f"  -- {len(findings)} finding(s), {blocking} blocking")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fable_findings.py", description="Review findings gate.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Add a finding.")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--severity", default="medium", choices=SEVERITIES)
    p_add.add_argument("--source", default="")
    p_add.add_argument("--location", default="")
    p_add.add_argument("--evidence", default="")
    p_add.set_defaults(func=cmd_add)

    p_resolve = sub.add_parser("resolve", help="Resolve a finding with evidence.")
    p_resolve.add_argument("--id", required=True)
    p_resolve.add_argument("--evidence", default="")
    p_resolve.add_argument("--verify-cmd", dest="verify_cmd", default="")
    p_resolve.add_argument("--verify-evidence", dest="verify_evidence", default="")
    p_resolve.set_defaults(func=cmd_resolve)

    p_reject = sub.add_parser("reject", help="Reject a finding with a reason.")
    p_reject.add_argument("--id", required=True)
    p_reject.add_argument("--reason", default="")
    p_reject.set_defaults(func=cmd_reject)

    p_gate = sub.add_parser("gate", help="Exit non-zero if any finding is open/blocked.")
    p_gate.set_defaults(func=cmd_gate)

    p_status = sub.add_parser("status", help="List findings.")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
