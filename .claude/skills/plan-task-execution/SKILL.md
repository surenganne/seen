---
name: plan-task-execution
description: Use when executing SEEN_BUILD_PLAN.md tasks or phase gates.
category: workflow
---

# Plan task execution

Work SEEN_BUILD_PLAN.md one task at a time, in order. Name the task ID in every commit message. If the plan is wrong or unclear, stop, write a short note in docs/adr/, and ask the owner.

- Every deliberate call (a gate scaled, a check skipped, a trade-off taken) gets a `Ruling:` line in `.superpowers/sdd/SEEN_BUILD_PLAN/progress.md`. State the cost in the same line.
- Parsers and algorithms: write the failing test first, confirm red, then implement to green.
- Before closing a phase, run in order: the host gates from CLAUDE.md (ruff, mypy, pytest, pii_benchmark, gen_openapi, web gates), then the containerised suites (see docker-test-parity), then the real-Claude e2e suite once against the final code with `uv run pytest -m e2e tests/e2e`.
- Only after those pass: build the whole-branch review package and dispatch a fresh-context reviewer. Read its findings before declaring the phase done.
- Never claim a gate passed from an rc you did not read. Check exit codes and the summary line.
