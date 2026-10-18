"""Read-only: summarise recorded spike runs (stream.jsonl + hook payloads)."""
import json
import os
import sys

base = os.path.dirname(os.path.abspath(__file__)) + "/rec"
for n in sys.argv[1:]:
    print("===", n)
    for l in open(f"{base}/{n}/stream.jsonl"):
        d = json.loads(l)
        t, st = d.get("type"), d.get("subtype")
        if t == "result":
            print("RESULT:", (d.get("result") or "")[:300].replace("\n", " | "), "|", st, d.get("is_error"), d.get("total_cost_usd"))
        if t == "system" and st in ("notification", "permission_denied"):
            print("SYS:", json.dumps(d)[:250])
        if t == "system" and st == "hook_response" and d.get("hook_event") in ("UserPromptSubmit", "Stop"):
            print("HOOKRESP", d.get("hook_event"), d.get("exit_code"), d.get("outcome"), repr(d.get("stdout"))[:120], repr(d.get("stderr"))[:120])
        if t == "user" and isinstance(d["message"]["content"], list):
            for c in d["message"]["content"]:
                if c.get("type") == "tool_result" and c.get("is_error"):
                    print("TOOLERR:", str(c.get("content"))[:160].replace("\n", " "))
        if t == "assistant":
            for c in d["message"]["content"]:
                if c.get("type") == "tool_use":
                    print("TOOL_USE", c["name"], json.dumps(c["input"])[:120])
    for f in sorted(os.listdir(f"{base}/{n}")):
        if any(k in f for k in ("Stop_", "NotebookEdit", "Write", "Subagent")):
            p = json.load(open(f"{base}/{n}/{f}"))["payload"]
            print("  ", p["hook_event_name"], p.get("stop_hook_active", ""), p.get("agent_type", ""), json.dumps(p.get("tool_input", ""))[:150])
