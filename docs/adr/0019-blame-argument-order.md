# 19: `git blame` is run without `--end-of-options`: `blame <rev> -- <path>`

Status: proposed, 2026-10-20 (owner to confirm)

Spec section 6.1 first gave `git blame ... --end-of-options <rev> -- <path>`. That failed on the host (git 2.54), so PV-4
changed it to `--end-of-options -- <path> <rev>`, which only worked on newer git. In the Docker image (git 2.39.5,
`python:3.12-slim-bookworm`) `git blame` rejects `--end-of-options` in every position and prints its usage text, so
`blame_file` failed for every file there, and 23 tests failed in the containerised suite. Host gates stayed green because
the host git is newer.

Decision: `git blame --porcelain --no-textconv -w -M -C <rev> -- <path>`, with no `--end-of-options`. Checked in the
2.39.5 container; the other provenance git calls (`show`, `ls-tree`, `rev-parse`, `diff`, `rev-list`, `log`) accept
`--end-of-options` there and keep it.

Why it is safe: `rev` must match `blame.REV` (starts with a letter, digit or `_`, no spaces, no NUL) and `<path>` comes from
`resolve_path` (no leading `-`, no `..`, not absolute, no symlinks). `blame_file` also raises if either starts with `-`
before any git call, so nothing option-shaped reaches git. `--` still ends options before the path.

Guards: `tests/provenance/test_blame.py` asserts the blame argv has no `--end-of-options` and that a `-`-leading rev or path
never reaches git. The Docker suite is the check on old git; rebuild its image first (docs/TESTING.md Part 2).
