# Tool map — intent to Claude Code tool

A quick reference for which Claude Code tool serves each step of the workflow.

| Intent | Claude Code tool |
| --- | --- |
| View a file | `Read` |
| Change a file | `Edit` / `Write` |
| Search file contents | `Grep` |
| Find files by name/glob | `Glob` |
| Run a shell command / tests | `Bash` |
| Fetch a web page | `WebFetch` |
| Search the web for fresh facts | `WebSearch` |
| Track a multi-step plan | TodoWrite / task tools |

## Evidence ledgers (this plugin)
| Intent | Command |
| --- | --- |
| Plan multi-step work with evidence | `scripts/fable_goals.py create … / next / checkpoint` |
| Record a review finding | `scripts/fable_findings.py add …` |
| Resolve / reject a finding | `scripts/fable_findings.py resolve … / reject …` |
| Check the findings gate | `scripts/fable_findings.py gate` |

The Stop hook reads `.claude-fable-harness/findings.json` and blocks turn completion while any
finding is open or blocked. It activates only when that file exists, so ordinary
sessions are unaffected.
