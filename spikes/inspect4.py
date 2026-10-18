"""Read-only: skill recall, truncation, MCP coverage, deny-rule hook ordering."""
import json, os

base = os.path.dirname(os.path.abspath(__file__)) + "/rec"

def payloads(n):
    for f in sorted(os.listdir(f"{base}/{n}")):
        if f[0].isdigit():
            yield f, json.load(open(f"{base}/{n}/{f}"))["payload"]

def tlines(n):
    p = next(payloads(n))[1]
    return [json.loads(l) for l in open(p["transcript_path"])]

hook_pre = [p["tool_input"]["skill"] for f, p in payloads("recall") if p["hook_event_name"] == "PreToolUse" and p.get("tool_name") == "Skill"]
hook_post = [p["tool_input"]["skill"] for f, p in payloads("recall") if p["hook_event_name"] == "PostToolUse" and p.get("tool_name") == "Skill"]
tr = [c["input"]["skill"] for d in tlines("recall") if d.get("type") == "assistant" for c in d["message"]["content"] if c.get("type") == "tool_use" and c["name"] == "Skill"]
print("recall: pre", len(hook_pre), "post", len(hook_post), "transcript", len(tr), tr == hook_pre)

for n, tool in (("bigout", "Bash"), ("mcp", "mcp__fakecrm__lookup_customer"), ("fetch", "WebFetch"), ("fetch", "Bash"), ("run1", "Read")):
    post = [p for f, p in payloads(n) if p["hook_event_name"] == "PostToolUse" and p.get("tool_name") == tool]
    resp = json.dumps(post[0]["tool_response"]) if post else ""
    ids = {p["tool_use_id"] for p in post}
    tres = [c for d in tlines(n) if d.get("type") == "user" and isinstance(d["message"]["content"], list) for c in d["message"]["content"] if c.get("type") == "tool_result" and c.get("tool_use_id") in ids]
    tc = json.dumps(tres[0]["content"]) if tres else ""
    print(f"{n}/{tool}: hook_response_len={len(resp)} transcript_result_len={len(tc)}")
    print("   transcript:", tc[:220])
    print("   hook      :", resp[:220])

print("deny_rule hook events:", [(p["hook_event_name"], p.get("tool_name", "")) for f, p in payloads("deny_rule")])
