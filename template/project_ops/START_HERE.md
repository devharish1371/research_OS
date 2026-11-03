# Start here

Python 3.9+, macOS/Linux or WSL. No network or paid model required for the ledger.

```sh
./projectctl doctor
./projectctl status
./start-project
```

To populate memory from existing material, invoke `/project-bootstrap` in Claude Code with your goal, source paths/URLs, and each repository's role. It inventories first, reads relevant sections, records source-linked facts and tasks, and saves a handoff. It does not automatically ingest every file or verify unrun results. Use it again for changed sources; it checks existing records before adding more.

| Operation | Command |
|---|---|
| Task-specific context | `./projectctl context --task T1 --query 'baseline' --check-evidence` |
| Search | `./projectctl search 'baseline split' --limit 8` |
| Exact record / history | `./projectctl show C1`; `./projectctl history C1 --limit 10` |
| Task | `./projectctl task add T1 'Title' --acceptance 'Observable result'` |
| Complete task | `./projectctl task set T1 done --evidence results/run.json` |
| Claim | `./projectctl claim C1 reported --text 'Result' --scope 'Run and dataset' --evidence results/run.json` |
| Decision | `./projectctl decide D1 --question 'Question' --choice 'Choice' --source user --why 'Reason'` |
| Observation | `./projectctl note --id N1 --summary 'What happened' --evidence results/run.json` |
| Procedure | `./projectctl remember M1 'Procedure' --kind procedure --source tool_observation` |
| Constraint | `./projectctl remember RULE1 'Constraint' --kind constraint --source user` |
| Handoff | `./projectctl handoff --summary 'Actual outcome' --next 'Concrete action' --evidence results/run.json` |
| Verification | `./projectctl verify --json` |
| Temporal view | `./projectctl search 'query' --as-of 2026-10-01T00:00:00Z` |
| Validity | `./projectctl search 'query' --valid-at 2026-10-01` |
| Lifecycle | `./projectctl archive T1 --reason 'Done'`; `./projectctl restore T1 --reason 'Needed'` |
| Retrieval exclusion | `./projectctl forget N1 --reason 'Exclude'` |
| Recovery | `./projectctl recover` (backs up export and replays valid committed history) |
| Rebuild search | `./projectctl index rebuild` |
| Upgrade v1 | `./projectctl migrate --dry-run`, then `./projectctl migrate` |

`status` defaults to a 4,800-byte packet; `context` defaults to 12,000 bytes. Override with `--max-bytes 8000`. These are UTF-8 byte budgets, not exact token counts. Required-context overflow must be resolved before acting. Hook startup output uses the smaller budget.

Full verification exits 0 for clean, 1 for integrity/schema errors, 2 for active evidence drift. Quick verification returns 3 because evidence was not hashed. `--warn-only` explicitly permits a zero exit despite drift. Routine status labels evidence unverified; `context --check-evidence` checks selected references.

Evidence paths must resolve inside the project. `verified` needs scope and evidence. Changing a verified claim requires an explicit evidence review. Use `--expect-revision N` to reject stale edits. Use `--operation-id KEY` before a mutation command for idempotent retries.

Four hooks: SessionStart, Stop, PreCompact, SessionEnd. Confirm with `/hooks`. Compaction saves only already-recorded state. For concurrent sessions use `handoff --session-id SESSION_ID`; otherwise handoffs are project-wide.

Archive and forget preserve history. Forget excludes both current and historical search, but explicit `show`/`history` remain available. Neither command provides physical deletion.
