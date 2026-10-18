"""Replay recorded hook payloads through the real hook against a temp repo."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from seen_core import hook

from tests.conftest import FIXTURES


class Replay:
    def __init__(self, repo: Path, tmp: Path, transcript: str = "run1", sid: str = "sess-1") -> None:
        self.repo, self.sid = repo, sid
        self.src = FIXTURES / "transcripts" / f"{transcript}.jsonl"
        self.tp = tmp / "transcripts" / f"{sid}.jsonl"
        self.tp.parent.mkdir(parents=True, exist_ok=True)
        self.tp.write_text("")
        sub = self.src.with_suffix("") / "subagents"
        if sub.exists():
            shutil.copytree(sub, self.tp.with_suffix("") / "subagents")
        self.prompt_n = 0

    def payload(self, name: str, **over: Any) -> dict[str, Any]:
        d = json.loads((FIXTURES / "hook_payloads" / f"{name}.json").read_text())
        d = json.loads(json.dumps(d).replace("/work/demo-repo", str(self.repo)))
        d.update(session_id=self.sid, transcript_path=str(self.tp), cwd=str(self.repo), prompt_id=f"p{self.prompt_n}")
        d.update(over)
        return d

    def fire(self, event: str, fixture: str, **over: Any) -> hook.Result:
        return hook.run(event, json.dumps(self.payload(fixture, **over)).encode())

    def start(self) -> None:
        self.fire("session-start", "session_start")

    def prompt(self, text: str = "add mul to calc") -> hook.Result:
        self.prompt_n += 1
        return self.fire("prompt-submit", "user_prompt_submit", prompt=text)

    def model_works(self) -> None:
        """Append the recorded turn to the transcript, as Claude Code would."""
        with open(self.tp, "a") as f:
            f.write(self.src.read_text().replace('"id": "msg_', f'"id": "msg{self.prompt_n}_'))

    def stop(self, **over: Any) -> hook.Result:
        return self.fire("stop", "stop", **over)
