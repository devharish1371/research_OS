---
name: project-handoff
description: Save the current work so the next session resumes accurately.
---

# Project Handoff

Inspect what changed this session (not the whole history). Reconcile affected records: `./projectctl task set ID STATUS --note ... --evidence PATH`, `./projectctl claim ID STATUS --text ... --scope ... --evidence PATH`, `./projectctl decide ...`. Then run `./projectctl handoff --summary 'Actual outcome and limitations' --next 'One concrete next action' --evidence PATH` (repeat `--evidence`), then `./projectctl verify`. Record failures and unverified work honestly. Never put credentials, raw transcripts or long speculation in the ledger. If verify fails, inspect the mismatch; never rewrite history to hide it.
