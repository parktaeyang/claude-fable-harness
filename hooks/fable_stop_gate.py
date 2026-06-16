#!/usr/bin/env python3
"""claude-fable-harness Stop-hook gate.

Blocks turn completion while review findings remain open/blocked, so the assistant
cannot declare "done" with unresolved findings on the ledger.

Hybrid enforcement (hard block + escape hatches to avoid infinite loops):
  1. FABLE_ALLOW_STOP=1            -> never block (explicit user override).
  2. FABLE_MAX_STOP_BLOCKS (=3)    -> after this many consecutive blocks with NO
                                      progress, allow the stop.
  3. Progress reset                -> if the blocking count drops, the counter resets.

Stop-hook contract (Claude Code): to block, print JSON {"decision":"block","reason":..}
to stdout and exit 0. To allow, print nothing and exit 0. This hook never raises a
non-zero exit on its own internal errors -- a broken gate must not wedge the session.

Activates only when .claude-fable-harness/findings.json exists with blocking findings, so
ordinary sessions are never affected.

Pure Python standard library; runs on Python 3.9+.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_MAX_BLOCKS = 3
BLOCKING_STATUSES = {"open", "blocked"}


def is_truthy(value: str) -> bool:
    return str(value).strip().lower() in TRUTHY


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # never fail the hook on our own write error


def read_event() -> Dict[str, Any]:
    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def allow() -> int:
    return 0


def main() -> int:
    event = read_event()
    session_id = str(event.get("session_id", "default"))

    project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    state_dir = Path(project) / ".claude-fable-harness"
    findings_file = state_dir / "findings.json"

    # No findings ledger -> workflow not active -> allow normal completion.
    if not findings_file.exists():
        return allow()
    try:
        data = read_json(findings_file)
    except (json.JSONDecodeError, OSError):
        return allow()  # never block on our own read error

    blocking = [
        f for f in data.get("findings", [])
        if f.get("status") in BLOCKING_STATUSES
    ]
    if not blocking:
        return allow()

    # Escape 1: explicit user override.
    if is_truthy(os.environ.get("FABLE_ALLOW_STOP", "")):
        print("[claude-fable-harness] FABLE_ALLOW_STOP set; gate bypassed.", file=sys.stderr)
        return allow()

    # Escape 2/3: per-session round limit with progress reset.
    try:
        max_blocks = int(os.environ.get("FABLE_MAX_STOP_BLOCKS", "") or DEFAULT_MAX_BLOCKS)
    except ValueError:
        max_blocks = DEFAULT_MAX_BLOCKS

    state_file = state_dir / "stop_state.json"
    try:
        store = read_json(state_file)
        if not isinstance(store, dict):
            store = {}
    except (json.JSONDecodeError, OSError):
        store = {}

    entry = store.get(session_id) or {"blocks": 0, "last": None}
    current = len(blocking)
    if entry.get("last") is not None and current < entry["last"]:
        entry["blocks"] = 0  # progress made -> reset counter
    entry["last"] = current

    if entry["blocks"] >= max_blocks:
        print(
            f"[claude-fable-harness] gate exhausted after {entry['blocks']} block(s) with no "
            f"progress; allowing stop. {current} finding(s) still open.",
            file=sys.stderr,
        )
        store[session_id] = entry
        write_json(state_file, store)
        return allow()

    entry["blocks"] += 1
    store[session_id] = entry
    write_json(state_file, store)

    ids = ", ".join(str(f.get("id", "?")) for f in blocking)
    reason = (
        f"claude-fable-harness findings gate: {current} blocking finding(s) remain ({ids}). "
        "Resolve each (fable_findings.py resolve --id <id> --evidence \"<fix>\" "
        "--verify-evidence \"<proof>\") or reject it with a reason before finishing. "
        "To override, re-run with FABLE_ALLOW_STOP=1."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
