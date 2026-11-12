# 20: Changes are attributed per turn from whole-tree snapshots, so overlapping sessions can be mixed up

Status: accepted as a known limit, 2026-11-12. Revisit if overlapping agents in one repo become common.

**What happens.** At prompt submit the hook takes a snapshot of the repo's working tree (`gitdelta.snapshot`); at Stop
it takes another and `gitdelta.delta` credits the difference to that turn. The snapshots cover the whole working tree,
not the files this session touched. If a second session (or the developer) edits the same repo between the two
snapshots, those edits are credited to the first session's turn too.

**Consequences.** Both sessions can record `ChangeFile` rows and `file.changed` audit events for each other's lines,
which inflates line totals. A `require_skill` rule can be wrongly satisfied (the path changed, but not by the session that
ran the skill) or missed. A file already modified at prompt submit that is edited in place, so its line counts stay the
same, shows no delta; only the edit-tool hint adds the path, with (0, 0) lines. Cost and skill runs are not affected:
they come from each session's own transcript.

**Decision.** Keep whole-tree snapshots. They need only git, work for edits made by any tool, and keep the hook on the
standard library. Attributing per edit would mean recording each edit-tool call's exact patch, which misses shell-made
edits and rename or generated-file cases, and is a larger design change than the problem justifies today.

**Mitigation.** State the limit (docs/limits.md). Per-turn change figures are reliable when one agent works in a
repository at a time. Cost, tokens, skills and PII findings stay per session either way.

**Options if it matters later.** Record the edit tool's file paths per session and restrict each turn's delta to them;
detect overlap (another session with an open turn in the same project) and mark the change `shared` instead of crediting
it; or run agents in separate worktrees, which already keeps their trees apart.
