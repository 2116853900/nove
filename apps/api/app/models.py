from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), default="Local workspace")


class Novel(Base, TimestampMixin):
    __tablename__ = "novels"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    genre: Mapped[str] = mapped_column(String(80), default="未分类")
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    core_idea: Mapped[str] = mapped_column(Text, default="")
    target_words: Mapped[int] = mapped_column(Integer, default=200000)
    planned_chapters: Mapped[int] = mapped_column(Integer, default=80)
    narrative_pov: Mapped[str] = mapped_column(String(80), default="第三人称限知")
    tense: Mapped[str] = mapped_column(String(40), default="过去时")
    style: Mapped[str] = mapped_column(Text, default="")
    writing_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    creation_mode: Mapped[str] = mapped_column(String(32), default="scratch")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class NovelRule(Base, TimestampMixin):
    __tablename__ = "novel_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    rule: Mapped[str] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(String(60), default="世界设定")
    importance: Mapped[str] = mapped_column(String(12), default="中")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    violations: Mapped[int] = mapped_column(Integer, default=0)


class OutlineNode(Base, TimestampMixin):
    __tablename__ = "outline_nodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("outline_nodes.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(240))
    position: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OutlinePreview(Base):
    """A short-lived, confirm-before-write outline or blueprint draft."""

    __tablename__ = "outline_previews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Chapter(Base, TimestampMixin):
    __tablename__ = "chapters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    outline_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chapter_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(240))
    state: Mapped[str] = mapped_column(String(32), default="PLANNED")
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    latest_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    needs_check: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_status: Mapped[str] = mapped_column(String(24), default="NOT_INDEXED")
    target_words: Mapped[int] = mapped_column(Integer, default=3500)
    brief: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("novel_id", "chapter_index"),)


class ChapterVersion(Base, TimestampMixin):
    __tablename__ = "chapter_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(String(64), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    audit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    locked_ranges: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("chapter_id", "sequence"),)


class StoryEntity(Base, TimestampMixin):
    __tablename__ = "story_entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list)


class CharacterState(Base, TimestampMixin):
    """Per-chapter character state (location, body, knowledge boundary, etc.)."""

    __tablename__ = "character_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("story_entities.id"), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(200), default="")
    body_status: Mapped[str] = mapped_column(String(120), default="健康")
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    emotion: Mapped[str] = mapped_column(String(80), default="")
    known_facts: Mapped[list[str]] = mapped_column(JSON, default=list)
    beliefs: Mapped[list[str]] = mapped_column(JSON, default=list)
    inventory: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("entity_id", "chapter_id"),)


class LocationState(Base, TimestampMixin):
    """Per-chapter location condition (destroyed/blocked/occupied)."""

    __tablename__ = "location_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("story_entities.id"), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    condition: Mapped[str] = mapped_column(String(40), default="normal")
    # normal | destroyed | blocked | occupied
    controlled_by: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("entity_id", "chapter_id"),)


class StoryEvent(Base, TimestampMixin):
    __tablename__ = "story_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_outline_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    story_time: Mapped[str] = mapped_column(String(120))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    subjects: Mapped[list[str]] = mapped_column(JSON, default=list)
    action: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(200), default="")
    consequences: Mapped[str] = mapped_column(Text, default="")


class PlotThread(Base, TimestampMixin):
    __tablename__ = "plot_threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    planted: Mapped[str] = mapped_column(String(100), default="")
    payoff: Mapped[str] = mapped_column(String(100), default="")
    importance: Mapped[str] = mapped_column(String(12), default="中")
    latest: Mapped[str] = mapped_column(Text, default="")
    source_outline_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class StoryBeat(Base, TimestampMixin):
    __tablename__ = "story_beats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_label: Mapped[str] = mapped_column(String(100))
    beat_type: Mapped[str] = mapped_column(String(24))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_outline_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ModelConfig(Base, TimestampMixin):
    """Workspace or novel-scoped LLM config (AgentScope/OpenCode compatible).

    novel_id is null for workspace library models; novel create clones into
    novel-scoped rows with role assignments.
    """

    __tablename__ = "model_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="untested")
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # temperature / top_p stored as percent (0.7 -> 70, 1.0 -> 100)
    temperature: Mapped[int] = mapped_column(Integer, default=70)
    top_p: Mapped[int] = mapped_column(Integer, default=100)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=8192)
    context_size: Mapped[int] = mapped_column(Integer, default=128000)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=120000)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # OpenCode-style options bag + AgentScope extra_body passthrough
    extra_body: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditConfig(Base, TimestampMixin):
    __tablename__ = "audit_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pass_score: Mapped[int] = mapped_column(Integer, default=85)
    revise_score: Mapped[int] = mapped_column(Integer, default=70)
    max_rewrite_attempts: Mapped[int] = mapped_column(Integer, default=1)
    auto_audit: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_revise: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_rewrite: Mapped[bool] = mapped_column(Boolean, default=True)
    fatal_issue_force_rewrite: Mapped[bool] = mapped_column(Boolean, default=True)
    rubric_version: Mapped[int] = mapped_column(Integer, default=1)
    dimensions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ChapterAudit(Base, TimestampMixin):
    __tablename__ = "chapter_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(String(64), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("chapter_versions.id"), index=True)
    rubric_version: Mapped[int] = mapped_column(Integer, default=1)
    total_score: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(24))
    dimension_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    fatal_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    strengths: Mapped[list[str]] = mapped_column(JSON, default=list)
    rewrite_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MemoryChunk(Base, TimestampMixin):
    __tablename__ = "memory_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("chapter_versions.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding_model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    __table_args__ = (UniqueConstraint("version_id", "chunk_index"),)


class NarrativeSummary(Base, TimestampMixin):
    """Deterministic chapter/arc/volume memory with provenance."""

    __tablename__ = "narrative_summaries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    scope_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    start_chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    end_chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    canonical_facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    open_loops: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    entity_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_chapter_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("novel_id", "scope_type", "scope_id"),)


class GenerationJob(Base, TimestampMixin):
    __tablename__ = "generation_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(String(64), index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(24), default="PENDING")
    stage: Mapped[str] = mapped_column(String(100), default="等待开始")
    base_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(240), unique=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    allowed_agents: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SkillRun(Base, TimestampMixin):
    __tablename__ = "skill_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    novel_id: Mapped[str] = mapped_column(String(64), index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    skill_id: Mapped[str] = mapped_column(String(36), index=True)
    skill_name: Mapped[str] = mapped_column(String(120))
    skill_version: Mapped[str] = mapped_column(String(40), default="")
    agent_name: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), default="ok")
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentCallLog(Base, TimestampMixin):
    """Lightweight observability for Writer/Auditor/Plot/Memory/Style/Outline calls."""

    __tablename__ = "agent_call_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True, default="local")
    novel_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(80), default="")
    model_name: Mapped[str] = mapped_column(String(160), default="")
    operation: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), default="ok")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
