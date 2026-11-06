"""API contract (plan section 12). The team server exposes the same shapes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from .team import TeamState


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
    alert_reasons: list[str] = []


class Tiles(BaseModel):
    changes: int  # requests
    changed: int = 0  # requests that changed files
    commits: int = 0  # distinct commits those changes ended on
    files_changed: int
    lines_added: int
    lines_removed: int
    tokens: int
    tok_in: int = 0
    tok_out: int = 0
    tok_cache_read: int = 0
    tok_cache_write: int = 0
    cost_usd: float
    policy_checks: int = 0  # required-skill checks that ran, and how many were met
    policy_met: int = 0
    policy_missed: int  # requests with at least one missed check
    pii_changes: int
    pii_high: int
    background_changes: int = 0  # plugin background turns, left out of every figure above except PII (ADR 0010)
    background_cost_usd: float = 0.0


class DayStat(BaseModel):
    date: str  # IST calendar date, every day in the range is present
    requests: int
    changed: int
    files: int  # distinct files touched that day
    added: int
    removed: int
    commits: int
    cost_usd: float
    cost_by_model: dict[str, float]
    tok_out: int
    pii_changes: int


class GitOutcomes(BaseModel):
    committed: int = 0
    uncommitted: int = 0
    reverted: int = 0


class PolicyStat(BaseModel):
    policy_id: str
    title: str | None
    require_skill: str | None
    mode: str | None
    checks: int
    met: int


class AreaStat(BaseModel):
    area: str
    changes: int
    added: int
    removed: int


class RhythmCell(BaseModel):
    dow: int  # 0 = Monday, IST
    hour: int  # 0-23, IST
    changes: int


class ChangeRow(BaseModel):
    id: str
    seq: int | None
    session_id: str | None
    started_at: str | None
    request: str | None = None  # what the person asked, as stored (pii.store_prompt_text), on one line
    summary: str | None
    background: bool = False  # the turn ran in a plugin's background session (ADR 0010)
    model: str | None
    tool: str
    files: list[str]
    added: int
    removed: int
    tokens: int
    cost_usd: float
    git_status: str | None
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
    prev: Tiles  # the same figures for the period of equal length just before this one
    by_day: list[DayStat]
    git: GitOutcomes
    policies: list[PolicyStat]
    skill_status: dict[str, int]
    areas: list[AreaStat]
    rhythm: list[RhythmCell]
    top_skills: list[SkillStat]
    by_model: list[ModelStat]
    pii_by_type: list[PiiTypeStat]
    pii_top_sources: list[PiiSource]
    alert: Alert


class ChangePage(BaseModel):
    total: int
    counts: SessionCounts = SessionCounts(all=0, yours=0, background=0)
    page: int = 1
    page_size: int = 50
    cost_usd: float = 0.0  # across every page of the filtered set
    items: list[ChangeRow]


class TimelineEntry(ChangeRow):
    actor: str | None = None  # pseudonymous user id from the audit trail, never a login or email
    commit: str | None = None  # short sha of HEAD after the change
    headline: str  # one line: what the turn did
    areas: list[str]  # up to three top folders the change touched, most files first


class TimelineDay(BaseModel):
    day: str  # IST calendar date
    changes: int  # totals cover the whole day, even when its entries continue on the next page
    files: int
    added: int
    removed: int
    commits: int
    entries: list[TimelineEntry]


class TimelinePage(BaseModel):
    total: int
    quiet_hidden: int  # turns with no file changes left out (all_turns brings them back)
    actors: list[str]
    page: int
    page_size: int
    days: list[TimelineDay]


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
    files: list[FileLine]
    skills: list[SkillRun]
    policies: list[PolicyCheck]
    pii: list[PiiFindingOut]
    pii_checked: str


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
    skills: dict[str, Any]
    audit: dict[str, Any]
    pii: dict[str, Any]
    sync: dict[str, Any]
    prices: dict[str, Any]
    tools: list[dict[str, Any]]
    local_data: dict[str, str]


class SettingsIn(BaseModel):
    skills: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    pii: dict[str, Any] | None = None
    sync: dict[str, Any] | None = None
    user: dict[str, Any] | None = None


class Ok(BaseModel):
    ok: bool = True
    detail: dict[str, Any] = {}


class TeamSession(BaseModel):
    state: Literal["signed_in", "signed_out", "not_configured"]
    email: str | None
    role: str | None


class TeamLoginOut(BaseModel):
    url: str | None  # null when sign-in cannot start; reason says why (fixed values, never server text)
    reason: Literal["not_configured", "unavailable"] | None = None


class TeamLogoutOut(BaseModel):
    state: Literal["signed_out"]


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


# Team bodies are untrusted: strict types, and money accepts JSON ints but never NaN/Infinity.
Money = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class TeamProjectOut(BaseModel):
    id: StrictStr
    name: StrictStr
    changes: StrictInt
    last_change_at: StrictStr | None
    cost_7d: Money


class TeamProjects(BaseModel):
    state: TeamState
    reason: StrictStr | None
    projects: list[TeamProjectOut] = []


class TeamTiles(BaseModel):
    changes: StrictInt
    lines_added: StrictInt
    lines_removed: StrictInt
    policy_missed: StrictInt
    pii_changes: StrictInt
    cost_usd: Money


class TeamCostDay(BaseModel):
    date: StrictStr
    by_tool: dict[str, Money]


class TeamSkillRuns(BaseModel):
    skill_id: StrictStr
    runs: StrictInt


class TeamModelRow(BaseModel):
    model: StrictStr
    changes: StrictInt
    tok_out: StrictInt
    cost_usd: Money


class TeamPiiType(BaseModel):
    type: StrictStr
    count: StrictInt


class TeamOverviewData(BaseModel):
    """The team server's overview body; unknown fields are dropped."""

    range: StrictInt
    tiles: TeamTiles
    cost_by_day: list[TeamCostDay] = []
    top_skills: list[TeamSkillRuns] = []
    by_model: list[TeamModelRow] = []
    pii_by_type: list[TeamPiiType] = []


class TeamOverviewOut(BaseModel):
    state: TeamState
    reason: StrictStr | None
    range: StrictInt | None = None
    tiles: TeamTiles | None = None
    cost_by_day: list[TeamCostDay] = []
    top_skills: list[TeamSkillRuns] = []
    by_model: list[TeamModelRow] = []
    pii_by_type: list[TeamPiiType] = []


class TeamMemberOut(BaseModel):
    user_id: StrictStr
    email: StrictStr | None = None
    last_synced_at: StrictStr | None
    changes: StrictInt
    key_expired: StrictBool


class TeamMembers(BaseModel):
    state: TeamState
    reason: StrictStr | None
    members: list[TeamMemberOut] = []
