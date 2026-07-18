from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.outline import heuristic_outline_children, normalize_outline_nodes
from app.models import Chapter, Novel, OutlineNode
from app.services_outline import OutlineService


def test_heuristic_outline_children_kinds() -> None:
    nodes = heuristic_outline_children(
        novel={"title": "星河", "coreIdea": "信标"},
        parent={"title": "第一卷"},
        child_kind="chapter",
        count=2,
        existing_titles=[],
        start_chapter_index=20,
    )
    assert len(nodes) == 2
    assert nodes[0]["kind"] == "chapter"
    assert "20" in nodes[0]["title"] or "第 20" in nodes[0]["title"]


def test_normalize_outline_nodes_filters_kind() -> None:
    nodes = normalize_outline_nodes(
        {
            "nodes": [
                {"kind": "chapter", "title": "A", "details": {"goal": "g"}},
                {"kind": "volume", "title": "B", "details": {}},
            ]
        },
        child_kind="chapter",
        count=5,
    )
    assert len(nodes) == 2
    assert all(n["kind"] == "chapter" for n in nodes)


def test_generate_appends_without_touching_locked(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    arc = session.get(OutlineNode, "arc1")
    assert arc is not None
    locked_before = session.scalars(
        select(OutlineNode).where(
            OutlineNode.novel_id == novel.id,
            OutlineNode.locked.is_(True),
        )
    ).all()
    locked_titles = {item.title for item in locked_before}
    before_count = session.scalar(
        select(OutlineNode).where(OutlineNode.parent_id == "arc1")
    )
    assert before_count is not None

    sibling_count = len(
        session.scalars(
            select(OutlineNode).where(OutlineNode.parent_id == "arc1")
        ).all()
    )
    chapter_count = len(
        session.scalars(select(Chapter).where(Chapter.novel_id == novel.id)).all()
    )

    result = OutlineService(session).generate_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=2,
        create_chapters=True,
    )
    assert len(result["created"]) == 2
    assert result["chaptersCreated"] == 2

    after_siblings = session.scalars(
        select(OutlineNode).where(OutlineNode.parent_id == "arc1")
    ).all()
    assert len(after_siblings) == sibling_count + 2
    still_locked = {
        item.title
        for item in after_siblings
        if item.locked
    }
    assert locked_titles.issubset(still_locked)

    after_chapters = session.scalars(
        select(Chapter).where(Chapter.novel_id == novel.id)
    ).all()
    assert len(after_chapters) == chapter_count + 2


def test_generate_under_locked_parent_appends_scenes(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    locked = session.scalar(
        select(OutlineNode).where(
            OutlineNode.novel_id == novel.id,
            OutlineNode.locked.is_(True),
            OutlineNode.kind == "chapter",
        )
    )
    assert locked is not None
    before = len(
        session.scalars(
            select(OutlineNode).where(OutlineNode.parent_id == locked.id)
        ).all()
    )
    result = OutlineService(session).generate_children(
        novel,
        parent_id=locked.id,
        child_kind="scene",
        count=2,
        create_chapters=False,
    )
    assert len(result["created"]) == 2
    after = session.scalars(
        select(OutlineNode).where(OutlineNode.parent_id == locked.id)
    ).all()
    assert len(after) == before + 2
    session.refresh(locked)
    assert locked.locked is True
