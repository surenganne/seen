# 1. Hook code ships in seen-cli; the plugin carries a shim

The hook (`seen_core.hook`, stdlib only) is installed as the `seen-hook` console script by `seen-cli`.
`plugin/bin/seen-hook` finds it (SEEN_HOOK_BIN, PATH, ~/.local/bin) and fails open with a visible
systemMessage if it is missing. One source of truth; no vendored copy that drifts. Cost: the plugin
needs seen-cli installed.
