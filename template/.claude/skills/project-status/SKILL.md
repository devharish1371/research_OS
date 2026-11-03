---
name: project-status
description: Recall project progress, open tasks, evidence state and the next action.
---

# Project Status

Run `./projectctl status`, then `search QUERY` and `show ID` for the relevant records. Use `context --task ID --query QUERY --check-evidence` before relying on selected evidence. Report last activity, next action, blockers, conflicts and freshness with dates. Resolve any required-context-overflow warning before acting; status alone does not rehash evidence. Never infer that something finished from elapsed time; check the artifact. Do not promote a claim from narrative alone.
