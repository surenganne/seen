"""Team sync serializer (plan principle 4, 11B team sync). Builds what may leave the machine.

Allowlist by construction: each field is added only when its switch is on. Never prompts, summaries,
diffs, file contents, PII values, fingerprints or PII source references.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select

from . import audit, config, paths, spool
from .db import ledger_session
from .db.models import Change, ChangeFile, Outbox, PiiFinding, PolicyResult, Session, Skill, SkillInvocation


def _change(db: Any, c: Change, s: dict[str, Any]) -> dict[str, Any]:
    sess = db.get(Session, c.session_id) if c.session_id else None
    files = list(db.scalars(select(ChangeFile).where(ChangeFile.change_id == c.id)))
    out: dict[str, Any] = {"id": c.id, "project_id": c.project_id, "session_id": c.session_id, "seq": c.seq,
                           "started_at": c.started_at, "duration_s": c.duration_s, "tool": sess.tool if sess else "claude-code",
                           "user_id": sess.user_id if sess else None, "model": c.model, "git_status": c.git_status,
                           "file_count": len(files),
                           "lines_added": sum(f.added for f in files), "lines_removed": sum(f.removed for f in files)}
    if s["send_paths"]:
        out["files"] = [{"path": f.path, "added": f.added, "removed": f.removed} for f in files]
    if s["send_tokens"]:
        out.update(tok_in=c.tok_in, tok_out=c.tok_out, tok_cache_read=c.tok_cache_read, tok_cache_write=c.tok_cache_write)
    if s["send_cost"]:
        out.update(cost_usd=c.cost_usd, price_version=c.price_version)
    if s["send_skills"]:
        kinds = dict(db.execute(select(Skill.id, Skill.kind)).all())
        out["skills"] = [{"skill": i.skill_id, "kind": kinds.get(i.skill_id), "hash": i.hash, "trigger": i.trigger, "status": i.status}
                         for i in db.scalars(select(SkillInvocation).where(SkillInvocation.change_id == c.id).order_by(SkillInvocation.ordinal))]
        out["policies"] = [{"policy": p.policy_id, "met": bool(p.met)}
                           for p in db.scalars(select(PolicyResult).where(PolicyResult.change_id == c.id))]
    if s["send_pii_counts"]:
        counts: Counter[str] = Counter()
        for f in db.scalars(select(PiiFinding).where(PiiFinding.change_id == c.id, PiiFinding.status == "open")):
            counts[f.type or "?"] += f.count
        out["pii"] = {"state": c.pii_state, "counts": dict(counts)}
    return out


# Per event type, the detail keys that may leave the machine. Anything else (keyed hashes, ids of
# unknown keys) is dropped. Path keys additionally need send_paths.
AUDIT_DETAIL = {
    "session.start": {"plugin_version", "source"}, "session.end": {"reason"}, "session.incomplete": {"last_seq"},
    "capture.gap": {"hook"}, "turn.start": {"prompt_len", "slash"},
    "turn.end": {"tok_in", "tok_out", "tok_cache_read", "tok_cache_write", "cost_usd", "price_version", "files"},
    "gate.decision": {"hook", "decision", "reason"}, "file.changed": {"path", "added", "removed"},
    "tool.call": {"tool", "cmd0", "skill", "path"}, "skill.invoked": {"skill", "hash", "trigger", "status"},
    "policy.result": {"policy", "met"}, "pii.finding": {"type", "count", "confidence", "destination", "source_kind"},
    "pii.allowlisted": {"count", "source_kind"}, "approval.skill": {"skill", "hash", "old", "new"},
    "approval.pii_test_data": {"type", "old", "new"},
    "config.changed": {"key", "changed"}, "lockfile.changed": set(), "policies.changed": set(),
    "export.created": {"format", "count", "verified"}, "sync.batch": {"kind", "count", "server", "ack"},
    "audit.checkpoint": {"pruned_from_seq", "pruned_to_seq"},
}
PATH_KEYS = {"path"}


def _audit_events(s: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    out = []
    for e in reversed(audit.query(limit=limit)):
        keep = AUDIT_DETAIL.get(e["type"], set()) - (set() if s["send_paths"] else PATH_KEYS)
        d = {k: v for k, v in e["detail"].items() if k in keep}
        out.append({k: e[k] for k in ("seq", "event_id", "occurred_at", "actor_kind", "actor_id", "project_id", "session_id",
                                      "change_id", "type", "outcome", "prev_hash", "hash")} | {"detail": d})
    return out


def heads() -> list[dict[str, Any]]:
    try:
        lines = paths.audit_heads().read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-50:]:
        p = ln.split()
        if len(p) >= 3:
            out.append({"at": p[0], "seq": int(p[1]), "hash": p[2]})
    return out


def build_batch(limit: int = 500) -> dict[str, Any]:
    s = config.load()["sync"]
    if not s["enabled"]:
        return {"changes": [], "audit_heads": [], "audit": []}
    with ledger_session() as db:
        rows = list(db.scalars(select(Change).where(Change.synced_at.is_(None)).order_by(Change.started_at).limit(limit)))
        changes = [_change(db, c, s) for c in rows]
    done = (anchor() or {}).get("seq") or 0
    return {"changes": changes, "audit_heads": [h for h in heads() if h["seq"] > done],
            "audit": _audit_events(s, limit) if s["send_audit"] else []}


# ---- outbox worker (Phase 5): enqueue the allowlisted batch, send with retry and idempotency keys

class SyncError(RuntimeError):
    pass


Transport = Any  # callable(url, headers, body) -> (status, json)


def install_id() -> str:
    """Random per-install id for anchoring; never derived from the user or host."""
    import secrets

    f = paths.home() / "install_id"
    try:
        v = f.read_text().strip()
        if v:
            return v
    except OSError:
        pass
    paths.ensure_dir(f.parent)
    v = "inst_" + secrets.token_hex(12)
    f.write_text(v + "\n")
    return v


def server_url() -> str:
    """The team server base URL from config, with the scheme checks. The key is not needed."""
    from urllib.parse import urlparse

    s = config.load()["sync"]
    url = str(s.get("server") or "").rstrip("/")
    u = urlparse(url)
    if not url or u.scheme not in ("https", "http") or not u.hostname:
        raise SyncError("Set [sync] server = \"https://...\" in ~/.seen/config.toml")
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise SyncError("Refusing to send the API key over plain http; use https (http is allowed for localhost only)")
    return url


def server_and_key() -> tuple[str, str]:
    """Server URL and key. Key order: the env var named by api_key_env, then the `seen team login` key file."""
    import os

    from . import teamauth

    url = server_url()
    name = str(config.load()["sync"].get("api_key_env") or "SEEN_TEAM_API_KEY")
    key = os.environ.get(name, "") or teamauth.load_key() or ""
    if not key:
        raise SyncError(f"No team key: set the {name} environment variable or run `seen team login`")
    return url, key


_server = server_and_key


def parked_auth_statuses() -> set[int]:
    """Which of 401/403 refused a parked batch (401 = expired or revoked key, 403 = access)."""
    with ledger_session() as db:
        return set(db.scalars(select(Outbox.last_status).where(Outbox.dead_at.is_not(None), Outbox.sent_at.is_(None),
                                                               Outbox.last_status.in_((401, 403))).distinct()))


def enqueue() -> dict[str, Any] | None:
    import hashlib
    import json

    b = build_batch()
    if not b["changes"] and not b["audit_heads"]:
        return None
    b["install_id"] = install_id()
    body = json.dumps(b, sort_keys=True, separators=(",", ":"))
    with ledger_session() as db:
        if any(json.loads(o.payload_json or "{}").get("_body") == body for o in db.scalars(select(Outbox).where(Outbox.sent_at.is_(None)))):
            return None  # same batch already waiting (or parked as rejected: it is retried only on request)
        db.add(Outbox(kind="batch", payload_json=json.dumps({"_body": body, "_key": hashlib.sha256(body.encode()).hexdigest()[:40]}),
                      created_at=spool.now(), attempts=0))
        db.commit()
    return b


def _due(o: Outbox, now_offset_s: float) -> bool:
    from datetime import UTC, datetime, timedelta

    if not o.attempts:
        return True
    created = datetime.fromisoformat((o.created_at or spool.now()).replace("Z", "+00:00"))
    backoff = timedelta(seconds=min(3600, 30 * 2 ** (o.attempts - 1)))
    return datetime.now(UTC) + timedelta(seconds=now_offset_s) >= created + backoff


def _http(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (scheme checked in _server)
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 0, {}


RETRYABLE = {0, 408, 425, 429}  # 0 = no answer; every 5xx is retryable too. Other 4xx will not change by waiting.


def push(transport: Transport | None = None, now_offset_s: float = 0, retry_dead: bool = False) -> dict[str, int]:
    import json
    from urllib.parse import urlparse

    url, key = server_and_key()
    if retry_dead:
        with ledger_session() as db:
            for o in db.scalars(select(Outbox).where(Outbox.dead_at.is_not(None), Outbox.sent_at.is_(None))):
                o.dead_at, o.last_status, o.attempts = None, None, 0
            db.commit()
    enqueue()
    send = transport or _http
    sent = failed = dead = 0
    with ledger_session() as db:
        pending = list(db.scalars(select(Outbox).where(Outbox.sent_at.is_(None), Outbox.dead_at.is_(None)).order_by(Outbox.id)))
        for o in pending:
            if not _due(o, now_offset_s):
                continue
            meta = json.loads(o.payload_json or "{}")
            status, resp = send(f"{url}/api/sync", {"Authorization": f"Bearer {key}", "X-Idempotency-Key": meta["_key"],
                                                    "Content-Type": "application/json"}, meta["_body"].encode())
            if 200 <= status < 300:
                o.sent_at = spool.now()
                body = json.loads(meta["_body"])
                ids = [c["id"] for c in body["changes"]]
                for c in db.scalars(select(Change).where(Change.id.in_(ids))):
                    c.synced_at = o.sent_at
                if resp.get("anchored"):
                    _write_anchor({**resp["anchored"], "at": o.sent_at, "server": urlparse(url).netloc})
                sent += 1
                db.commit()
                audit.append([{"type": "sync.batch", "actor_kind": "system", "subject": "batch",
                               "detail": {"kind": "batch", "count": len(ids), "server": urlparse(url).netloc,
                                          "ack": "duplicate" if resp.get("duplicate") else "accepted"}}])
            elif status in RETRYABLE or status >= 500:
                o.attempts = (o.attempts or 0) + 1
                failed += 1
                db.commit()
            else:  # a permanent rejection (bad key, wrong project, too large, invalid): park it, tell the user, keep the data owed
                o.dead_at, o.last_status = spool.now(), status
                dead += 1
                db.commit()
                audit.append([{"type": "sync.batch", "actor_kind": "system", "subject": "batch",
                               "detail": {"kind": "batch", "count": len(json.loads(meta["_body"])["changes"]),
                                          "server": urlparse(url).netloc, "ack": "rejected", "status": status}}])
    return {"sent": sent, "failed": failed, "dead": dead}


def _anchor_file() -> Any:
    return paths.home() / "anchors.json"


def _write_anchor(a: dict[str, Any]) -> None:
    import json

    _anchor_file().write_text(json.dumps(a))


def anchor() -> dict[str, Any] | None:
    import json

    try:
        data: dict[str, Any] = json.loads(_anchor_file().read_text())
        return data
    except (OSError, ValueError):
        return None
