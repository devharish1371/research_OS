---
name: evidence-audit
description: Challenge a claim, result, source interpretation or readiness-to-ship statement.
---

# Evidence Audit

Read the requested source and the matching claim record. State the estimand: what exactly was measured, on what population or denominator, with which code/data/version, under which protocol. Trace the narrative to primary artifacts. Test the strongest alternative explanation, and check for selection effects, leakage, wrong units or baselines, and whether the evidence supports the wording rather than merely existing. Classify honestly (verified / reported / disputed / hypothesis / unknown) and register revisions with `./projectctl claim ID STATUS --text ... --scope ... --evidence PATH`. Preserve contrary findings; do not silently repair a source or infer a missing configuration.
