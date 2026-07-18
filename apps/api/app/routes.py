from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx
from urllib.parse import urlparse
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import AuthContext, get_auth_context, get_current_workspace, require_workspace_id
from . import db as db_module
from .db import SessionLocal, get_session
from .domain import VersionConflictError
from .craft import (
    CKSKILL_RULESET_VERSION,
    RULE_PROVENANCE,
    normalize_writing_profile,
    profile_readiness,
)
from .job_limiter import acquire_job_slot, active_jobs
from .models import (
    AuditConfig,
    Chapter,
    ChapterAudit,
    ChapterVersion,
    GenerationJob,
    MemoryChunk,
    ModelConfig,
    Novel,
    NovelRule,
    OutlineNode,
    PlotThread,
    Skill,
    StoryBeat,
    StoryEntity,
    StoryEvent,
    Workspace,
)
from .presenters import (
    audit_config_dict,
    audit_dict,
    beat_dict,
    chapter_dict,
    entity_dict,
    event_dict,
    job_dict,
    model_dict,
    novel_dict,
    outline_tree,
    plot_thread_dict,
    rule_dict,
    skill_dict,
    version_dict,
)
from .repositories import SqlAlchemyRepository
from .schemas import (
    AuditConfigUpdate,
    AuditRequest,
    AccountDeleteRequest,
    ChapterUpdate,
    ChapterCreate,
    ChapterMetaUpdate,
    ConfirmRequest,
    EmbeddingCloudCreate,
    EmbeddingLocalDownloadRequest,
    EntityCreate,
    EntityUpdate,
    GenerateRequest,
    ModelConfigCreate,
    ModelConfigUpdate,
    BlueprintCommitRequest,
    ModelProbeRequest,
    NovelCreate,
    NovelUpdate,
    ImportManuscriptRequest,
    OutlineCommitRequest,
    OutlineGenerateRequest,
    OutlineMasterPreviewRequest,
    OutlineMasterEnrichRequest,
    OutlineMoveRequest,
    OutlinePreviewRequest,
    OutlineRegenerateRequest,
    OutlineUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
    RelationsUpdate,
    RestoreRequest,
    RuleCreate,
    RuleUpdate,
    SelectionEditRequest,
    SkillImport,
    SkillUpdate,
    WritingPatternCreate,
)
from .security import decrypt_secret, encrypt_secret
from .services import (
    AuditService,
    ChapterService,
    GenerationService,
    MemoryService,
    SelectionEditService,
    WritingPolicyService,
)
from .services_blueprint import BlueprintService
from .services_bootstrap import NovelBootstrapService, run_novel_bootstrap
from .services_outline import OutlineService


router = APIRouter(prefix="/api", dependencies=[Depends(get_auth_context)])


def run_generation(job_id: str, auto_audit: bool) -> None:
    with acquire_job_slot(timeout=300) as ok:
        if not ok:
            with SessionLocal() as session:
                job = session.get(GenerationJob, job_id)
                if job is not None:
                    job.state = "FAILED"
                    job.error = "Generation slot unavailable"
                    job.stage = "排队失败"
                    chapter = session.get(Chapter, job.chapter_id) if job.chapter_id else None
                    if chapter is not None:
                        chapter.state = "DRAFT" if chapter.current_version_id else "PLANNED"
                    session.commit()
            return
        with SessionLocal() as session:
            GenerationService(session).run_job(job_id, auto_audit=auto_audit)


@router.get("/auth/status")
def auth_status(auth: AuthContext = Depends(get_auth_context)):
    return {
        "authenticated": auth.auth_mode != "dev" or True,
        "mode": auth.auth_mode,
        "workspaceId": auth.workspace_id,
        "apiKeyRequired": bool(
            __import__("app.config", fromlist=["settings"]).settings.api_key
        ),
        "activeJobs": active_jobs(),
    }


@router.get("/novels")
def list_novels(session: Session = Depends(get_session)):
    novels = SqlAlchemyRepository(session).list_novels()
    return [novel_dict(session, novel) for novel in novels]


@router.post("/novels/import", status_code=201)
def import_novel(
    payload: ImportManuscriptRequest,
    session: Session = Depends(get_session),
    workspace: Workspace = Depends(get_current_workspace),
):
    from .import_export import ImportExportService

    try:
        result = ImportExportService(session).import_text(
            title=payload.title,
            text=payload.text,
            genre=payload.genre,
            core_idea=payload.core_idea,
            confirm_all=payload.confirm_all,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # import_text commits; attach workspace models onto the new novel.
    _attach_models_to_novel(
        session,
        workspace_id=workspace.id,
        novel_id=result["novelId"],
        default_model_id=payload.default_model_id,
        plan_model_id=payload.default_model_id,
        write_model_id=payload.default_model_id,
        audit_model_id=payload.default_model_id,
    )
    session.commit()
    novel = SqlAlchemyRepository(session).get_novel(result["novelId"])
    return {"import": result, "novel": novel_dict(session, novel)}


@router.get("/novels/{novel_id}/export")
def export_novel(
    novel_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|txt|json)$"),
    include_bible: bool = False,
    session: Session = Depends(get_session),
):
    from .import_export import ImportExportService

    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    service = ImportExportService(session)
    if format == "json":
        return service.export_json_meta(novel)

    def content_disposition(ext: str) -> str:
        # HTTP headers must be latin-1; use ASCII fallback + RFC 5987 filename*.
        safe = re.sub(r"[^\w\-.]+", "_", novel.title, flags=re.UNICODE).strip("._") or "nove"
        safe_ascii = safe.encode("ascii", "ignore").decode("ascii") or "nove"
        from urllib.parse import quote

        starred = quote(f"{novel.title}.{ext}", safe="")
        return f"attachment; filename=\"{safe_ascii}.{ext}\"; filename*=UTF-8''{starred}"

    if format == "txt":
        body = service.export_txt(novel, include_bible=include_bible)
        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": content_disposition("txt")},
        )
    body = service.export_markdown(novel, include_bible=include_bible)
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition("md")},
    )


@router.get("/novels/{novel_id}/relations")
def list_relations(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .services_relations import RelationService

    return RelationService(session).list_for_novel(novel_id)


@router.put("/story-entities/{entity_id}/relations")
def put_relations(
    entity_id: str, payload: RelationsUpdate, session: Session = Depends(get_session)
):
    from .services_relations import RelationService

    try:
        return RelationService(session).set_relations(entity_id, payload.relations)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/audit-scan")
def novel_audit_scan(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .services_relations import NovelAuditService

    return NovelAuditService(session).scan(novel_id)


def _clone_model_for_novel(
    session: Session,
    *,
    source: ModelConfig,
    novel_id: str,
    roles: list[str],
) -> ModelConfig:
    clone = ModelConfig(
        workspace_id=source.workspace_id,
        novel_id=novel_id,
        name=source.name,
        provider=source.provider,
        model_id=source.model_id,
        base_url=source.base_url,
        encrypted_api_key=source.encrypted_api_key,
        status=source.status,
        roles=list(roles),
        latency_ms=source.latency_ms,
        temperature=source.temperature,
        top_p=getattr(source, "top_p", 100) or 100,
        max_output_tokens=source.max_output_tokens,
        context_size=getattr(source, "context_size", 128000) or 128000,
        timeout_ms=getattr(source, "timeout_ms", 120000) or 120000,
        is_default=False,
        extra_body=dict(getattr(source, "extra_body", None) or {}),
    )
    session.add(clone)
    return clone


_LOCAL_TEXT_PROVIDERS = {"本地", "local", "Ollama", "vLLM"}


def _ensure_cloud_text_model(provider: str, base_url: str) -> None:
    normalized_provider = (provider or "").strip()
    if normalized_provider in _LOCAL_TEXT_PROVIDERS:
        raise HTTPException(status_code=422, detail="仅支持云端文本模型。")
    value = (base_url or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="请填写云端模型服务地址。")
    hostname = (urlparse(value).hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise HTTPException(status_code=422, detail="请使用云端模型地址，不能连接本机模型。")


def _is_usable_cloud_model(model: ModelConfig) -> bool:
    try:
        _ensure_cloud_text_model(model.provider, model.base_url)
    except HTTPException:
        return False
    return model.status == "connected"


def _attach_models_to_novel(
    session: Session,
    *,
    workspace_id: str,
    novel_id: str,
    default_model_id: str | None,
    plan_model_id: str | None,
    write_model_id: str | None,
    audit_model_id: str | None,
    required: bool = False,
) -> None:
    library = [
        item
        for item in session.scalars(
        select(ModelConfig).where(
            ModelConfig.workspace_id == workspace_id,
            ModelConfig.novel_id.is_(None),
        )
        ).all()
        if _is_usable_cloud_model(item)
    ]
    by_id = {item.id: item for item in library}
    if not library:
        if required:
            raise ValueError("请先连接并测试一个可用的云端模型。")
        return

    default = by_id.get(default_model_id or "") or next(
        (item for item in library if item.is_default),
        library[0],
    )
    plan = by_id.get(plan_model_id or "") or default
    write = by_id.get(write_model_id or "") or default
    audit = by_id.get(audit_model_id or "") or default

    role_map: dict[str, list[str]] = {}
    for model, roles in (
        (plan, ["大纲"]),
        (write, ["写作", "润色"]),
        (audit, ["审计", "连续性", "记忆提取"]),
    ):
        role_map.setdefault(model.id, [])
        for role in roles:
            if role not in role_map[model.id]:
                role_map[model.id].append(role)

    # Always include default even if only used as fallback label
    role_map.setdefault(default.id, role_map.get(default.id, []))

    for model_id, roles in role_map.items():
        source = by_id[model_id]
        _clone_model_for_novel(session, source=source, novel_id=novel_id, roles=roles)


def _model_from_payload(
    *,
    workspace_id: str,
    novel_id: str | None,
    payload: ModelConfigCreate,
) -> ModelConfig:
    _ensure_cloud_text_model(payload.provider, payload.base_url)
    return ModelConfig(
        workspace_id=workspace_id,
        novel_id=novel_id,
        name=payload.name,
        provider=payload.provider,
        model_id=payload.model_id,
        base_url=payload.base_url,
        encrypted_api_key=encrypt_secret(payload.api_key),
        roles=list(payload.roles or []),
        temperature=round(payload.temperature * 100),
        top_p=round(payload.top_p * 100),
        max_output_tokens=payload.max_output_tokens,
        context_size=payload.context_size,
        timeout_ms=payload.timeout_ms,
        is_default=payload.is_default,
        extra_body=dict(payload.extra_body or {}),
        status="untested",
    )


def _apply_model_update(model: ModelConfig, payload: ModelConfigUpdate) -> None:
    values = payload.model_dump(exclude_unset=True)
    _ensure_cloud_text_model(
        str(values.get("provider", model.provider)),
        str(values.get("base_url", model.base_url)),
    )
    connection_changed = any(
        key in values for key in {"provider", "model_id", "base_url", "api_key"}
    )
    api_key = values.pop("api_key", None)
    temperature = values.pop("temperature", None)
    top_p = values.pop("top_p", None)
    for key, value in values.items():
        setattr(model, key, value)
    if api_key is not None:
        model.encrypted_api_key = encrypt_secret(api_key)
    if temperature is not None:
        model.temperature = round(temperature * 100)
    if top_p is not None:
        model.top_p = round(top_p * 100)
    if connection_changed:
        model.status = "untested"


@router.post("/novels", status_code=201)
def create_novel(
    payload: NovelCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    workspace: Workspace = Depends(get_current_workspace),
):
    novel_fields = payload.model_dump(
        exclude={
            "auto_audit",
            "default_model_id",
            "plan_model_id",
            "write_model_id",
            "audit_model_id",
            "auto_bootstrap",
        }
    )
    novel_fields["writing_profile"] = normalize_writing_profile(
        novel_fields.get("writing_profile")
    )
    novel = Novel(workspace_id=workspace.id, **novel_fields)
    session.add(novel)
    session.flush()
    # Manual creation stays empty; auto-bootstrap fills the outline after commit.
    session.add(AuditConfig(workspace_id=workspace.id, novel_id=novel.id, auto_audit=payload.auto_audit, dimensions=AuditService.DEFAULT_DIMENSIONS))
    try:
        _attach_models_to_novel(
            session,
            workspace_id=workspace.id,
            novel_id=novel.id,
            default_model_id=payload.default_model_id,
            plan_model_id=payload.plan_model_id,
            write_model_id=payload.write_model_id,
            audit_model_id=payload.audit_model_id,
            required=payload.auto_bootstrap,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    if payload.auto_bootstrap:
        bootstrap = NovelBootstrapService(session)
        bootstrap.queue(novel)
        background_tasks.add_task(run_novel_bootstrap, novel.id)
    return novel_dict(session, novel)


@router.get("/novels/{novel_id}")
def get_novel(novel_id: str, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    return novel_dict(session, novel)


@router.get("/novels/{novel_id}/bootstrap")
def get_novel_bootstrap(novel_id: str, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    return NovelBootstrapService(session).status(novel)


@router.post("/novels/{novel_id}/bootstrap/retry", status_code=202)
def retry_novel_bootstrap(
    novel_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    service = NovelBootstrapService(session)
    current = service.status(novel)
    if current["status"] == "running":
        raise HTTPException(status_code=409, detail="故事仍在搭建中")
    if current["status"] == "complete":
        return current
    service.queue(novel)
    background_tasks.add_task(run_novel_bootstrap, novel.id)
    return service.status(novel)


@router.get("/novels/{novel_id}/writing-health")
def get_writing_health(novel_id: str, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    chapters = session.scalars(
        select(Chapter)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_index)
    ).all()
    blocked: list[dict[str, Any]] = []
    unaudited = 0
    non_passing = 0
    memory_pending = 0
    for chapter in chapters:
        contract = WritingPolicyService(session).contract(chapter)
        if not contract["ready"]:
            blocked.append(
                {
                    "chapterId": chapter.id,
                    "chapterIndex": chapter.chapter_index,
                    "title": chapter.title,
                    "blockers": contract["gate"]["blockers"],
                }
            )
        if chapter.current_version_id:
            audit = session.scalar(
                select(ChapterAudit)
                .where(
                    ChapterAudit.chapter_id == chapter.id,
                    ChapterAudit.version_id == chapter.current_version_id,
                )
                .order_by(ChapterAudit.created_at.desc())
            )
            if audit is None:
                unaudited += 1
            elif audit.decision != "PASS":
                non_passing += 1
        if chapter.memory_status == "PENDING":
            memory_pending += 1
    readiness = profile_readiness(novel.writing_profile)
    profile_ok = readiness["ready"] or not readiness["strict"]
    return {
        "ruleset": CKSKILL_RULESET_VERSION,
        "profile": readiness,
        "chapters": len(chapters),
        "blockedChapters": blocked,
        "unauditedVersions": unaudited,
        "nonPassingAudits": non_passing,
        "memoryPending": memory_pending,
        "healthy": profile_ok and not blocked and not unaudited and not non_passing and not memory_pending,
        "provenance": RULE_PROVENANCE,
    }


@router.post("/novels/{novel_id}/writing-patterns", status_code=201)
def add_writing_pattern(
    novel_id: str,
    payload: WritingPatternCreate,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    profile = normalize_writing_profile(novel.writing_profile)
    learned = list(profile["learned_patterns"])
    value = f"[{payload.pattern_type}/{payload.importance}] {payload.description.strip()}"
    if value not in learned:
        learned.append(value)
    profile["learned_patterns"] = learned[-20:]
    novel.writing_profile = profile
    session.commit()
    return {"status": "success", "learned": value, "writingProfile": profile}


@router.patch("/novels/{novel_id}")
def update_novel(novel_id: str, payload: NovelUpdate, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "writing_profile":
            value = normalize_writing_profile(value)
        setattr(novel, key, value)
    session.commit()
    return novel_dict(session, novel)


@router.delete("/novels/{novel_id}", status_code=204)
def delete_novel(novel_id: str, session: Session = Depends(get_session)):
    from .services_novel import delete_novel_cascade

    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    delete_novel_cascade(session, novel)
    session.commit()


@router.delete("/account", status_code=204)
def delete_account(
    payload: AccountDeleteRequest,
    auth: AuthContext = Depends(get_auth_context),
    session: Session = Depends(get_session),
):
    if payload.confirmation != "DELETE":
        raise HTTPException(status_code=400, detail="请输入 DELETE 以确认删除账号")
    from .models import AgentCallLog, ModelConfig, Skill, SkillRun
    from .services_novel import delete_novel_cascade

    novels = session.scalars(select(Novel).where(Novel.workspace_id == auth.workspace_id)).all()
    for novel in novels:
        delete_novel_cascade(session, novel)
    for model in [AgentCallLog, SkillRun, ModelConfig, Skill]:
        session.query(model).filter(model.workspace_id == auth.workspace_id).delete(
            synchronize_session=False
        )
    workspace = session.get(Workspace, auth.workspace_id)
    if workspace is not None:
        session.delete(workspace)
    session.commit()


@router.get("/novels/{novel_id}/chapters")
def list_chapters(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    chapters = session.scalars(select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_index)).all()
    return [chapter_dict(session, chapter) for chapter in chapters]


@router.post("/novels/{novel_id}/chapters", status_code=201)
def create_chapter(novel_id: str, payload: ChapterCreate, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    highest = session.scalar(select(Chapter.chapter_index).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_index.desc())) or 0
    parent = session.scalar(select(OutlineNode).where(OutlineNode.novel_id == novel_id, OutlineNode.kind == "arc").order_by(OutlineNode.position))
    node = OutlineNode(
        workspace_id=novel.workspace_id,
        novel_id=novel.id,
        parent_id=parent.id if parent else None,
        kind="chapter",
        title=f"第 {highest + 1} 章 · {payload.title}",
        position=highest + 1,
        details=payload.brief,
    )
    session.add(node)
    session.flush()
    chapter = Chapter(
        workspace_id=novel.workspace_id,
        novel_id=novel.id,
        outline_node_id=node.id,
        chapter_index=highest + 1,
        title=payload.title,
        target_words=payload.target_words,
        brief=payload.brief,
    )
    session.add(chapter)
    session.commit()
    return chapter_dict(session, chapter, include_content=True)


@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: str, session: Session = Depends(get_session)):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    return chapter_dict(session, chapter, include_content=True)


@router.get("/chapters/{chapter_id}/writing-contract")
def get_writing_contract(
    chapter_id: str, session: Session = Depends(get_session)
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    return WritingPolicyService(session).contract(chapter)


@router.patch("/chapters/{chapter_id}")
def save_chapter(chapter_id: str, payload: ChapterUpdate, session: Session = Depends(get_session)):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    try:
        version = ChapterService(session).create_version(
            chapter, content=payload.content, title=payload.title, source=payload.source,
            base_version_id=payload.base_version_id, locked_ranges=payload.locked_ranges,
        )
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"chapter": chapter_dict(session, chapter, include_content=True), "version": version_dict(version, chapter.current_version_id)}


@router.patch("/chapters/{chapter_id}/meta")
def update_chapter_meta(chapter_id: str, payload: ChapterMetaUpdate, session: Session = Depends(get_session)):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(chapter, key, value)
    if chapter.outline_node_id:
        node = session.get(OutlineNode, chapter.outline_node_id)
        if node:
            if payload.title is not None:
                node.title = f"第 {chapter.chapter_index} 章 · {payload.title}"
            if payload.brief is not None:
                node.details = payload.brief
    session.commit()
    return chapter_dict(session, chapter, include_content=True)


def queue_generation(
    chapter_id: str,
    payload: GenerateRequest,
    operation: str,
    background: BackgroundTasks,
    session: Session,
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    from .agents.models import model_config_for_role

    if model_config_for_role(session, chapter.novel_id, "写作") is None:
        raise HTTPException(
            status_code=409,
            detail="请先为本项目连接并测试云端写作模型。",
        )
    if payload.base_version_id != chapter.current_version_id:
        raise HTTPException(status_code=409, detail="Generation base version is stale")
    contract = WritingPolicyService(session).contract(
        chapter,
        overrides=payload.model_dump(exclude={"base_version_id", "auto_audit"}),
    )
    if contract["gate"]["status"] != "pass":
        try:
            OutlineService(session).complete_chapter_contract(
                chapter,
                overrides=payload.model_dump(exclude={"base_version_id", "auto_audit"}),
            )
            contract = WritingPolicyService(session).contract(
                chapter,
                overrides=payload.model_dump(exclude={"base_version_id", "auto_audit"}),
            )
        except Exception:
            session.rollback()
            chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
            contract = WritingPolicyService(session).contract(
                chapter,
                overrides=payload.model_dump(exclude={"base_version_id", "auto_audit"}),
            )
    if not contract["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "写前门禁未通过："
                + "；".join(item["message"] for item in contract["gate"]["blockers"]),
                "gate": contract["gate"],
            },
        )
    job = GenerationService(session).create_job(
        chapter,
        payload.base_version_id,
        operation,
        options=payload.model_dump(exclude={"base_version_id", "auto_audit"}),
    )
    if job.state == "PENDING":
        background.add_task(run_generation, job.id, payload.auto_audit)
    result = job_dict(job)
    result["activeJobs"] = active_jobs()
    return result


@router.post("/chapters/{chapter_id}/generate", status_code=202)
def generate_chapter(
    chapter_id: str,
    payload: GenerateRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    return queue_generation(chapter_id, payload, "GENERATE_CHAPTER", background, session)


@router.post("/chapters/{chapter_id}/continue", status_code=202)
def continue_chapter(
    chapter_id: str,
    payload: GenerateRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    return queue_generation(chapter_id, payload, "CONTINUE_CHAPTER", background, session)


@router.post("/chapters/{chapter_id}/rewrite", status_code=202)
def rewrite_chapter(
    chapter_id: str,
    payload: GenerateRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    return queue_generation(chapter_id, payload, "REWRITE_CHAPTER", background, session)


@router.post("/chapters/{chapter_id}/audit-and-rewrite", status_code=202)
def audit_and_rewrite_chapter(
    chapter_id: str,
    payload: GenerateRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    return queue_generation(chapter_id, payload, "AUDIT_AND_REWRITE", background, session)


@router.post("/chapters/{chapter_id}/audit")
def audit_chapter(
    chapter_id: str,
    payload: AuditRequest | None = None,
    session: Session = Depends(get_session),
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    repo = SqlAlchemyRepository(session)
    target_version_id = (payload.version_id if payload else None) or chapter.current_version_id
    if not target_version_id:
        raise HTTPException(
            status_code=409,
            detail="当前章节还没有正文，无法审计。请先接受 AI 候选，或指定 version_id。",
        )
    version = repo.get_version(target_version_id)
    if version.chapter_id != chapter.id:
        raise HTTPException(status_code=404, detail="版本不属于该章节")
    if not version.content.strip():
        raise HTTPException(status_code=409, detail="目标版本正文为空，无法审计")
    # Only promote chapter score/state when auditing the current formal version.
    update_chapter = version.id == chapter.current_version_id
    return audit_dict(
        AuditService(session).audit(chapter, version, update_chapter=update_chapter),
        version.content,
    )


@router.post("/chapters/{chapter_id}/versions/{version_id}/audit")
def audit_version(
    chapter_id: str,
    version_id: str,
    session: Session = Depends(get_session),
):
    return audit_chapter(
        chapter_id,
        payload=AuditRequest(version_id=version_id),
        session=session,
    )


@router.post("/chapters/{chapter_id}/selection-edit")
def selection_edit(
    chapter_id: str,
    payload: SelectionEditRequest,
    session: Session = Depends(get_session),
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    if (
        payload.base_version_id is not None
        and payload.base_version_id != chapter.current_version_id
    ):
        raise HTTPException(status_code=409, detail="Selection edit base version is stale")
    try:
        return SelectionEditService(session).edit(
            chapter,
            operation=payload.operation,
            start=payload.start,
            end=payload.end,
            selected_text=payload.selected_text,
            content=payload.content,
            instruction=payload.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chapters/{chapter_id}/confirm")
def confirm_chapter(chapter_id: str, payload: ConfirmRequest | None = None, session: Session = Depends(get_session)):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    if not chapter.current_version_id:
        raise HTTPException(status_code=409, detail="Chapter has no version to confirm")
    if (
        chapter.confirmed_version_id == chapter.current_version_id
        and chapter.state == "CONFIRMED"
    ):
        return chapter_dict(session, chapter, include_content=True)
    latest_audit = session.scalar(
        select(ChapterAudit)
        .where(
            ChapterAudit.chapter_id == chapter.id,
            ChapterAudit.version_id == chapter.current_version_id,
        )
        .order_by(ChapterAudit.created_at.desc())
    )
    contract = WritingPolicyService(session).contract(chapter)
    strict_workflow = bool(contract.get("strict"))
    gate_override_reason = payload.gate_override_reason if payload else None
    if strict_workflow and latest_audit is None:
        raise HTTPException(
            status_code=409,
            detail="自动质量保护要求当前版本先完成质量检查，不能直接确认。",
        )
    if strict_workflow and latest_audit and latest_audit.decision != "PASS":
        if not gate_override_reason:
            raise HTTPException(
                status_code=409,
                detail=(
                    "当前质量检查仍未通过；请先按问题修改并重新检查，"
                    "或填写至少 8 个字符的确认理由。"
                ),
            )
    if strict_workflow and not contract["ready"] and not gate_override_reason:
        raise HTTPException(
            status_code=409,
            detail="本章写作准备仍有缺项；系统可自动补齐，或填写至少 8 个字符的确认理由。",
        )
    if latest_audit and latest_audit.fatal_issues:
        reason = (
            payload.fatal_override_reason if payload else None
        ) or gate_override_reason
        if not reason:
            raise HTTPException(
                status_code=409,
                detail="当前版本存在严重问题；请先修改，或填写至少 8 个字符的确认理由。",
            )
        latest_audit.rewrite_requirements = {
            **latest_audit.rewrite_requirements,
            "fatalOverrideReason": reason,
        }
    previous_confirmed_version_id = chapter.confirmed_version_id
    current = SqlAlchemyRepository(session).get_version(chapter.current_version_id)
    if gate_override_reason:
        current.content_json = {
            **(current.content_json or {}),
            "qualityGateOverride": {
                "reason": gate_override_reason,
                "auditDecision": latest_audit.decision if latest_audit else "NOT_AUDITED",
                "prewriteGate": contract.get("gate", {}).get("status"),
                "ruleset": contract.get("ruleset"),
            },
        }
    memory_result = MemoryService(session).commit_confirmed_memory(
        chapter,
        current,
        previous_confirmed_version_id=previous_confirmed_version_id,
    )
    chapter.confirmed_version_id = chapter.current_version_id
    chapter.state = "CONFIRMED"
    chapter.needs_check = False
    session.commit()
    payload_out = chapter_dict(session, chapter, include_content=True)
    if memory_result.get("impact"):
        payload_out["impact"] = memory_result["impact"]
    return payload_out


@router.get("/chapters/{chapter_id}/versions")
def list_versions(chapter_id: str, session: Session = Depends(get_session)):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    versions = session.scalars(select(ChapterVersion).where(ChapterVersion.chapter_id == chapter_id).order_by(ChapterVersion.sequence.desc())).all()
    return [version_dict(version, chapter.current_version_id) for version in versions]


@router.get("/chapters/{chapter_id}/versions/diff")
def diff_versions(
    chapter_id: str,
    left: str,
    right: str,
    session: Session = Depends(get_session),
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    left_v = SqlAlchemyRepository(session).get_version(left)
    right_v = SqlAlchemyRepository(session).get_version(right)
    if left_v.chapter_id != chapter.id or right_v.chapter_id != chapter.id:
        raise HTTPException(status_code=404, detail="Version does not belong to chapter")
    from .text_diff import paragraph_diff

    return {
        "chapterId": chapter.id,
        "left": version_dict(left_v, chapter.current_version_id),
        "right": version_dict(right_v, chapter.current_version_id),
        "diff": paragraph_diff(left_v.content, right_v.content),
    }


@router.post("/chapters/{chapter_id}/versions/{version_id}/restore")
def restore_version(chapter_id: str, version_id: str, payload: RestoreRequest, session: Session = Depends(get_session)):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    target = SqlAlchemyRepository(session).get_version(version_id)
    if target.chapter_id != chapter.id:
        raise HTTPException(status_code=404, detail="Version does not belong to chapter")
    version = ChapterService(session).restore(chapter, target, payload.current_content)
    return {"chapter": chapter_dict(session, chapter, include_content=True), "version": version_dict(version, chapter.current_version_id)}


@router.post("/chapters/{chapter_id}/versions/{version_id}/accept")
def accept_version(
    chapter_id: str,
    version_id: str,
    session: Session = Depends(get_session),
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    candidate = SqlAlchemyRepository(session).get_version(version_id)
    try:
        ChapterService(session).accept_candidate(chapter, candidate)
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return chapter_dict(session, chapter, include_content=True)


@router.delete(
    "/chapters/{chapter_id}/versions/{version_id}",
    status_code=204,
)
def delete_version(
    chapter_id: str,
    version_id: str,
    session: Session = Depends(get_session),
):
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    version = SqlAlchemyRepository(session).get_version(version_id)
    try:
        ChapterService(session).delete_version(chapter, version)
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/chapters/{chapter_id}/audits")
def list_audits(chapter_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_chapter(chapter_id)
    audits = session.scalars(select(ChapterAudit).where(ChapterAudit.chapter_id == chapter_id).order_by(ChapterAudit.created_at.desc())).all()
    return [_audit_with_version_content(session, audit) for audit in audits]


@router.get("/novels/{novel_id}/audits")
def list_novel_audits(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    audits = session.scalars(select(ChapterAudit).where(ChapterAudit.novel_id == novel_id).order_by(ChapterAudit.created_at.desc())).all()
    return [_audit_with_version_content(session, audit) for audit in audits]


def _audit_with_version_content(session: Session, audit: ChapterAudit) -> dict[str, Any]:
    version = session.get(ChapterVersion, audit.version_id)
    return audit_dict(audit, version.content if version else "")


@router.get("/novels/{novel_id}/blueprint")
def get_blueprint(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    return {"blueprint": BlueprintService(session).get_blueprint(novel_id)}


@router.post("/novels/{novel_id}/blueprint/preview")
def preview_blueprint(novel_id: str, session: Session = Depends(get_session)):
    """Draft a story blueprint into a TTL preview (no DB writes)."""
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        return BlueprintService(session).preview(novel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/blueprint/commit")
def commit_blueprint(
    novel_id: str,
    payload: BlueprintCommitRequest,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        return BlueprintService(session).commit(
            novel,
            preview_id=payload.preview_id,
            blueprint=payload.blueprint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/outline")
def get_outline(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    nodes = session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel_id)).all()
    return outline_tree(list(nodes))


@router.post("/novels/{novel_id}/outline/generate")
def generate_outline(
    novel_id: str,
    payload: OutlineGenerateRequest,
    session: Session = Depends(get_session),
):
    """Legacy direct-write generate (kept for compatibility). Prefer preview+commit."""
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        result = OutlineService(session).generate_children(
            novel,
            parent_id=payload.parent_id,
            child_kind=payload.child_kind,
            count=payload.count,
            create_chapters=payload.create_chapters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    nodes = session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel_id)).all()
    return {
        **result,
        "outline": outline_tree(list(nodes)),
    }


@router.post("/novels/{novel_id}/outline/preview")
def preview_outline(
    novel_id: str,
    payload: OutlinePreviewRequest,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        return OutlineService(session).preview_children(
            novel,
            parent_id=payload.parent_id,
            child_kind=payload.child_kind,
            count=payload.count,
            create_chapters=payload.create_chapters,
            mode=payload.mode,
            run_coherence=payload.run_coherence,
            prior_drafts=payload.prior_drafts,
            chapter_offset=payload.chapter_offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/outline/master-preview")
def master_preview_outline(
    novel_id: str,
    payload: OutlineMasterPreviewRequest,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        return OutlineService(session).master_preview(
            novel,
            volume_count=payload.volume_count,
            chapter_count=payload.chapter_count,
            run_coherence=payload.run_coherence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/outline/master-preview/{preview_id}/enrich")
def enrich_master_volume(
    novel_id: str,
    preview_id: str,
    payload: OutlineMasterEnrichRequest,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        return OutlineService(session).enrich_master_volume(
            novel, preview_id=preview_id, index=payload.index
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/outline/regenerate")
def regenerate_outline_node(
    novel_id: str,
    payload: OutlineRegenerateRequest,
    session: Session = Depends(get_session),
):
    """Regenerate one existing outline node into a preview (confirm via commit)."""
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        return OutlineService(session).preview_regenerate_node(
            novel,
            node_id=payload.node_id,
            run_coherence=payload.run_coherence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/outline/commit")
def commit_outline_preview(
    novel_id: str,
    payload: OutlineCommitRequest,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    try:
        result = OutlineService(session).commit_preview(
            novel,
            preview_id=payload.preview_id,
            nodes=payload.nodes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    nodes = session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel_id)).all()
    return {**result, "outline": outline_tree(list(nodes))}


@router.delete("/novels/{novel_id}/outline/preview/{preview_id}", status_code=204)
def discard_outline_preview(
    novel_id: str,
    preview_id: str,
    session: Session = Depends(get_session),
):
    SqlAlchemyRepository(session).get_novel(novel_id)
    ok = OutlineService(session).discard_preview(novel_id, preview_id)
    if not ok:
        raise HTTPException(status_code=404, detail="preview not found or expired")
    return None


@router.patch("/outline-nodes/{node_id}")
def update_outline_node(node_id: str, payload: OutlineUpdate, session: Session = Depends(get_session)):
    node = session.get(OutlineNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Outline node not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    if node.kind == "chapter":
        chapter = session.scalar(select(Chapter).where(Chapter.outline_node_id == node.id))
        if chapter:
            if payload.title is not None:
                chapter.title = payload.title.split("·", 1)[-1].strip()
            if payload.details is not None:
                chapter.brief = payload.details
    session.commit()
    return {"id": node.id, "kind": node.kind, "title": node.title, "locked": node.locked, "details": node.details}


@router.delete("/outline-nodes/{node_id}")
def delete_outline_node(node_id: str, session: Session = Depends(get_session)):
    try:
        return OutlineService(session).delete_node(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/outline-nodes/{node_id}/move")
def move_outline_node(
    node_id: str,
    payload: OutlineMoveRequest,
    session: Session = Depends(get_session),
):
    try:
        result = OutlineService(session).move_node(node_id, payload.direction)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    node = session.get(OutlineNode, node_id)
    novel_id = node.novel_id if node else ""
    nodes = session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel_id)).all() if novel_id else []
    return {**result, "outline": outline_tree(list(nodes))}


def _list_entities(novel_id: str, entity_type: str, session: Session):
    SqlAlchemyRepository(session).get_novel(novel_id)
    entities = session.scalars(select(StoryEntity).where(StoryEntity.novel_id == novel_id, StoryEntity.entity_type == entity_type).order_by(StoryEntity.name)).all()
    return [entity_dict(entity) for entity in entities]


@router.get("/novels/{novel_id}/characters")
def list_characters(novel_id: str, session: Session = Depends(get_session)):
    return _list_entities(novel_id, "character", session)


@router.get("/novels/{novel_id}/locations")
def list_locations(novel_id: str, session: Session = Depends(get_session)):
    return _list_entities(novel_id, "location", session)


@router.get("/novels/{novel_id}/factions")
def list_factions(novel_id: str, session: Session = Depends(get_session)):
    return _list_entities(novel_id, "faction", session)


@router.get("/novels/{novel_id}/items")
def list_items(novel_id: str, session: Session = Depends(get_session)):
    return _list_entities(novel_id, "item", session)


def _create_entity(novel_id: str, entity_type: str, payload: EntityCreate, session: Session):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    entity = StoryEntity(workspace_id=novel.workspace_id, novel_id=novel.id, entity_type=entity_type, **payload.model_dump())
    session.add(entity)
    session.commit()
    return entity_dict(entity)


@router.post("/novels/{novel_id}/characters", status_code=201)
def create_character(novel_id: str, payload: EntityCreate, session: Session = Depends(get_session)):
    return _create_entity(novel_id, "character", payload, session)


@router.post("/novels/{novel_id}/locations", status_code=201)
def create_location(novel_id: str, payload: EntityCreate, session: Session = Depends(get_session)):
    return _create_entity(novel_id, "location", payload, session)


@router.post("/novels/{novel_id}/factions", status_code=201)
def create_faction(novel_id: str, payload: EntityCreate, session: Session = Depends(get_session)):
    return _create_entity(novel_id, "faction", payload, session)


@router.post("/novels/{novel_id}/items", status_code=201)
def create_item(novel_id: str, payload: EntityCreate, session: Session = Depends(get_session)):
    return _create_entity(novel_id, "item", payload, session)


@router.patch("/story-entities/{entity_id}")
def update_entity(entity_id: str, payload: EntityUpdate, session: Session = Depends(get_session)):
    entity = session.get(StoryEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Story entity not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    session.commit()
    return entity_dict(entity)


@router.delete("/story-entities/{entity_id}", status_code=204)
def delete_entity(entity_id: str, session: Session = Depends(get_session)):
    entity = session.get(StoryEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Story entity not found")
    session.delete(entity)
    session.commit()


@router.get("/novels/{novel_id}/character-states")
def list_character_states(
    novel_id: str,
    before_index: int | None = None,
    session: Session = Depends(get_session),
):
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .services_state import StateService

    return StateService(session).latest_character_states(novel_id, before_index=before_index)


@router.get("/novels/{novel_id}/location-states")
def list_location_states(
    novel_id: str,
    before_index: int | None = None,
    session: Session = Depends(get_session),
):
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .services_state import StateService

    return StateService(session).latest_location_states(novel_id, before_index=before_index)


@router.get("/story-entities/{entity_id}/states")
def list_entity_state_history(entity_id: str, session: Session = Depends(get_session)):
    entity = session.get(StoryEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Story entity not found")
    from .services_state import StateService

    if entity.entity_type == "character":
        return StateService(session).list_character_history(entity_id)
    # location history
    from sqlalchemy import select as sa_select
    from .models import LocationState
    from .services_state import location_state_dict

    states = session.scalars(
        sa_select(LocationState)
        .where(LocationState.entity_id == entity_id)
        .order_by(LocationState.chapter_index)
    ).all()
    return [location_state_dict(s, entity.name) for s in states]


@router.get("/novels/{novel_id}/world-rules")
def list_rules(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    rules = session.scalars(select(NovelRule).where(NovelRule.novel_id == novel_id)).all()
    return [rule_dict(rule) for rule in rules]


@router.post("/novels/{novel_id}/world-rules", status_code=201)
def create_rule(novel_id: str, payload: RuleCreate, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    rule = NovelRule(workspace_id=novel.workspace_id, novel_id=novel.id, **payload.model_dump())
    session.add(rule)
    session.commit()
    return rule_dict(rule)


@router.patch("/world-rules/{rule_id}")
def update_rule(rule_id: str, payload: RuleUpdate, session: Session = Depends(get_session)):
    rule = session.get(NovelRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="World rule not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    session.commit()
    return rule_dict(rule)


@router.get("/novels/{novel_id}/timeline")
def list_timeline(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    chapters = {item.id: f"第 {item.chapter_index} 章" for item in session.scalars(select(Chapter).where(Chapter.novel_id == novel_id)).all()}
    events = session.scalars(select(StoryEvent).where(StoryEvent.novel_id == novel_id).order_by(StoryEvent.sequence)).all()
    return [event_dict(event, chapters.get(event.chapter_id or "", "")) for event in events]


@router.get("/novels/{novel_id}/plot-threads")
def list_plot_threads(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    items = session.scalars(select(PlotThread).where(PlotThread.novel_id == novel_id)).all()
    return [plot_thread_dict(item) for item in items]


@router.post("/novels/{novel_id}/plot-threads", status_code=201)
def create_plot_thread(novel_id: str, payload: PlotThreadCreate, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    item = PlotThread(workspace_id=novel.workspace_id, novel_id=novel.id, **payload.model_dump())
    session.add(item)
    session.commit()
    return plot_thread_dict(item)


@router.patch("/plot-threads/{thread_id}")
def update_plot_thread(thread_id: str, payload: PlotThreadUpdate, session: Session = Depends(get_session)):
    item = session.get(PlotThread, thread_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Plot thread not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    session.commit()
    return plot_thread_dict(item)


@router.get("/novels/{novel_id}/beats")
def list_beats(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    items = session.scalars(select(StoryBeat).where(StoryBeat.novel_id == novel_id)).all()
    return {"highlights": [beat_dict(item) for item in items if item.beat_type == "highlight"], "twists": [beat_dict(item) for item in items if item.beat_type == "twist"]}


@router.get("/models")
def list_workspace_models(
    session: Session = Depends(get_session),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Workspace model library (novel_id is null). Used by new-novel wizard."""
    models = session.scalars(
        select(ModelConfig)
        .where(ModelConfig.workspace_id == workspace.id, ModelConfig.novel_id.is_(None))
        .order_by(ModelConfig.is_default.desc(), ModelConfig.updated_at.desc())
    ).all()
    return [model_dict(model) for model in models]


@router.post("/models", status_code=201)
def create_workspace_model(
    payload: ModelConfigCreate,
    session: Session = Depends(get_session),
    workspace: Workspace = Depends(get_current_workspace),
):
    if payload.is_default:
        for item in session.scalars(
            select(ModelConfig).where(
                ModelConfig.workspace_id == workspace.id,
                ModelConfig.novel_id.is_(None),
                ModelConfig.is_default.is_(True),
            )
        ).all():
            item.is_default = False
    model = _model_from_payload(workspace_id=workspace.id, novel_id=None, payload=payload)
    session.add(model)
    session.commit()
    return model_dict(model)


@router.get("/novels/{novel_id}/models")
def list_models(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    models = session.scalars(select(ModelConfig).where(ModelConfig.novel_id == novel_id)).all()
    return [model_dict(model) for model in models]


@router.post("/novels/{novel_id}/models", status_code=201)
def create_model(novel_id: str, payload: ModelConfigCreate, session: Session = Depends(get_session)):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    model = _model_from_payload(workspace_id=novel.workspace_id, novel_id=novel.id, payload=payload)
    session.add(model)
    session.commit()
    return model_dict(model)


@router.patch("/models/{model_id}")
def update_model(model_id: str, payload: ModelConfigUpdate, session: Session = Depends(get_session)):
    model = session.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    if payload.is_default is True and model.novel_id is None:
        for item in session.scalars(
            select(ModelConfig).where(
                ModelConfig.workspace_id == model.workspace_id,
                ModelConfig.novel_id.is_(None),
                ModelConfig.is_default.is_(True),
                ModelConfig.id != model.id,
            )
        ).all():
            item.is_default = False
    _apply_model_update(model, payload)
    session.commit()
    return model_dict(model)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, session: Session = Depends(get_session)):
    model = session.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    session.delete(model)
    session.commit()
    return None


def _is_local_provider(provider: str, model_id: str = "") -> bool:
    if provider in {"内嵌", "embedded", "local-neural", "local_neural"}:
        return True
    return provider in {"本地", "local"} and (not model_id or model_id == "nove-local")


def _parse_remote_models(payload: Any) -> list[dict[str, Any]]:
    """Normalize OpenAI-compatible /models response into [{id, name, ownedBy}]."""
    rows: list[Any]
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if isinstance(item, str):
            model_id = item
            name = item
            owned_by = ""
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            name = str(item.get("name") or item.get("id") or model_id).strip()
            owned_by = str(item.get("owned_by") or item.get("owner") or "").strip()
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        result.append({"id": model_id, "name": name, "ownedBy": owned_by})
    result.sort(key=lambda row: row["id"].lower())
    return result


def _probe_openai_compatible(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str = "",
    timeout_ms: int = 120000,
) -> dict[str, Any]:
    _ensure_cloud_text_model(provider, base_url)
    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    timeout_s = max(3.0, min(30.0, float(timeout_ms or 120000) / 1000.0))
    url = f"{base_url.rstrip('/')}/models"
    try:
        response = httpx.get(url, headers=headers, timeout=timeout_s)
        response.raise_for_status()
        remote_models = _parse_remote_models(response.json())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型连接失败：{exc}") from exc
    latency_ms = round((time.perf_counter() - started) * 1000)
    return {
        "ok": True,
        "status": "connected",
        "latencyMs": latency_ms,
        "models": remote_models,
        "message": f"连接成功，发现 {len(remote_models)} 个模型。"
        if remote_models
        else "连接成功，但端点未返回模型列表，请手动填写模型标识。",
    }


@router.post("/models/probe")
def probe_model_endpoint(payload: ModelProbeRequest):
    """Test connection and list remote models without saving a config."""
    return _probe_openai_compatible(
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model_id=payload.model_id,
        timeout_ms=payload.timeout_ms,
    )


@router.post("/models/{model_id}/test")
def test_model(model_id: str, session: Session = Depends(get_session)):
    model = session.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    try:
        result = _probe_openai_compatible(
            provider=model.provider,
            base_url=model.base_url,
            api_key=decrypt_secret(model.encrypted_api_key),
            model_id=model.model_id,
            timeout_ms=getattr(model, "timeout_ms", 120000) or 120000,
        )
    except HTTPException:
        model.status = "error"
        session.commit()
        raise
    model.status = "connected"
    model.latency_ms = int(result.get("latencyMs") or 0)
    session.commit()
    return {**model_dict(model), "probe": result}


@router.get("/models/{model_id}/remote-models")
def list_remote_models(model_id: str, session: Session = Depends(get_session)):
    """Re-fetch available model ids from a saved config's endpoint."""
    model = session.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    result = _probe_openai_compatible(
        provider=model.provider,
        base_url=model.base_url,
        api_key=decrypt_secret(model.encrypted_api_key),
        model_id=model.model_id,
        timeout_ms=getattr(model, "timeout_ms", 120000) or 120000,
    )
    return result


@router.get("/novels/{novel_id}/audit-config")
def get_audit_config(novel_id: str, session: Session = Depends(get_session)):
    config = session.scalar(select(AuditConfig).where(AuditConfig.novel_id == novel_id))
    if config is None:
        raise HTTPException(status_code=404, detail="Audit config not found")
    return audit_config_dict(config)


@router.patch("/novels/{novel_id}/audit-config")
def update_audit_config(novel_id: str, payload: AuditConfigUpdate, session: Session = Depends(get_session)):
    config = session.scalar(select(AuditConfig).where(AuditConfig.novel_id == novel_id))
    if config is None:
        raise HTTPException(status_code=404, detail="Audit config not found")
    values = payload.model_dump()
    for key, value in values.items():
        setattr(config, key, value)
    config.rubric_version += 1
    session.commit()
    return audit_config_dict(config)


@router.get("/novels/{novel_id}/agent-calls")
def list_agent_calls(novel_id: str, limit: int = 50, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .models import AgentCallLog

    rows = session.scalars(
        select(AgentCallLog)
        .where(AgentCallLog.novel_id == novel_id)
        .order_by(AgentCallLog.created_at.desc())
        .limit(max(1, min(200, limit)))
    ).all()
    return [
        {
            "id": row.id,
            "agentName": row.agent_name,
            "modelName": row.model_name,
            "operation": row.operation,
            "status": row.status,
            "durationMs": row.duration_ms,
            "inputTokens": row.input_tokens,
            "outputTokens": row.output_tokens,
            "inputSummary": row.input_summary,
            "outputSummary": row.output_summary,
            "error": row.error,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/novels/{novel_id}/usage")
def novel_usage_stats(novel_id: str, session: Session = Depends(get_session)):
    """Aggregate model/agent usage for FR-013 style dashboards."""
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .models import AgentCallLog, SkillRun

    rows = session.scalars(
        select(AgentCallLog).where(AgentCallLog.novel_id == novel_id)
    ).all()
    skill_rows = session.scalars(
        select(SkillRun).where(SkillRun.novel_id == novel_id)
    ).all()

    by_model: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    total_in = 0
    total_out = 0
    total_ms = 0
    errors = 0
    for row in rows:
        total_in += int(row.input_tokens or 0)
        total_out += int(row.output_tokens or 0)
        total_ms += int(row.duration_ms or 0)
        if row.status != "ok":
            errors += 1
        model_key = row.model_name or "(unknown)"
        agent_key = row.agent_name or "(unknown)"
        for bag, key in ((by_model, model_key), (by_agent, agent_key)):
            item = bag.setdefault(
                key,
                {
                    "name": key,
                    "calls": 0,
                    "errors": 0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "durationMs": 0,
                },
            )
            item["calls"] += 1
            item["inputTokens"] += int(row.input_tokens or 0)
            item["outputTokens"] += int(row.output_tokens or 0)
            item["durationMs"] += int(row.duration_ms or 0)
            if row.status != "ok":
                item["errors"] += 1

    # Rough cost estimate: $0.5 / 1M in + $1.5 / 1M out (placeholder, not billing).
    est_cost = (total_in / 1_000_000) * 0.5 + (total_out / 1_000_000) * 1.5
    calls = len(rows)
    return {
        "novelId": novel_id,
        "calls": calls,
        "errors": errors,
        "errorRate": round(errors / calls, 4) if calls else 0,
        "inputTokens": total_in,
        "outputTokens": total_out,
        "totalTokens": total_in + total_out,
        "durationMs": total_ms,
        "avgLatencyMs": round(total_ms / calls) if calls else 0,
        "estimatedCostUsd": round(est_cost, 6),
        "byModel": sorted(by_model.values(), key=lambda x: x["calls"], reverse=True),
        "byAgent": sorted(by_agent.values(), key=lambda x: x["calls"], reverse=True),
        "skillRuns": len(skill_rows),
        "recent": [
            {
                "id": row.id,
                "agentName": row.agent_name,
                "modelName": row.model_name,
                "operation": row.operation,
                "status": row.status,
                "durationMs": row.duration_ms,
                "inputTokens": row.input_tokens,
                "outputTokens": row.output_tokens,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
            }
            for row in sorted(
                rows, key=lambda r: r.created_at or r.id, reverse=True
            )[:20]
        ],
    }


def _clear_embedding_role(session: Session, novel_id: str) -> None:
    models = session.scalars(select(ModelConfig).where(ModelConfig.novel_id == novel_id)).all()
    for model in models:
        roles = list(model.roles or [])
        if "Embedding" not in roles and "embedding" not in roles:
            continue
        model.roles = [r for r in roles if r not in {"Embedding", "embedding"}]


def _upsert_embedded_model(
    session: Session,
    *,
    novel_id: str,
    workspace_id: str,
    entry: dict[str, Any],
) -> ModelConfig:
    """Create or update the novel's in-process embedding model and assign role."""
    _clear_embedding_role(session, novel_id)
    existing = session.scalars(
        select(ModelConfig).where(
            ModelConfig.novel_id == novel_id,
            ModelConfig.provider.in_(["内嵌", "embedded", "local-neural"]),
            ModelConfig.model_id == entry["modelId"],
        )
    ).first()
    extra = {
        "runtime": "fastembed",
        "catalogKey": entry["key"],
        "dimensions": entry["dimensions"],
    }
    if existing is None:
        existing = ModelConfig(
            workspace_id=workspace_id,
            novel_id=novel_id,
            name=f"本地 · {entry['name']}",
            provider="内嵌",
            model_id=entry["modelId"],
            base_url="",
            encrypted_api_key="",
            status="connected",
            roles=["Embedding"],
            temperature=0,
            top_p=100,
            max_output_tokens=512,
            context_size=8192,
            timeout_ms=120000,
            is_default=False,
            extra_body=extra,
        )
        session.add(existing)
    else:
        existing.name = f"本地 · {entry['name']}"
        existing.status = "connected"
        existing.roles = ["Embedding"]
        existing.extra_body = extra
        existing.base_url = ""
    return existing


@router.get("/embedding/local-catalog")
def embedding_local_catalog():
    from .memory.local_runtime import catalog_with_download_flags

    return catalog_with_download_flags()


@router.get("/novels/{novel_id}/embedding/local/status")
def embedding_local_status(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    from .memory.local_runtime import get_download_status

    return get_download_status(novel_id)


@router.post("/novels/{novel_id}/embedding/local/download")
def embedding_local_download(
    novel_id: str,
    payload: EmbeddingLocalDownloadRequest,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    from .memory.local_catalog import get_catalog_entry
    from .memory.local_runtime import start_download_job

    entry = get_catalog_entry(payload.catalog_key)
    if entry is None:
        raise HTTPException(status_code=422, detail=f"未知模型档位：{payload.catalog_key}")

    workspace_id = novel.workspace_id

    def on_complete(done_entry: Any) -> None:
        # Use db_module.SessionLocal so tests can rebind the factory.
        with db_module.SessionLocal() as db:
            try:
                _upsert_embedded_model(
                    db,
                    novel_id=novel_id,
                    workspace_id=workspace_id,
                    entry=dict(done_entry),
                )
                db.commit()
            except Exception:
                db.rollback()
                raise

    try:
        job = start_download_job(
            novel_id=novel_id,
            catalog_key=payload.catalog_key,
            on_complete=on_complete,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job.to_dict()


@router.post("/novels/{novel_id}/embedding/cloud", status_code=201)
def embedding_cloud_create(
    novel_id: str,
    payload: EmbeddingCloudCreate,
    session: Session = Depends(get_session),
):
    novel = SqlAlchemyRepository(session).get_novel(novel_id)
    base_url = payload.base_url.strip()
    model_id = payload.model_id.strip()
    if not base_url:
        raise HTTPException(status_code=422, detail="请填写 Base URL")
    if not model_id:
        raise HTTPException(status_code=422, detail="请填写模型标识")

    # Light probe: GET /models if possible; still allow save when list empty.
    try:
        result = _probe_openai_compatible(
            provider=payload.provider,
            base_url=base_url,
            api_key=payload.api_key,
            model_id=model_id,
        )
        status = "connected" if result.get("ok") else "untested"
        latency_ms = int(result.get("latencyMs") or 0)
    except HTTPException:
        status = "error"
        latency_ms = 0

    _clear_embedding_role(session, novel_id)
    name = payload.name.strip() or f"Embedding · {model_id}"
    model = ModelConfig(
        workspace_id=novel.workspace_id,
        novel_id=novel_id,
        name=name,
        provider=payload.provider or "OpenAI 兼容",
        model_id=model_id,
        base_url=base_url,
        encrypted_api_key=encrypt_secret(payload.api_key),
        status=status,
        roles=["Embedding"],
        latency_ms=latency_ms or None,
        temperature=0,
        top_p=100,
        max_output_tokens=512,
        context_size=8192,
        timeout_ms=60000,
        is_default=False,
        extra_body={"purpose": "embedding"},
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return model_dict(model)


@router.delete("/novels/{novel_id}/embedding/assignment", status_code=204)
def embedding_clear_assignment(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    _clear_embedding_role(session, novel_id)
    session.commit()
    return None


@router.get("/novels/{novel_id}/memory/status")
def get_memory_status(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    return MemoryService(session).memory_status(novel_id)


@router.post("/novels/{novel_id}/memory/reindex")
def reindex_memory(novel_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    return MemoryService(session).reindex_novel(novel_id)


@router.get("/novels/{novel_id}/impact/{chapter_id}")
def get_chapter_impact(novel_id: str, chapter_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_novel(novel_id)
    chapter = SqlAlchemyRepository(session).get_chapter(chapter_id)
    if chapter.novel_id != novel_id:
        raise HTTPException(status_code=404, detail="Chapter not found in novel")
    later = session.scalars(
        select(Chapter).where(
            Chapter.novel_id == novel_id,
            Chapter.chapter_index > chapter.chapter_index,
            Chapter.needs_check.is_(True),
        ).order_by(Chapter.chapter_index)
    ).all()
    return {
        "sourceChapterId": chapter.id,
        "sourceChapterIndex": chapter.chapter_index,
        "affectedChapters": [
            {
                "chapterId": item.id,
                "chapterIndex": item.chapter_index,
                "title": item.title,
                "state": item.state,
                "needsCheck": item.needs_check,
            }
            for item in later
        ],
    }


@router.get("/skills")
def list_skills(session: Session = Depends(get_session)):
    return [skill_dict(skill) for skill in session.scalars(select(Skill).order_by(Skill.name)).all()]


def _skill_metadata(content: str) -> tuple[str, str, str]:
    """Read the minimal portable SKILL.md front matter without executing it."""
    text = content.strip()
    metadata: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    metadata[key.strip().lower()] = value.strip().strip('"\'')
            body = parts[2].strip()
    heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), "")
    raw_name = metadata.get("name") or heading or "imported-skill"
    name = re.sub(r"[^a-z0-9-]+", "-", raw_name.lower()).strip("-")[:100]
    if not name:
        raise HTTPException(status_code=422, detail="SKILL.md 缺少可用的 name 或标题")
    return name, metadata.get("version", "1.0.0")[:40], metadata.get("description", heading)[:2000]


@router.post("/skills/import", status_code=201)
def import_skill(payload: SkillImport, session: Session = Depends(get_session)):
    name, version, description = _skill_metadata(payload.content)
    if name in {"continuity-check", "entity-lookup", "outline-generate", "outline-coherence"}:
        raise HTTPException(status_code=409, detail="不能覆盖系统 Skill")
    if session.scalar(select(Skill).where(Skill.name == name)) is not None:
        raise HTTPException(status_code=409, detail="已存在同名 Skill，请修改 SKILL.md 的 name 后重试")
    skill = Skill(
        workspace_id="local",
        name=name,
        version=version,
        description=description or "用户导入的提示型 Skill",
        allowed_agents=[],
        input_schema={"x-nove-origin": "user", "instructions": payload.content},
        output_schema={},
        enabled=True,
    )
    session.add(skill)
    session.commit()
    session.refresh(skill)
    return skill_dict(skill)


@router.patch("/skills/{skill_id}")
def update_skill(skill_id: str, payload: SkillUpdate, session: Session = Depends(get_session)):
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if (skill.input_schema or {}).get("x-nove-origin") == "system":
        raise HTTPException(status_code=403, detail="系统 Skill 的授权由系统固定管理")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(skill, key, value)
    session.commit()
    return skill_dict(skill)


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: str, session: Session = Depends(get_session)):
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if (skill.input_schema or {}).get("x-nove-origin") == "system":
        raise HTTPException(status_code=403, detail="系统 Skill 不能删除")
    session.delete(skill)
    session.commit()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)):
    return job_dict(SqlAlchemyRepository(session).get_job(job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, session: Session = Depends(get_session)):
    job = SqlAlchemyRepository(session).get_job(job_id)
    if job.state in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Job is already finished")
    job.cancel_requested = True
    session.commit()
    return job_dict(job)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, session: Session = Depends(get_session)):
    SqlAlchemyRepository(session).get_job(job_id)

    async def stream():
        sent = 0
        while True:
            session.expire_all()
            job = SqlAlchemyRepository(session).get_job(job_id)
            events = job.events or []
            for event in events[sent:]:
                yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            sent = len(events)
            if job.state in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            await asyncio.sleep(0.2)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
