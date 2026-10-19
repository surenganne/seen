uv run ruff check . -q && uv run pytest tests > /tmp/seen-final.log 2>&1; tail -1 /tmp/seen-final.log && git add -A && git commit -qm "security: custom PII rules checked on the parsed pattern tree (nested repeats/branches at any depth rejected)

Co-Authored-By: Claude Opus 5.5 <[REDACTED:pii:email]>" && echo "Security (post-review): ReDoS validator bypass via nested groups — sre parse-tree check RED→GREEN ($(git rev-parse --short HEAD))" >> docs/build-ledger.md && git commit -qam "docs: ledger entry" && echo ok

Output: 373 passed, 7 deselected, 1 warning in 56.07s / ok

The package is 1.8 MB, mostly lockfiles, recorded fixtures and the PII corpus, so the reviewer is pointed at the source and the risky surfaces.