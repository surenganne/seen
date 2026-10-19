"""Team server schema (Phase 5 skeleton). Holds synced metadata only: never prompts, diffs or PII values."""

from __future__ import annotations

from sqlalchemy import JSON, Integer, MetaData, String, Text, UniqueConstraint
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
    received_at: Mapped[str] = mapped_column(String(40))


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


class TeamBatch(Base):
    __tablename__ = "team_batches"
    __table_args__ = (UniqueConstraint("key_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_id: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    accepted: Mapped[int] = mapped_column(Integer)
    response: Mapped[str] = mapped_column(Text)
    received_at: Mapped[str] = mapped_column(String(40))
