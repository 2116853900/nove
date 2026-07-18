from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditConfig,
    Chapter,
    ChapterAudit,
    ChapterVersion,
    GenerationJob,
    ModelConfig,
    Novel,
    NovelRule,
    OutlineNode,
    PlotThread,
    Skill,
    StoryBeat,
    StoryEntity,
    StoryEvent,
)
from .craft import normalize_writing_profile, profile_readiness


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def chapter_status(
    chapter: Chapter, has_fatal: bool = False, pass_score: int = 85
) -> str:
    if chapter.state == "CONFIRMED":
        return "confirmed"
    if has_fatal:
        return "fatal"
    if chapter.latest_score is not None and chapter.latest_score >= pass_score:
        return "pass"
    if chapter.latest_score is not None:
        return "revise"
    if chapter.memory_status == "PENDING":
        return "memory-pending"
    return "unaudited"


def version_dict(version: ChapterVersion, current_id: str | None = None) -> dict[str, Any]:
    return {
        "id": version.id,
        "label": f"v{version.sequence}",
        "source": version.source,
        "model": version.model_name,
        "score": version.audit_score,
        "time": iso(version.created_at),
        "words": len(version.content),
        "current": version.id == current_id,
        "title": version.title,
        "content": version.content,
        "baseVersionId": version.base_version_id,
        "lockedRanges": version.locked_ranges,
    }


def chapter_dict(session: Session, chapter: Chapter, include_content: bool = False) -> dict[str, Any]:
    current = session.get(ChapterVersion, chapter.current_version_id) if chapter.current_version_id else None
    latest_audit = session.scalar(
        select(ChapterAudit)
        .where(ChapterAudit.chapter_id == chapter.id)
        .order_by(ChapterAudit.created_at.desc())
    )
    audit_config = session.scalar(
        select(AuditConfig).where(AuditConfig.novel_id == chapter.novel_id)
    )
    result = {
        "id": chapter.id,
        "novelId": chapter.novel_id,
        "index": chapter.chapter_index,
        "title": chapter.title,
        "outlineNodeId": chapter.outline_node_id,
        "words": len(current.content) if current else 0,
        "score": chapter.latest_score,
        "status": chapter_status(
            chapter,
            bool(latest_audit and latest_audit.fatal_issues),
            audit_config.pass_score if audit_config else 85,
        ),
        "state": chapter.state,
        "needsCheck": chapter.needs_check,
        "memoryStatus": chapter.memory_status,
        "targetWords": chapter.target_words,
        "brief": chapter.brief,
        "currentVersionId": chapter.current_version_id,
        "confirmedVersionId": chapter.confirmed_version_id,
        "updatedAt": iso(chapter.updated_at),
    }
    if include_content:
        result["content"] = current.content if current else ""
        result["lockedRanges"] = current.locked_ranges if current else []
    return result


def novel_dict(session: Session, novel: Novel) -> dict[str, Any]:
    chapters = session.scalars(
        select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.chapter_index)
    ).all()
    words = 0
    pending = 0
    confirmed = 0
    for chapter in chapters:
        if chapter.current_version_id:
            version = session.get(ChapterVersion, chapter.current_version_id)
            words += len(version.content) if version else 0
        if chapter.state == "CONFIRMED":
            confirmed += 1
        if chapter.state in {"REVIEW_REQUIRED", "AUDITING", "OUTDATED"}:
            pending += 1
    return {
        "id": novel.id,
        "title": novel.title,
        "genre": novel.genre,
        "language": novel.language,
        "coreIdea": novel.core_idea,
        "targetWords": novel.target_words,
        "plannedChapters": novel.planned_chapters,
        "writingProfile": normalize_writing_profile(novel.writing_profile),
        "writingProfileReadiness": profile_readiness(novel.writing_profile),
        "progress": {"done": confirmed, "total": novel.planned_chapters},
        "words": words,
        "pendingAudits": pending,
        "updatedLabel": iso(novel.updated_at),
        "archived": novel.archived,
    }


def outline_tree(nodes: list[OutlineNode]) -> list[dict[str, Any]]:
    children: dict[str | None, list[OutlineNode]] = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    for group in children.values():
        group.sort(key=lambda item: item.position)

    def build(node: OutlineNode) -> dict[str, Any]:
        result = {
            "id": node.id,
            "kind": node.kind,
            "title": node.title,
            "locked": node.locked,
            "details": node.details,
        }
        descendants = children.get(node.id, [])
        if descendants:
            result["children"] = [build(item) for item in descendants]
        return result

    return [build(node) for node in children.get(None, [])]


def entity_dict(entity: StoryEntity) -> dict[str, Any]:
    base = {"id": entity.id, "name": entity.name, **entity.data}
    base.setdefault("summary", entity.summary)
    base.setdefault("locked", bool(entity.locked_fields))
    return base


def event_dict(event: StoryEvent, chapter_label: str = "") -> dict[str, Any]:
    return {
        "id": event.id,
        "storyTime": event.story_time,
        "chapter": chapter_label,
        "subjects": " · ".join(event.subjects),
        "action": event.action,
        "location": event.location,
        "consequence": event.consequences,
    }


def plot_thread_dict(thread: PlotThread) -> dict[str, Any]:
    return {
        "id": thread.id,
        "name": thread.name,
        "kind": thread.kind,
        "status": thread.status.lower(),
        "planted": thread.planted,
        "payoff": thread.payoff,
        "importance": thread.importance,
        "latest": thread.latest,
    }


def beat_dict(beat: StoryBeat) -> dict[str, Any]:
    return {"id": beat.id, "chapter": beat.chapter_label, **beat.data}


def audit_dict(audit: ChapterAudit, content: str = "") -> dict[str, Any]:
    issues = audit.issues
    fatal_issues = audit.fatal_issues
    if content:
        from .agents.auditor import attach_evidence_metadata

        issues = [attach_evidence_metadata(item, content) for item in (issues or [])]
        fatal_issues = [
            attach_evidence_metadata(item, content) for item in (fatal_issues or [])
        ]
    return {
        "id": audit.id,
        "chapterId": audit.chapter_id,
        "versionId": audit.version_id,
        "totalScore": audit.total_score,
        "decision": audit.decision,
        "dimensions": audit.dimension_scores,
        "fatalIssues": fatal_issues,
        "issues": issues,
        "strengths": audit.strengths,
        "rewriteRequirements": audit.rewrite_requirements,
        "createdAt": iso(audit.created_at),
    }


def model_dict(model: ModelConfig) -> dict[str, Any]:
    top_p = getattr(model, "top_p", 100) or 100
    return {
        "id": model.id,
        "name": model.name,
        "provider": model.provider,
        "modelId": model.model_id,
        "baseUrl": model.base_url,
        "apiKeyMasked": "********" if model.encrypted_api_key else "",
        "status": model.status,
        "roles": model.roles or [],
        "latency": f"{model.latency_ms / 1000:.1f}s" if model.latency_ms else "—",
        "temperature": (model.temperature or 0) / 100,
        "topP": top_p / 100,
        "maxOutputTokens": model.max_output_tokens,
        "contextSize": getattr(model, "context_size", 128000) or 128000,
        "timeoutMs": getattr(model, "timeout_ms", 120000) or 120000,
        "isDefault": bool(getattr(model, "is_default", False)),
        "extraBody": getattr(model, "extra_body", None) or {},
        "novelId": model.novel_id,
        "scope": "novel" if model.novel_id else "workspace",
    }


def audit_config_dict(config: AuditConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "enabled": config.enabled,
        "passScore": config.pass_score,
        "reviseScore": config.revise_score,
        "maxRewriteAttempts": min(1, config.max_rewrite_attempts),
        "autoAudit": config.auto_audit,
        "autoRevise": config.auto_revise,
        "autoRewrite": config.auto_rewrite,
        "fatalIssueForceRewrite": config.fatal_issue_force_rewrite,
        "rubricVersion": config.rubric_version,
        "dimensions": config.dimensions,
    }


def job_dict(job: GenerationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "novelId": job.novel_id,
        "chapterId": job.chapter_id,
        "type": job.job_type,
        "state": job.state,
        "stage": job.stage,
        "baseVersionId": job.base_version_id,
        "cancelRequested": job.cancel_requested,
        "events": job.events,
        "result": job.result,
        "error": job.error,
        "createdAt": iso(job.created_at),
        "updatedAt": iso(job.updated_at),
    }


def rule_dict(rule: NovelRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "rule": rule.rule,
        "type": rule.rule_type,
        "importance": rule.importance,
        "since": "项目设定",
        "locked": rule.locked,
        "violations": rule.violations,
    }


def skill_dict(skill: Skill) -> dict[str, Any]:
    schema = skill.input_schema or {}
    is_system = schema.get("x-nove-origin") == "system"
    return {
        "id": skill.id,
        "name": skill.name,
        "version": skill.version,
        "description": skill.description,
        "allowedAgents": skill.allowed_agents,
        "timeoutSeconds": skill.timeout_seconds,
        "enabled": skill.enabled,
        "isSystem": is_system,
        "kind": "runtime" if is_system else "prompt",
    }
