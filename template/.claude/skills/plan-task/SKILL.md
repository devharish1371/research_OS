---
name: plan-task
description: Turn a goal into ledger tasks with dependencies and acceptance criteria before doing the work.
---

# Plan Task

1. Restate the goal and what "done" means in one or two sentences.
2. Check `./projectctl status` and existing tasks to avoid duplicates.
3. Split into small tasks, each with a testable acceptance criterion and explicit dependencies: `./projectctl task add ID 'Title' --depends A,B --acceptance 'Observable condition'`.
4. Name the riskiest assumption and the cheapest check that could falsify it; make that the first task.
5. Writing a plan is not running it. Wait for authorisation before costly, irreversible or outward-facing steps.
