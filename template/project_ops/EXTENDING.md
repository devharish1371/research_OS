# Extending this setup: project tools, skills and docs

The kit gives you the contract, ledger, hooks and generic skills. Everything specific to your project (scripts, procedures, reference documents) is added on top, using the pattern below so Claude finds it, uses it safely and records what it did.

## 1. Choose the right place

| You need... | Add a... | Where | Loaded when |
|---|---|---|---|
| A rule Claude must always follow | bullet in the contract | `CLAUDE.md` (keep it short) | every session |
| A repeatable action (run an evaluation, query a server, build a report) | **tool** (script) | `tools/` | when run |
| A repeatable *way of working* that uses tools and docs | **skill** | `.claude/skills/<name>/SKILL.md` | when relevant or `/name` |
| Reference facts, procedures, definitions | **doc** | `docs/` (or `project_ops/`) | when a skill or task points to it |
| Something to remember about how *you* like to work, across projects | user memory | `~/.claude/` (not this repo) | every session |
| Automatic behaviour on session or tool events | hook | `.claude/settings.json` | by the harness |

Rule of thumb: contract = what must never be forgotten; skill = how to do a kind of task; doc = what is true; tool = do it deterministically. Put arithmetic and file checks in tools so the model does not have to guess them.

## 2. Add a project tool

1. Copy `project_ops/templates/tool.py` to `tools/<name>.py` (create `tools/`). Use the standard library where you can; add other dependencies to `requirements.txt` and say so in the doc.
2. Make it **deterministic and read-only by default**. Anything that deletes, overwrites, submits or sends needs an explicit flag and is listed under "needs approval" in a runbook.
3. Make its output **evidence**: write JSON/CSV under `results/` containing the input file path and SHA-256, the exact metric and denominator, the protocol reference and a timestamp. A tool that prints a number only to the terminal produces no evidence.
4. Validate inputs (paths inside the project, files exist). Print one clear line on success and a clear error on failure; use non-zero exit codes for failure.
5. **Never take secrets as arguments or write them anywhere.** Read them from the OS keychain or environment variables. On macOS: `security add-generic-password -U -a "$USER" -s my-service -w` (you type the secret yourself) and read it with `security find-generic-password -s my-service -w`.
6. Optionally add a launcher like `projectctl`: a 4-line `sh` file `./mytool` that `exec python3 tools/mytool.py "$@"`.
7. Add a test in `tools/tests/` (a tiny fixture and an assertion on the output) and run `python3 -m unittest discover -s tools/tests`.
8. Register it: add a row to the "Project facts" table in `CLAUDE.md`, and record it as a task: `./projectctl task add TOOL-1 'Build mytool' --acceptance 'Runs on fixture, test passes, output has hash+denominator'`; close it with evidence.

For a tool that talks to a remote system (cluster, API, database): log each command line (without secrets) to `logs/`, keep read-only commands separate from write commands, and have Claude ask before any write. Write the access rules in a runbook (section 4).

## 3. Add a skill

A skill is a short procedure Claude loads on demand. Create `.claude/skills/<name>/SKILL.md` from `project_ops/templates/SKILL.md`.

- **Frontmatter** `name` (kebab-case, matches the folder) and `description`. The description is what Claude uses to decide to load it, so say *when* ("Use when the user asks to run or compare evaluations") and *what it yields*.
- **Body**: numbered steps, which docs to read (by path and section), which tools to run, what must be checked, when to stop and ask, and how to record the outcome in the ledger. Aim for under ~40 lines; link to docs for detail.
- **One workflow per skill.** Split rather than grow. Do not paste whole documents into a skill.
- Add it to the "Skills" line in `CLAUDE.md` so people know it exists.
- Test it: open a session, type `/<name>`, and check that Claude reads the right files, runs the tool, and ends with a handoff. Tighten the wording where it drifted.

Typical project skills: `/run-experiment`, `/compare-results`, `/monitor-jobs`, `/build-report`, `/literature-check`, `/prepare-update` (a status note for a supervisor, never sent automatically).

## 4. Add docs

Keep documents in `docs/` and link them from `CLAUDE.md`'s table; do not make Claude read all of them each session. Templates are in `project_ops/templates/`:

| Doc | Purpose | Template |
|---|---|---|
| Protocol | Exactly how a measurement or experiment is done, with definitions and an acceptance criterion | `protocol.md` |
| Runbook | Access, safe vs approval-needed commands, failures, recovery | `runbook.md` |
| Data dictionary | Files, fields, splits, versions, hashes | `data_dictionary.md` |
| Source map | For papers/specs: which page or section states what, and where sources disagree | (write as a table: claim, source, page, notes) |
| Roadmap | Goals, dependencies, decision points | (write as a list tied to ledger task ids) |

Habits that keep docs trustworthy:

- Put a status line at the top (`proposed`, `frozen on <date>`, `superseded by ...`). Do not edit a frozen protocol silently; write an amendment and record a decision.
- Reference sources by path and page; keep original reference files unmodified in `docs/sources/` or `Papers/`.
- Link to ledger ids (`T2`, `C1`, `D1`) rather than copying changing numbers into prose. Numbers live in result files and claims.
- Write long evidence to files; keep ledger entries short and point to them with `--evidence`.

## 4b. Make Claude use them

After adding a tool, skill or doc, update `CLAUDE.md`:

```markdown
| Evaluate a model | `docs/eval_protocol.md`, `./evaluate` |
Skills: ..., `/run-experiment`
```

and record one decision if it changes how the project works: `./projectctl decide D5 --question 'How do we score runs?' --choice 'Exact match on the full test set via tools/evaluate' --source user --why '...'`.

## 5. Add or tune hooks and permissions

`.claude/settings.json` holds hooks (shared, committed). Personal overrides go in `.claude/settings.local.json` (git-ignored).

- A hook is a command that runs on an event (`SessionStart`, `Stop`, `PreToolUse`, `PostToolUse`, ...). Keep hooks fast (under a few seconds), read-only where possible, and never let them read prompts or transcripts if you share the repo. See the Claude Code hooks docs.
- Example: block edits to frozen files with a `PreToolUse` hook that checks the path and exits non-zero. Test with a dry run before relying on it.
- Permissions: allow the safe read-only commands your tools use so Claude is not interrupted, and leave write commands to prompt. Add them to `.claude/settings.json` under `permissions.allow` (for example `"Bash(./projectctl status)"`, `"Bash(./evaluate:*)"`). Never allow broad patterns like `Bash(rm:*)`.

## 6. Environment and reproducibility

- Pin dependencies in `requirements.txt` (or `environment.yml`); record the Python version and OS in the protocol.
- Record the code version a result came from (`git rev-parse HEAD`) in the result file.
- Keep big data, model weights and caches out of git (`.gitignore`); identify them by hash in the data dictionary instead.
- Seeds, hardware and execution mode (eager vs compiled, CPU vs GPU) are part of the protocol; results from different modes are not interchangeable until shown to be.

## 7. A complete worked example

Goal: "evaluate checkpoints on the test set and compare them."

```bash
mkdir -p tools docs results
cp project_ops/templates/tool.py tools/evaluate.py             # edit: load checkpoint, compute exact accuracy, save JSON
printf '#!/bin/sh\nexec python3 "$(dirname "$0")/tools/evaluate.py" "$@"\n' > evaluate && chmod +x evaluate
cp project_ops/templates/protocol.md docs/eval_protocol.md     # define metric, denominator (all 10,000 test rows), acceptance
mkdir -p .claude/skills/run-eval && cp project_ops/templates/SKILL.md .claude/skills/run-eval/SKILL.md
```

Edit the skill so it says: read `docs/eval_protocol.md`, run `./evaluate CKPT --out results/<ckpt>.json`, confirm the denominator equals 10,000, never compare results from different protocols, record a claim and a handoff. Then:

```bash
./projectctl task add EVAL-1 'Evaluate checkpoint set' --acceptance 'One result JSON per checkpoint, denominator 10000, hashes recorded'
./projectctl decide D2 --question 'Metric' --choice 'Exact match over full test set' --source user --why 'Matches the paper definition'
```

and add the tool, doc and skill to the `CLAUDE.md` table. From now on any session (or friend) can run `/run-eval`, gets the same procedure, and leaves hashed evidence behind.

## 8. Checklist before you rely on an addition

- [ ] Tool output includes input hash, metric, denominator, protocol reference, timestamp
- [ ] Read-only by default; write actions need a flag and are listed as approval-needed
- [ ] No secrets in code, arguments, logs or docs
- [ ] Test or fixture run passes
- [ ] Doc has a status line and is linked from `CLAUDE.md`
- [ ] Skill has a precise `description` and ends by recording a handoff
- [ ] Ledger has a task (with acceptance) and, where relevant, a decision for the new addition
- [ ] `./projectctl verify` passes

## 9. Anti-patterns

- Dumping documents into `CLAUDE.md` (it is loaded every session; link instead).
- A tool that prints results only to the terminal (no evidence, nothing to hash).
- Skills that restate the whole protocol (they go stale; point to the doc).
- Editing a frozen protocol or reference source instead of amending and recording the decision.
- Allowing broad shell permissions to avoid prompts.
- Recording "done" because a script exited 0 rather than because the acceptance criterion was checked.
