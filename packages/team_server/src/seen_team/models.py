"""Team server schema (Phase 5 skeleton). Holds synced metadata only: never prompts, diffs or PII values."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData()


class TeamProject(Base):
    __tablename__ = "team_projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen: Mapped[str] = mapped_column(String(40))


class TeamChange(Base):
    __tablename__ = "team_changes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(80), index=True)
    started_at: Mapped[str | None] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON)  # type: ignore[type-arg]
    writer_key: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[str] = mapped_column(String(40))


class TeamInstall(Base):
    """An install id belongs to the first key that used it: nobody else can anchor heads for it."""
    __tablename__ = "team_installs"
    install_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    key_id: Mapped[str] = mapped_column(String(32))
    first_seen: Mapped[str] = mapped_column(String(40))


class TeamAuditHead(Base):
    __tablename__ = "team_audit_heads"
    install_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    hash: Mapped[str] = mapped_column(String(64))
    at: Mapped[str] = mapped_column(String(40))
    received_at: Mapped[str] = mapped_column(String(40))


class TeamApiKey(Base):
    __tablename__ = "team_api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    project_id: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # member | lead | admin
    user_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str | None] = mapped_column(String(40), default=None)
    revoked_at: Mapped[str | None] = mapped_column(String(40), default=None)
    origin: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")  # manual | sso


class TeamUser(Base):
    """An SSO identity, keyed by the IdP's stable subject; email is an attribute (lowercased), not the key."""
    __tablename__ = "team_users"
    sub: Mapped[str] = mapped_column(String(200), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))  # member | lead | admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen: Mapped[str] = mapped_column(String(40))
    last_login: Mapped[str] = mapped_column(String(40))


class TeamBatch(Base):
    __tablename__ = "team_batches"
    __table_args__ = (UniqueConstraint("key_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_id: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    accepted: Mapped[int] = mapped_column(Integer)
    response: Mapped[str] = mapped_column(Text)
    received_at: Mapped[str] = mapped_column(String(40))


class TeamUsedToken(Base):
    """sha256 of an id_token already exchanged: one id_token mints at most one key. Pruned once past its exp."""

    __tablename__ = "team_used_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[str] = mapped_column(String(40), index=True)
