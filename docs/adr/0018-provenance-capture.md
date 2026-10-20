# 18: Provenance captures tool-input fingerprints (Method A); MultiEdit dropped

Status: accepted, 2026-10-20

Seen fingerprints the lines in Edit, Write and NotebookEdit tool inputs (spec section 5, Method A), not the
`git diff <head_before>` added lines at turn end (Method B). `spikes/provenance/compare.py` measured both on seven
scratch-repo scenarios. A had 100% precision in every scenario with flagged lines; B fell to 36% when a person edited
during the turn. A's cost is recall for files a command wrote (17% in the Bash scenario), which the report states as a limit.
**MultiEdit:** Claude Code 2.1.304 has no MultiEdit tool (absent from the headless `init` tool list, as in 2.1.302,
hooks-findings A6). No fixture is recorded; drop MultiEdit from `added_lines` and the Task 2 tool set.
**Trivial-line threshold:** stays at 10 alphanumeric characters; nothing in the data argues for a change.

| scenario | A prec | A rec | B prec | B rec | A tp/fp/fn | B tp/fp/fn |
|---|---|---|---|---|---|---|
| in-turn commit | 100% | 100% | 100% | 100% | 10/0/0 | 10/0/0 |
| human commit later | 100% | 100% | 100% | 100% | 8/0/0 | 8/0/0 |
| human edits half | 100% | 100% | 36% | 100% | 5/0/0 | 5/9/0 |
| squash merge | 100% | 100% | 100% | 100% | 10/0/0 | 10/0/0 |
| rename | 100% | 100% | 100% | 100% | 8/0/0 | 8/0/0 |
| Bash-generated file | 100% | 17% | 100% | 100% | 4/0/20 | 24/0/0 |
| human-only repo | n/a | n/a | n/a | n/a | 0/0/0 | 0/0/0 |
