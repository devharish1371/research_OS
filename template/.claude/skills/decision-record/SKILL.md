---
name: decision-record
description: Record a decision with its question, choice, who decided and why, so later sessions do not relitigate or misattribute it.
---

# Decision Record

Use when the user makes a choice, or when you propose one that shapes later work. Run `./projectctl decide ID --question '...' --choice '...' --source user|assistant_proposal|external --why '...'`. Attribute accurately: a proposal you made is `assistant_proposal` until the user accepts it, then record the acceptance as a new `user` decision. Never attribute instructions to people who did not give them. Link superseded decisions in the new `--why`.
