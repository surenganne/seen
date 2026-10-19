git add -A && git commit -qm "team: only member keys (bound to a user) can write; container perf factor; docs in test image

Co-Authored-By: Claude Opus 5.5 <[REDACTED:pii:email]>" && echo "Docker re-run: tests 354/354, Playwright 37 + 1 skip ($(git rev-parse --short HEAD))
Ruling: SEEN_PERF_FACTOR=2.5 only in the container test service (Docker Desktop VM process start is slower; hooks run on host) — plan's 150ms hook gate unscaled — cost: container perf regressions under 2.5x go unnoticed there; host run is the gate." >> .superpowers/sdd/SEEN_BUILD_PLAN/progress.md && uv run pytest -m e2e tests/e2e > .superpowers/sdd/SEEN_BUILD_PLAN/e2e.log 2>&1

7 passed in 58.61s

All 7 real-session e2e tests pass on the final code.

Last step from executing-plans: one fresh-context review of the whole branch, using the most capable model.