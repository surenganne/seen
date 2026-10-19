"""API contract (plan section 12). The team server exposes the same shapes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    id: str
    started_at: str | None
    ended_at: str | None
    status: Literal["active", "ended", "incomplete"]
    source: Literal["live", "imported"] = "live"
    last_event_at: str | None
    tool: str
    tool_version: str | None
    entrypoint: str | None = None
    background: bool = False  # started by a plugin through the Agent SDK (entrypoint sdk-*), not by a person
    models: list[str]
    turns: int
    files: int
    tool_calls: int
    events: int
    cost_usd: float


class SessionCounts(BaseModel):
    all: int
    yours: int
    background: int


class SessionPage(BaseModel):
    total: int
    active: int
    counts: SessionCounts
    page: int
    page_size: int
    items: list[SessionOut]


class ProjectOut(BaseModel):
    id: str
    name: str | None
    remote: str | None
    root_path: str | None
    changes: int
    last_change_at: str | None
    cost_7d: float
    alert: bool


class Tiles(BaseModel):
    changes: int
    files_changed: int
    lines_added: int
    lines_removed: int
    tokens: int
    cost_usd: float
    mem_loaded_pct: float | None
    policy_missed: int
    pii_changes: int
    pii_high: int


class DayCost(BaseModel):
    date: str
    by_tool: dict[str, float]


class ChangeRow(BaseModel):
    id: str
    seq: int | None
    session_id: str | None
    started_at: str | None
    summary: str | None
    model: str | None
    tool: str
    files: list[str]
    added: int
    removed: int
    tokens: int
    cost_usd: float
    git_status: str | None
    mem_state: str | None
    skills: list[str]
    policy_missed: bool
    pii_state: str | None
    pii_count: int
    pii_high: bool
    unapproved_skill: bool


class FileStat(BaseModel):
    path: str
    changes: int
    added: int
    removed: int


class SkillStat(BaseModel):
    skill_id: str
    runs: int


class ModelStat(BaseModel):
    model: str
    changes: int
    tok_in: int
    tok_out: int
    tok_cache_read: int
    tok_cache_write: int
    cost_usd: float


class PiiTypeStat(BaseModel):
    type: str
    count: int
    changes: int


class PiiSource(BaseModel):
    source_ref: str
    source_kind: str
    changes: int
    count: int
    types: list[str]
    deny_rule: str | None


class Alert(BaseModel):
    on: bool
    reasons: list[str]


class Overview(BaseModel):
    range: int
    tiles: Tiles
    cost_by_day: list[DayCost]
    recent_changes: list[ChangeRow]
    top_files: list[FileStat]
    top_skills: list[SkillStat]
    by_model: list[ModelStat]
    pii_by_type: list[PiiTypeStat]
    pii_top_sources: list[PiiSource]
    alert: Alert


class ChangePage(BaseModel):
    total: int
    page: int = 1
    page_size: int = 50
    cost_usd: float = 0.0  # across every page of the filtered set
    items: list[ChangeRow]


class FileLine(BaseModel):
    path: str
    added: int
    removed: int


class Tokens(BaseModel):
    input: int
    out: int
    cache_read: int
    cache_write: int


class CostPart(BaseModel):
    kind: Literal["input", "output", "cache_read", "cache_write"]
    tokens: int
    cost_usd: float
    share: float


class MemoryRef(BaseModel):
    memory_id: str
    content_hash: str | None
    type: str | None = None
    status: str | None = None


class SkillRun(BaseModel):
    ordinal: int
    skill_id: str
    kind: str | None
    hash_short: str | None
    trigger: str | None
    status: str | None


class PolicyCheck(BaseModel):
    policy_id: str
    title: str | None
    require_skill: str | None
    met: bool
    mode: str | None


class PiiFindingOut(BaseModel):
    id: str
    type: str | None
    confidence: str | None
    count: int
    distinct_count: int
    source_kind: str | None
    source_ref: str | None
    destination: str | None
    detector: str | None
    status: str | None


class ChangeDetail(BaseModel):
    id: str
    source: Literal["live", "imported"] = "live"
    project_id: str | None
    session_id: str | None
    seq: int | None
    started_at: str | None
    ended_at: str | None
    duration_s: int | None
    summary: str | None
    prompt_text: str | None
    prompt_storage: str
    model: str | None
    tool: str
    tokens: Tokens
    cost_usd: float | None
    price_version: str | None
    prices_verified: bool
    cost_breakdown: list[CostPart]
    git_head_before: str | None
    git_head_after: str | None
    git_status: str | None
    mem_state: str | None
    mem_injected_tokens: int
    files: list[FileLine]
    memories: list[MemoryRef]
    skills: list[SkillRun]
    policies: list[PolicyCheck]
    pii: list[PiiFindingOut]
    pii_checked: str
    memory_saved: list[str]


class SkillOut(BaseModel):
    id: str
    kind: str | None
    origin: str | None
    path: str | None
    description: str | None
    allowed_tools: str | None
    hash: str | None
    hash_short: str | None
    status: str
    runs: int
    last_used: str | None
    first_seen: str | None


class SkillVersionOut(BaseModel):
    hash: str
    hash_short: str
    first_seen: str | None
    approved: bool
    approved_by: str | None
    approved_at: str | None
    runs: int


class SkillDetail(SkillOut):
    versions: list[SkillVersionOut]
    recent_changes: list[ChangeRow]
    required_by: list[str]


class PolicyOut(BaseModel):
    id: str
    title: str | None
    paths: list[str]
    require_skill: str | None
    mode: str | None
    applicable: int
    met: int
    missed: int
    compliance: float


class AuditEventOut(BaseModel):
    seq: int
    event_id: str
    occurred_at: str | None
    recorded_at: str | None
    actor_kind: str | None
    actor_id: str | None
    project_id: str | None
    session_id: str | None
    change_id: str | None
    type: str
    subject: str | None
    outcome: str | None
    detail: dict[str, Any]
    hash: str
    prev_hash: str


class AuditPage(BaseModel):
    page: int
    page_size: int
    items: list[AuditEventOut]


class VerifyOut(BaseModel):
    ok: bool
    count: int
    head: str
    head_seq: int
    break_seq: int | None
    expected: str | None
    found: str | None
    reason: str | None
    verified_at: str
    anchored: bool
    anchor_note: str


class ExportIn(BaseModel):
    project: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")  # becomes part of a file name
    date_from: str | None = None
    date_to: str | None = None
    format: Literal["csv", "ndjson"] = "ndjson"


class ExportOut(BaseModel):
    path: str
    manifest: dict[str, Any]


class SettingsOut(BaseModel):
    user: dict[str, Any]
    memory: dict[str, Any]
    skills: dict[str, Any]
    audit: dict[str, Any]
    pii: dict[str, Any]
    sync: dict[str, Any]
    prices: dict[str, Any]
    tools: list[dict[str, Any]]
    local_data: dict[str, str]


class SettingsIn(BaseModel):
    memory: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    pii: dict[str, Any] | None = None
    sync: dict[str, Any] | None = None
    user: dict[str, Any] | None = None


class Ok(BaseModel):
    ok: bool = True
    detail: dict[str, Any] = {}


class MemoryOut(BaseModel):
    id: str
    type: str
    scope: str
    status: Literal["verified", "unverified", "stale", "invalid"]
    file_ref: str | None
    verified_at: str | None
    source_change: str | None
    stale_reason: str | None
    error: str | None
    body: str
    path: str
    content_hash: str
    used_in: int


class MemoryPage(BaseModel):
    items: list[MemoryOut]
    invalid: list[MemoryOut]
    counts: dict[str, int]


class PiiRow(PiiFindingOut):
    change_id: str | None
    started_at: str | None
    summary: str | None


class PiiPage(BaseModel):
    items: list[PiiRow]
    checked: str


class DenySnippet(BaseModel):
    rules: list[str]
    snippet: str
    note: str
