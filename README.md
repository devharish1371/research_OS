# claude-project-kit

A drop-in setup that makes Claude Code work rigorously and resume accurately in any project. It is distilled from a research workspace and is domain-neutral.

## What you get

| Piece | Purpose |
|---|---|
| `CLAUDE.md` | Working contract every Claude model follows: no invented results, typed claims, evidence for "done", ask before irreversible actions, no secrets, mandatory handoff |
| `project_ops/projectctl.py` + `./projectctl` | Stdlib-only ledger: tasks with dependencies and acceptance criteria, typed claims, decision journal, handoff, hash-chained history, evidence hashing, `verify` |
| `.claude/settings.json` | Hooks: SessionStart greets with last activity and next action; Stop reminds once if files changed without a handoff; SessionEnd saves a fingerprint |
| `.claude/skills/` | `/project-status`, `/plan-task`, `/evidence-audit`, `/decision-record`, `/project-handoff` |
| `start-project` | Prints status and opens Claude with a greeting request |
| `project_ops/START_HERE.md`, `SYSTEM_DESIGN.md` | Commands and the reasoning behind the design |

Requires Python 3.9+ (macOS/Linux) and Claude Code. No dependencies, no network calls, nothing sent anywhere.

## Install into any folder

```bash
git clone https://github.com/<you>/claude-project-kit.git ~/claude-project-kit   # once
~/claude-project-kit/install.sh /path/to/project --name "My Project" --goal "One-sentence goal"
cd /path/to/project && ./start-project      # or just: claude
```

Existing files are never overwritten (use `--force` to replace). The installer fills `CLAUDE.md`, appends to `.gitignore`, and creates the ledger. Then edit the "Project facts" table in `CLAUDE.md` with your own docs and protocols.

Update an existing project to a newer kit with `git -C ~/claude-project-kit pull && ~/claude-project-kit/install.sh . --force` (this overwrites `CLAUDE.md`, so merge your edits first).

## Daily use

Claude reads the contract and the greeting automatically. You can say things like "plan this as tasks", "audit this claim", "record that I decided X" or "/project-handoff". Commit `project_ops/state.json` and `project_ops/logs/` if you want the history versioned.

## Extending it

Add domain tools next to `projectctl` (cluster access, deck builders, evaluators), one skill per workflow under `.claude/skills/<name>/SKILL.md`, and a row for each in `CLAUDE.md`. Keep `CLAUDE.md` short; put detail in linked files so context stays small.

## Limits

The ledger is a local audit trail, not tamper-proof. Hooks cannot read the conversation, so the handoff must be written deliberately. Run `python3 -m unittest discover -s project_ops/tests` after changing `projectctl.py`.
