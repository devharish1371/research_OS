# Start here

Requires Python 3.9+ (stdlib only) and Claude Code. No paid service, no credentials stored.

```bash
./projectctl status          # saved state, next action
./start-project              # print status, then open Claude with a greeting request
```

Plain `claude` in this folder also loads `CLAUDE.md` and the SessionStart hook. Review and trust the project when asked; `/hooks` shows the hooks.

| Command | Purpose |
|---|---|
| `./projectctl init --name N --goal G` | One-time ledger creation (the installer does this) |
| `./projectctl status` | Greeting: last activity, next action, blocked tasks, drift |
| `./projectctl task add ID 'Title' --depends A,B --acceptance '...'` | Add a task |
| `./projectctl task set ID in_progress\|blocked\|done\|deferred --note '...' --evidence PATH` | Update; `done` requires evidence and finished dependencies |
| `./projectctl claim ID STATUS --text '...' --scope '...' --evidence PATH` | Register or revise a typed claim |
| `./projectctl decide ID --question --choice --source user\|assistant_proposal\|external --why` | Decision journal |
| `./projectctl note --summary '...'` | Append an observation without changing the handoff |
| `./projectctl handoff --summary '...' --next '...' --evidence PATH` | Save where the next session resumes |
| `./projectctl verify` | Check structure, journal chain and evidence hashes |

Evidence paths are relative to the project root; `--evidence` can repeat. Slash commands: `/project-status`, `/plan-task`, `/evidence-audit`, `/decision-record`, `/project-handoff`.

To add your own tools, skills and docs, follow `project_ops/EXTENDING.md`.
