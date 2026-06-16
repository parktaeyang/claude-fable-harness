# claude-fable-harness

Evidence-based workflow gates for [Claude Code](https://claude.com/claude-code): a goal
ledger with verification checkpoints, a review findings gate, and a **Stop hook that
blocks completion until findings are resolved**.

## What it does

| Layer | Mechanism | Enforcement |
| --- | --- | --- |
| Soft nudge | `SKILL.md` + `UserPromptSubmit` reminder | weak (persuasion) |
| Hard gate (CLI) | `fable_goals.py` / `fable_findings.py` exit codes | strong — can't pass the CLI without evidence |
| **Hard block (Stop hook)** | `fable_stop_gate.py` → `{"decision":"block"}` | strong — the model can't just declare "done" |

- **Goal ledger** — track multi-step work; the final goal requires verification evidence
  and is blocked while findings remain open.
- **Findings gate** — record review findings; `gate` exits non-zero while any are
  open/blocked.
- **Stop hook** — blocks turn completion while blocking findings remain. Activates only
  when `.claude-fable-harness/findings.json` exists, so ordinary sessions are unaffected.

## Install (local dev)

    claude --plugin-dir .

## Install (marketplace)

    claude plugin marketplace add parktaeyang/claude-fable-harness
    claude plugin install claude-fable-harness

Update a loaded plugin mid-session with `/reload-plugins`.

## Install scope (global vs per-project)

The scope is chosen by whoever installs — the plugin does not (and cannot) force it.

- Installing interactively via the `/plugin` menu prompts you to pick a scope.
- The headless `claude plugin install` command defaults to `user` (global).

| Scope | Applies to | How to install |
| --- | --- | --- |
| `user` (default) | all your projects (global) | `claude plugin install claude-fable-harness` |
| `project` | this repo, shared with collaborators (`.claude/settings.json`) | `claude plugin install claude-fable-harness --scope project` |
| `local` | this repo, only you (`.claude/settings.local.json`, gitignored) | `claude plugin install claude-fable-harness --scope local` |

This plugin ships with `"defaultEnabled": false`, so it installs **disabled**. Enable it
when you want the gates active — with the `/plugin` menu or
`claude plugin enable claude-fable-harness`.

## Escape hatches (no infinite loops)

- `FABLE_ALLOW_STOP=1` — explicit override; never block.
- `FABLE_MAX_STOP_BLOCKS` (default `3`) — allow the stop after this many consecutive
  blocks with no progress.
- Progress reset — when the blocking-finding count drops, the counter resets.

## Terminal usage

    export PATH="$PWD/bin:$PATH"
    claude-fable-harness status
    claude-fable-harness goals create --brief "fix bug" --goal "inspect::reproduce" --goal "verify::tests"
    claude-fable-harness findings gate

## Test

    python3 -m unittest discover -s tests -v

Requires Python 3.9+ (standard library only; no third-party dependencies).

## License

MIT — see [`LICENSE`](LICENSE).
