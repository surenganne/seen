"""Phase 0: turn raw spike recordings into committed, scrubbed fixtures.

Usage: python3 spikes/scrub_fixtures.py <rec_dir>
Writes tests/fixtures/hook_payloads/*.json and tests/fixtures/transcripts/*.jsonl.
Paths are normalised to /work/demo-repo and /home/dev; system-prompt blobs and
attachments are dropped (they carry org instructions, not data we parse).
"""
import json
import os
import re
import sys

REC = sys.argv[1]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
SP = os.path.dirname(REC.rstrip("/"))
KEEP_TYPES = {"user", "assistant", "system", "cost-state", "last-prompt", "queue-operation"}
FORBIDDEN = [os.path.basename(HOME).lower(), "ExampleOrg", "@exampleorg"]


def scrub_text(s: str) -> str:
    s = re.sub(re.escape(SP) + r"/(repos/[\w-]+|spike-repo)", "/work/demo-repo", s)
    s = s.replace(SP, "/work/scratch")
    slug = re.sub(r"[^A-Za-z0-9]", "-", SP)
    s = re.sub(re.escape(HOME) + r"/\.claude/projects/" + re.escape(slug) + r"-(repos-[\w-]+|spike-repo)",
               "/home/dev/.claude/projects/-work-demo-repo", s)
    s = re.sub(re.escape(slug) + r"-(repos-[\w-]+|spike-repo)", "-work-demo-repo", s)
    s = s.replace(HOME + "/repos/seen/spikes/recorder", "/home/dev/seen/plugin")
    s = s.replace(HOME, "/home/dev")
    s = re.sub(r"(?i)ExampleOrg", "ExampleOrg", s)
    s = re.sub(r"/private/tmp/claude-\d+/[^\"\s]*", "/tmp/claude-tasks", s)
    return s


def scrub(obj):
    return json.loads(scrub_text(json.dumps(obj)))


def check(text: str, where: str):
    low = text.lower()
    for f in FORBIDDEN:
        if f in low:
            raise SystemExit(f"scrub failed: '{f}' left in {where}")


# run/file-prefix -> fixture name
PICK = {
    ("run1", "SessionStart_"): "session_start",
    ("run1", "UserPromptSubmit_"): "user_prompt_submit",
    ("run1", "PreToolUse_Read"): "pre_tool_use_read",
    ("run1", "PostToolUse_Read"): "post_tool_use_read",
    ("run1", "PreToolUse_Edit"): "pre_tool_use_edit",
    ("run1", "PostToolUse_Edit"): "post_tool_use_edit",
    ("run1", "PreToolUse_Bash"): "pre_tool_use_bash",
    ("run1", "PostToolUse_Bash"): "post_tool_use_bash",
    ("run1", "PreToolUse_Skill"): "pre_tool_use_skill",
    ("run1", "PostToolUse_Skill"): "post_tool_use_skill",
    ("run1", "Stop_"): "stop",
    ("run1", "SessionEnd_"): "session_end",
    ("gate", "PreToolUse_Write"): "pre_tool_use_write",
    ("gate", "PostToolUse_Write"): "post_tool_use_write",
    ("gate", "PreToolUse_NotebookEdit"): "pre_tool_use_notebook_edit",
    ("gate", "PostToolUse_NotebookEdit"): "post_tool_use_notebook_edit",
    ("stopblock", "Stop_"): "stop_hook_active",  # last Stop of that run has stop_hook_active=true
    ("subagent", "PreToolUse_Skill"): "pre_tool_use_skill_subagent",
    ("subagent", "SubagentStop_"): "subagent_stop",
    ("slash", "UserPromptSubmit_"): "user_prompt_submit_slash_skill",
    ("slash_cmd", "UserPromptSubmit_"): "user_prompt_submit_slash_command",
    ("mcp", "PostToolUse_mcp__fakecrm__lookup_customer"): "post_tool_use_mcp",
    ("fetch", "PostToolUse_WebFetch"): "post_tool_use_webfetch",
    ("bigout", "PostToolUse_Bash"): "post_tool_use_bash_large",
}

out_p = os.path.join(ROOT, "tests/fixtures/hook_payloads")
out_t = os.path.join(ROOT, "tests/fixtures/transcripts")
os.makedirs(out_p, exist_ok=True)
os.makedirs(out_t, exist_ok=True)

transcripts = {}
for (run, prefix), name in PICK.items():
    files = sorted(f for f in os.listdir(os.path.join(REC, run)) if f.split("_", 1)[-1].startswith(prefix) and f.endswith(".json"))
    if not files:
        raise SystemExit(f"missing {run}/{prefix}")
    p = json.load(open(os.path.join(REC, run, files[-1])))["payload"]
    if name == "post_tool_use_bash_large":
        p["tool_response"]["stdout"] = p["tool_response"]["stdout"][:2000] + "...[fixture-trimmed]"
    text = json.dumps(scrub(p), indent=1, sort_keys=True)
    check(text, name)
    open(os.path.join(out_p, name + ".json"), "w").write(text + "\n")
    transcripts[run] = p["transcript_path"]

for run in ("run1", "subagent", "stopblock", "slash", "mcp", "bigout", "recall"):
    tp = transcripts.get(run)
    if not tp:
        tp = json.load(open(os.path.join(REC, run, sorted(f for f in os.listdir(os.path.join(REC, run)) if f[0].isdigit())[0])))["payload"]["transcript_path"]
    lines = []
    for l in open(tp):
        d = json.loads(l)
        if d.get("type") in KEEP_TYPES:
            lines.append(json.dumps(scrub(d), sort_keys=True))
    text = "\n".join(lines) + "\n"
    check(text, run)
    open(os.path.join(out_t, f"{run}.jsonl"), "w").write(text)
    subdir = tp[:-6] + "/subagents"
    if os.path.isdir(subdir):
        for f in os.listdir(subdir):
            if f.endswith(".jsonl"):
                sub = "\n".join(json.dumps(scrub(json.loads(l)), sort_keys=True) for l in open(os.path.join(subdir, f)) if json.loads(l).get("type") in KEEP_TYPES) + "\n"
                check(sub, f)
                os.makedirs(os.path.join(out_t, run, "subagents"), exist_ok=True)
                open(os.path.join(out_t, run, "subagents", f), "w").write(sub)
print("ok", len(PICK), "payloads")
