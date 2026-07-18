from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class NovelCreate(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    genre: str = "未分类"
    language: str = "zh-CN"
    core_idea: str = ""
    target_words: int = Field(default=200000, ge=1000)
    planned_chapters: int = Field(default=80, ge=1, le=5000)
    creation_mode: str = "scratch"
    auto_audit: bool = True
    auto_bootstrap: bool = False
    writing_profile: dict[str, Any] = Field(default_factory=dict)
    # Workspace model library ids (cloned into the new novel)
    default_model_id: str | None = None
    plan_model_id: str | None = None
    write_model_id: str | None = None
    audit_model_id: str | None = None


class NovelUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    genre: str | None = None
    core_idea: str | None = None
    target_words: int | None = Field(default=None, ge=1000)
    planned_chapters: int | None = Field(default=None, ge=1, le=5000)
    language: str | None = None
    narrative_pov: str | None = None
    tense: str | None = None
    style: str | None = None
    writing_profile: dict[str, Any] | None = None
    archived: bool | None = None


class ChapterUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    content: str
    base_version_id: str | None = None
    source: str = "user"
    locked_ranges: list[dict[str, Any]] = Field(default_factory=list)


class ChapterCreate(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    target_words: int = Field(default=3500, ge=100, le=30000)
    brief: dict[str, Any] = Field(default_factory=dict)


class ChapterMetaUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    target_words: int | None = Field(default=None, ge=100, le=30000)
    brief: dict[str, Any] | None = None


class GenerateRequest(ApiModel):
    base_version_id: str | None = None
    target_words: int = Field(default=3500, ge=100, le=30000)
    pace: str = "均衡"
    dialogue_ratio: int = Field(default=35, ge=0, le=100)
    style_instruction: str = ""
    goal: str = ""
    must_preserve: list[str] = Field(default_factory=list)
    must_improve: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    auto_audit: bool = True


class SelectionEditRequest(ApiModel):
    operation: str = Field(
        description="expand | shrink | rewrite | dialogue | style"
    )
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    selected_text: str = Field(min_length=1)
    content: str = Field(description="Current editor full content for range validation")
    instruction: str = ""
    base_version_id: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "SelectionEditRequest":
        allowed = {"expand", "shrink", "rewrite", "dialogue", "style"}
        if self.operation not in allowed:
            raise ValueError(f"operation must be one of {sorted(allowed)}")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.end > len(self.content):
            raise ValueError("selection end exceeds content length")
        slice_text = self.content[self.start : self.end]
        if slice_text != self.selected_text:
            # Tolerate minor whitespace drift on edges.
            if slice_text.strip() != self.selected_text.strip():
                raise ValueError("selected_text does not match content[start:end]")
        return self


class RestoreRequest(ApiModel):
    current_content: str | None = None


class ConfirmRequest(ApiModel):
    fatal_override_reason: str | None = Field(default=None, min_length=8)
    gate_override_reason: str | None = Field(default=None, min_length=8)


class AuditRequest(ApiModel):
    """Optional target version; defaults to the chapter's current version."""

    version_id: str | None = None


class WritingPatternCreate(ApiModel):
    pattern_type: str = Field(
        default="other",
        pattern="^(hook|pacing|dialogue|payoff|emotion|format|other)$",
    )
    description: str = Field(min_length=3, max_length=1000)
    importance: str = Field(default="medium", pattern="^(high|medium|low)$")


class AuditConfigUpdate(ApiModel):
    enabled: bool = True
    pass_score: int = Field(default=85, ge=0, le=100)
    revise_score: int = Field(default=70, ge=0, le=100)
    max_rewrite_attempts: int = Field(default=1, ge=0, le=1)
    auto_audit: bool = True
    auto_revise: bool = True
    auto_rewrite: bool = True
    fatal_issue_force_rewrite: bool = True
    dimensions: list[dict[str, Any]]

    @model_validator(mode="after")
    def validate_scores(self) -> "AuditConfigUpdate":
        if self.revise_score > self.pass_score:
            raise ValueError("revise_score cannot exceed pass_score")
        if sum(int(item.get("max", 0)) for item in self.dimensions) != 100:
            raise ValueError("audit dimension weights must sum to 100")
        return self


class OutlineUpdate(ApiModel):
    title: str | None = None
    position: int | None = None
    locked: bool | None = None
    details: dict[str, Any] | None = None


class BlueprintCommitRequest(ApiModel):
    preview_id: str | None = None
    blueprint: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "BlueprintCommitRequest":
        if not self.preview_id and self.blueprint is None:
            raise ValueError("preview_id or blueprint is required")
        return self


class OutlineGenerateRequest(ApiModel):
    parent_id: str | None = None
    child_kind: str | None = Field(
        default=None,
        description="volume|arc|chapter|scene; default inferred from parent",
    )
    count: int = Field(default=3, ge=1, le=200)
    create_chapters: bool = True


class OutlinePreviewRequest(ApiModel):
    parent_id: str | None = None
    child_kind: str | None = None
    count: int = Field(default=10, ge=0, le=200)
    create_chapters: bool = True
    mode: str = Field(
        default="batch_chapters",
        description="batch_chapters | children | master_outline",
    )
    run_coherence: bool = True
    prior_drafts: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    chapter_offset: int = Field(default=0, ge=0, le=200)


class OutlineMasterPreviewRequest(ApiModel):
    # `chapter_count` is retained for clients that shipped before the
    # blueprint-first wizard. New clients should let the service derive the
    # volume count from the book length or provide `volume_count`.
    chapter_count: int | None = Field(default=None, ge=1, le=30)
    volume_count: int | None = Field(default=None, ge=1, le=12)
    run_coherence: bool = True


class OutlineMasterEnrichRequest(ApiModel):
    index: int = Field(ge=0, le=11)


class OutlineCommitRequest(ApiModel):
    preview_id: str = Field(min_length=1)
    nodes: list[dict[str, Any]] | None = None


class OutlineRegenerateRequest(ApiModel):
    node_id: str = Field(min_length=1)
    run_coherence: bool = True


class OutlineMoveRequest(ApiModel):
    direction: str = Field(description="up | down")

    @model_validator(mode="after")
    def validate_direction(self) -> "OutlineMoveRequest":
        if self.direction not in {"up", "down"}:
            raise ValueError("direction must be up or down")
        return self


class ImportManuscriptRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    genre: str = "导入"
    core_idea: str = ""
    confirm_all: bool = False
    default_model_id: str | None = None


class RelationsUpdate(ApiModel):
    relations: list[dict[str, Any]] = Field(default_factory=list)


class EntityCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    locked_fields: list[str] = Field(default_factory=list)


class EntityUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = None
    data: dict[str, Any] | None = None
    locked_fields: list[str] | None = None


class RuleCreate(ApiModel):
    rule: str = Field(min_length=1)
    rule_type: str = "世界设定"
    importance: str = "中"
    locked: bool = False


class RuleUpdate(ApiModel):
    rule: str | None = Field(default=None, min_length=1)
    rule_type: str | None = None
    importance: str | None = None
    locked: bool | None = None


class PlotThreadCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "foreshadowing"
    status: str = "PLANTED"
    planted: str = ""
    payoff: str = ""
    importance: str = "中"
    latest: str = ""


class PlotThreadUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = None
    status: str | None = None
    planted: str | None = None
    payoff: str | None = None
    importance: str | None = None
    latest: str | None = None


class ModelConfigCreate(ApiModel):
    """OpenAI-compatible model definition (AgentScope OpenAIChatModel + OpenCode options)."""

    name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    base_url: str = ""
    api_key: str = ""
    roles: list[str] = Field(default_factory=list)
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)
    max_output_tokens: int = Field(default=8192, ge=128, le=131072)
    context_size: int = Field(default=128000, ge=1024, le=2_000_000)
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    is_default: bool = False
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ModelConfigUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    provider: str | None = None
    model_id: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    roles: list[str] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_output_tokens: int | None = Field(default=None, ge=128, le=131072)
    context_size: int | None = Field(default=None, ge=1024, le=2_000_000)
    timeout_ms: int | None = Field(default=None, ge=1000, le=600000)
    is_default: bool | None = None
    extra_body: dict[str, Any] | None = None


class ModelProbeRequest(ApiModel):
    """Probe an OpenAI-compatible endpoint before saving the config."""

    provider: str = Field(default="OpenAI 兼容", max_length=80)
    base_url: str = ""
    api_key: str = ""
    model_id: str = ""
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)


class EmbeddingLocalDownloadRequest(ApiModel):
    catalog_key: str = Field(min_length=1, max_length=80)


class EmbeddingCloudCreate(ApiModel):
    """Minimal cloud embedding endpoint for the Roles tab."""

    name: str = Field(default="", max_length=160)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = ""
    model_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(default="OpenAI 兼容", max_length=80)


class SkillUpdate(ApiModel):
    enabled: bool | None = None
    allowed_agents: list[str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


class SkillImport(ApiModel):
    """A user-owned, prompt-only SKILL.md import. Executable files are never accepted."""

    content: str = Field(min_length=1, max_length=100000)


class AccountDeleteRequest(ApiModel):
    confirmation: str = Field(min_length=1, max_length=32)
