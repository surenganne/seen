"""Ledger schema (plan section 8). Same models serve SQLite (local) and Postgres (team)."""

from __future__ import annotations

from sqlalchemy import Float, Integer, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

T = Text


class Base(DeclarativeBase):
    metadata = MetaData()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(T)
    remote: Mapped[str | None] = mapped_column(T)
    root_path: Mapped[str | None] = mapped_column(T)
    created_at: Mapped[str | None] = mapped_column(T)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(T, index=True)
    started_at: Mapped[str | None] = mapped_column(T)
    ended_at: Mapped[str | None] = mapped_column(T)
    tool: Mapped[str] = mapped_column(T, default="claude-code", server_default="claude-code")
    tool_version: Mapped[str | None] = mapped_column(T)
    user_id: Mapped[str | None] = mapped_column(T)
    source: Mapped[str] = mapped_column(T, default="live", server_default="live")  # live | imported
    entrypoint: Mapped[str | None] = mapped_column(T)  # CLAUDE_CODE_ENTRYPOINT; sdk-* = a plugin's background session


class Change(Base):
    __tablename__ = "changes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(T, index=True)
    session_id: Mapped[str | None] = mapped_column(T, index=True)
    seq: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[str | None] = mapped_column(T, index=True)
    ended_at: Mapped[str | None] = mapped_column(T)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    prompt_text: Mapped[str | None] = mapped_column(T)
    summary: Mapped[str | None] = mapped_column(T)
    model: Mapped[str | None] = mapped_column(T)
    tok_in: Mapped[int] = mapped_column(Integer, default=0)
    tok_out: Mapped[int] = mapped_column(Integer, default=0)
    tok_cache_read: Mapped[int] = mapped_column(Integer, default=0)
    tok_cache_write: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    price_version: Mapped[str | None] = mapped_column(T)
    git_head_before: Mapped[str | None] = mapped_column(T)
    git_head_after: Mapped[str | None] = mapped_column(T)
    git_status: Mapped[str | None] = mapped_column(T)  # committed | uncommitted | reverted
    pii_state: Mapped[str | None] = mapped_column(T)  # none | found | blocked
    pii_count: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[str | None] = mapped_column(T)


class ChangeFile(Base):
    __tablename__ = "change_files"
    change_id: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, primary_key=True)
    added: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str | None] = mapped_column(T)  # plugin | user | project | org | builtin | sideload
    origin: Mapped[str | None] = mapped_column(T)
    path: Mapped[str | None] = mapped_column(T)
    scope_project_id: Mapped[str | None] = mapped_column(T)
    description: Mapped[str | None] = mapped_column(T)
    allowed_tools: Mapped[str | None] = mapped_column(T)
    first_seen: Mapped[str | None] = mapped_column(T)
    last_seen: Mapped[str | None] = mapped_column(T)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    hash: Mapped[str] = mapped_column(String, primary_key=True)
    first_seen: Mapped[str | None] = mapped_column(T)
    approved_by: Mapped[str | None] = mapped_column(T)
    approved_at: Mapped[str | None] = mapped_column(T)


class SkillInvocation(Base):
    __tablename__ = "skill_invocations"
    change_id: Mapped[str] = mapped_column(String, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[str | None] = mapped_column(T, index=True)
    hash: Mapped[str | None] = mapped_column(T)
    trigger: Mapped[str | None] = mapped_column(T)  # model | user | subagent
    status: Mapped[str | None] = mapped_column(T)  # approval status at that moment (P4-3)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(T)
    title: Mapped[str | None] = mapped_column(T)
    paths_json: Mapped[str | None] = mapped_column(T)
    require_skill: Mapped[str | None] = mapped_column(T)
    mode: Mapped[str | None] = mapped_column(T)  # report | enforce


class PolicyResult(Base):
    __tablename__ = "policy_results"
    change_id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_id: Mapped[str] = mapped_column(String, primary_key=True)
    met: Mapped[int] = mapped_column(Integer)


class PiiFinding(Base):
    __tablename__ = "pii_findings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    change_id: Mapped[str | None] = mapped_column(T, index=True)
    type: Mapped[str | None] = mapped_column(T)
    confidence: Mapped[str | None] = mapped_column(T)
    count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_count: Mapped[int] = mapped_column(Integer, default=0)
    source_kind: Mapped[str | None] = mapped_column(T)
    source_ref: Mapped[str | None] = mapped_column(T)
    destination: Mapped[str | None] = mapped_column(T)
    detector: Mapped[str | None] = mapped_column(T)
    status: Mapped[str | None] = mapped_column(T)  # open | test_data | allowlisted
    fingerprints_json: Mapped[str | None] = mapped_column(T)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str | None] = mapped_column(T)
    payload_json: Mapped[str | None] = mapped_column(T)
    created_at: Mapped[str | None] = mapped_column(T)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[str | None] = mapped_column(T)
    dead_at: Mapped[str | None] = mapped_column(T)  # the server rejected it for good; parked until `seen sync --retry-failed`
    last_status: Mapped[int | None] = mapped_column(Integer)
