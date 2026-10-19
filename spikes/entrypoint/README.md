# Spike: which entrypoint does a hook see? (2026-10-19, Claude Code 2.1.303)

Question: can a hook tell a person's session from one a plugin starts through the Agent SDK?

Run: `settings.json` here as `.claude/settings.json` in an empty, non-git folder (`SPIKE_DIR`), then
`claude -p "reply with the single word ok" --model claude-haiku-5-5` from inside an interactive session.

Recorded:

    start entrypoint=sdk-cli
    prompt entrypoint=sdk-cli

So hooks inherit `CLAUDE_CODE_ENTRYPOINT` from the Claude Code process, and a child `claude -p` gets `sdk-cli` even
though its parent's environment says `cli`. Interactive sessions report `cli`. Transcripts carry the same value in
each line's `entrypoint` field; in this repo on 2026-10-19: 2 `cli`, 11 `sdk-cli`, 118 `sdk-py`.
