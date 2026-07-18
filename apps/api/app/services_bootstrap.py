"""Background orchestration for turning one story idea into a writable novel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .craft import normalize_writing_profile
from .db import SessionLocal
from .models import Chapter, Novel, OutlineNode
from .services_bible_bootstrap import BibleBootstrapService
from .services_blueprint import BlueprintService
from .services_outline import OutlineService


_bootstrap_locks: dict[str, threading.Lock] = {}
_bootstrap_locks_guard = threading.Lock()


class NovelBootstrapService:
    def __init__(
        self,
        session: Session,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        max_workers: int = 3,
    ):
        self.session = session
        self.session_factory = session_factory
        self.max_workers = max(1, min(4, max_workers))

    def queue(self, novel: Novel) -> None:
        profile = normalize_writing_profile(novel.writing_profile)
        profile.update(
            {
                "strict_workflow": False,
                "bootstrap_status": "pending",
                "bootstrap_stage": "blueprint",
                "bootstrap_progress": 0,
                "bootstrap_message": "准备故事方向",
                "bootstrap_error": "",
            }
        )
        novel.writing_profile = profile
        self.session.commit()

    def run(self, novel_id: str) -> dict[str, Any]:
        novel = self.session.get(Novel, novel_id)
        if novel is None:
            raise ValueError("novel not found")
        if normalize_writing_profile(novel.writing_profile)["bootstrap_status"] == "complete":
            return self.status(novel)

        try:
            self._set_state(novel, "running", "blueprint", 8, "正在搭建故事方向")
            blueprint_service = BlueprintService(self.session)
            blueprint = blueprint_service.get_blueprint(novel.id)
            if blueprint is None:
                preview = blueprint_service.preview(novel)
                committed = blueprint_service.commit(novel, preview_id=preview["previewId"])
                blueprint = committed["blueprint"]
                draft_source = committed["draftSource"]
            else:
                committed = blueprint_service.commit(novel, blueprint=blueprint)
                draft_source = committed["draftSource"]
            self.session.refresh(novel)
            self._set_state(
                novel,
                "running",
                "bible",
                18,
                "正在准备人物与世界",
                draft_source=draft_source,
            )
            BibleBootstrapService(
                self.session,
                session_factory=self.session_factory,
            ).build(novel, blueprint=blueprint)
            self._set_state(
                novel,
                "running",
                "volumes",
                38,
                "正在规划全书阶段",
                draft_source=draft_source,
            )

            outline = OutlineService(self.session)
            volumes = self._children(novel.id, parent_id=None, kind="volume")
            if not volumes:
                master = outline.master_preview(novel)
                enriched = self._enrich_volumes(
                    novel.id,
                    preview_id=master["previewId"],
                    count=len(master.get("nodes") or []),
                )
                outline.commit_preview(
                    novel,
                    preview_id=master["previewId"],
                    nodes=enriched,
                )
                volumes = self._children(novel.id, parent_id=None, kind="volume")
            if not volumes:
                raise ValueError("没有生成可用的分卷规划")

            self._set_state(novel, "running", "arcs", 65, "正在细化第一卷剧情")
            first_volume = volumes[0]
            arcs = self._children(novel.id, parent_id=first_volume.id, kind="arc")
            if not arcs:
                arc_preview = outline.preview_children(
                    novel,
                    parent_id=first_volume.id,
                    child_kind="arc",
                    count=3,
                    create_chapters=False,
                    mode="children",
                )
                outline.commit_preview(novel, preview_id=arc_preview["previewId"])
                arcs = self._children(novel.id, parent_id=first_volume.id, kind="arc")
            if not arcs:
                raise ValueError("没有生成可用的剧情阶段")

            self._set_state(novel, "running", "chapters", 82, "正在准备首批章节")
            first_arc = arcs[0]
            chapter_nodes = self._children(novel.id, parent_id=first_arc.id, kind="chapter")
            if not chapter_nodes:
                chapter_preview = outline.preview_children(
                    novel,
                    parent_id=first_arc.id,
                    child_kind="chapter",
                    count=8,
                    create_chapters=True,
                    mode="batch_chapters",
                )
                outline.commit_preview(novel, preview_id=chapter_preview["previewId"])

            self._set_state(novel, "complete", "complete", 100, "故事已经准备好")
            return self.status(novel)
        except Exception as exc:
            self.session.rollback()
            novel = self.session.get(Novel, novel_id)
            if novel is None:
                raise
            current = normalize_writing_profile(novel.writing_profile)
            self._set_state(
                novel,
                "failed",
                current.get("bootstrap_stage") or "blueprint",
                int(current.get("bootstrap_progress") or 0),
                "搭建暂时中断，可以从当前进度重试",
                error=str(exc)[:500],
            )
            return self.status(novel)

    def status(self, novel: Novel) -> dict[str, Any]:
        profile = normalize_writing_profile(novel.writing_profile)
        blueprint = BlueprintService(self.session).get_blueprint(novel.id) or {}
        counts = {
            kind: int(
                self.session.scalar(
                    select(func.count(OutlineNode.id)).where(
                        OutlineNode.novel_id == novel.id,
                        OutlineNode.kind == kind,
                    )
                )
                or 0
            )
            for kind in ("volume", "arc", "chapter")
        }
        bible_counts = BibleBootstrapService(self.session).counts(novel.id)
        first_chapter = self.session.scalar(
            select(Chapter)
            .where(Chapter.novel_id == novel.id)
            .order_by(Chapter.chapter_index)
        )
        protagonist = blueprint.get("protagonist") or {}
        world = blueprint.get("world") or {}
        return {
            "novelId": novel.id,
            "status": profile["bootstrap_status"] or "not_started",
            "stage": profile["bootstrap_stage"] or "blueprint",
            "progress": profile["bootstrap_progress"],
            "message": profile["bootstrap_message"],
            "error": profile["bootstrap_error"],
            "autoGenerated": profile["auto_generated"],
            "draftSource": profile["bootstrap_draft_source"],
            "blueprint": {
                "bookTitle": blueprint.get("book_title") or novel.title,
                "logline": blueprint.get("logline") or novel.core_idea,
                "protagonistName": protagonist.get("name") or profile["protagonist_name"],
                "protagonistGoal": protagonist.get("goal") or profile["protagonist_desire"],
                "worldSetting": world.get("setting") or profile["world_scale"],
            },
            "counts": {
                **bible_counts,
                "volumes": counts["volume"],
                "arcs": counts["arc"],
                "chapters": counts["chapter"],
            },
            "firstChapterId": first_chapter.id if first_chapter is not None else None,
        }

    def _set_state(
        self,
        novel: Novel,
        status: str,
        stage: str,
        progress: int,
        message: str,
        *,
        error: str = "",
        draft_source: str | None = None,
    ) -> None:
        profile = normalize_writing_profile(novel.writing_profile)
        profile.update(
            {
                "bootstrap_status": status,
                "bootstrap_stage": stage,
                "bootstrap_progress": progress,
                "bootstrap_message": message,
                "bootstrap_error": error,
            }
        )
        if draft_source is not None:
            profile["bootstrap_draft_source"] = draft_source
        novel.writing_profile = profile
        self.session.commit()

    def _children(
        self, novel_id: str, *, parent_id: str | None, kind: str
    ) -> list[OutlineNode]:
        return list(
            self.session.scalars(
                select(OutlineNode)
                .where(
                    OutlineNode.novel_id == novel_id,
                    OutlineNode.parent_id == parent_id,
                    OutlineNode.kind == kind,
                )
                .order_by(OutlineNode.position)
            ).all()
        )

    def _enrich_volumes(
        self, novel_id: str, *, preview_id: str, count: int
    ) -> list[dict[str, Any]]:
        if count < 1:
            raise ValueError("分卷草案为空")

        def enrich(index: int) -> tuple[int, dict[str, Any]]:
            with self.session_factory() as worker_session:
                worker_novel = worker_session.get(Novel, novel_id)
                if worker_novel is None:
                    raise ValueError("novel not found")
                result = OutlineService(worker_session).enrich_master_volume(
                    worker_novel,
                    preview_id=preview_id,
                    index=index,
                )
                return index, result["node"]

        ordered: list[dict[str, Any] | None] = [None] * count
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, count),
            thread_name_prefix="novel-bootstrap",
        ) as pool:
            futures = [pool.submit(enrich, index) for index in range(count)]
            for future in as_completed(futures):
                index, node = future.result()
                ordered[index] = node
        return [node for node in ordered if node is not None]


def run_novel_bootstrap(novel_id: str) -> None:
    with _bootstrap_locks_guard:
        lock = _bootstrap_locks.setdefault(novel_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        with SessionLocal() as session:
            NovelBootstrapService(session).run(novel_id)
    finally:
        lock.release()
        with _bootstrap_locks_guard:
            if not lock.locked():
                _bootstrap_locks.pop(novel_id, None)
