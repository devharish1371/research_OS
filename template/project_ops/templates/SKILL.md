---
name: my-skill
description: One sentence saying WHEN to use this (what the user asks for) and WHAT it produces. This line decides whether Claude loads the skill.
---

# My Skill

1. Read only what is needed: `project_ops/<doc>.md` (section X), the relevant ledger record (`./projectctl status`).
2. Do the work with the project tool: `./tools/mytool <args>` (read-only by default).
3. Check results against the acceptance criterion in the task or protocol; do not assert success from the tool's exit code alone.
4. Stop and ask before anything irreversible or outward-facing (deleting data, spending compute, sending messages).
5. Record the outcome: `./projectctl task set ID STATUS --evidence PATH`, claims with `./projectctl claim`, then `./projectctl handoff`.
