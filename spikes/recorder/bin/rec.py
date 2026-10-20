"""Phase 0 recorder. Dumps payloads; env switches drive behaviour experiments."""
import json
import os
import sys
import time

ev = sys.argv[1]
raw = sys.stdin.read()
out = os.environ.get("SPIKE_OUT", "/tmp/seen-spike")
os.makedirs(out, exist_ok=True)
try:
    p = json.loads(raw)
except Exception:
    p = {"_raw": raw}
t0 = time.time()
with open(os.path.join(out, f"{time.time_ns()}_{ev}_{p.get('tool_name','')}.json"), "w") as f:
    json.dump({"argv_event": ev, "env_plugin_root": os.environ.get("CLAUDE_PLUGIN_ROOT"),
               "env_project_dir": os.environ.get("CLAUDE_PROJECT_DIR"), "payload": p}, f, indent=1)
E = os.environ.get
tool = p.get("tool_name", "")
ti = p.get("tool_input") or {}
if ev == "SessionStart" and E("SPIKE_CTX"):
    if E("SPIKE_CTX_FORMAT") == "json":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": E("SPIKE_CTX")}}))
    else:
        print(E("SPIKE_CTX"))
if ev == "UserPromptSubmit":
    if E("SPIKE_PCTX"):
        if E("SPIKE_CTX_FORMAT") == "json":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": E("SPIKE_PCTX")}}))
        else:
            print(E("SPIKE_PCTX"))
    if E("SPIKE_PROMPT") == "exit2":
        print("SPIKE: prompt blocked (stderr)", file=sys.stderr); sys.exit(2)
    if E("SPIKE_PROMPT") == "sysmsg":
        print(json.dumps({"systemMessage": "SPIKE-WARN-7731 visible to user only"})); sys.exit(0)
if ev == "PreToolUse":
    if E("SPIKE_BLOCK_EDIT") and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        if "/allowed/" not in path:
            print("SEEN-GATE: edit blocked. Write files only under allowed/ for this test.", file=sys.stderr); sys.exit(2)
    if E("SPIKE_DENY_READ") and tool == "Read" and "secret" in (ti.get("file_path") or ""):
        print("SEEN-PII: read denied, file contains PII", file=sys.stderr); sys.exit(2)
if ev == "Stop" and E("SPIKE_STOP_BLOCK") and not p.get("stop_hook_active"):
    print(json.dumps({"decision": "block", "reason": "Run the greet-skill skill before finishing."})); sys.exit(0)
with open(os.path.join(out, "_latency.tsv"), "a") as f:
    f.write(f"{ev}\t{(time.time()-t0)*1000:.2f}\n")
