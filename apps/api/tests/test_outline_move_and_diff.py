from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chapter, OutlineNode
from app.services_outline import OutlineService
from app.text_diff import paragraph_diff


def test_move_swaps_siblings_and_renumbers(session: Session) -> None:
    # o c10 and later siblings under arc1
    nodes = session.scalars(
        select(OutlineNode)
        .where(OutlineNode.parent_id == "arc1", OutlineNode.kind == "chapter")
        .order_by(OutlineNode.position)
    ).all()
    assert len(nodes) >= 2
    first, second = nodes[0], nodes[1]
    first_id, second_id = first.id, second.id
    service = OutlineService(session)
    result = service.move_node(second_id, "up")
    assert result["moved"] is True
    session.refresh(first)
    session.refresh(second)
    # After move+normalize, second should now be before first in position
    ordered = session.scalars(
        select(OutlineNode)
        .where(OutlineNode.parent_id == "arc1", OutlineNode.kind == "chapter")
        .order_by(OutlineNode.position)
    ).all()
    ids = [n.id for n in ordered]
    assert ids.index(second_id) < ids.index(first_id)

    # Chapter indexes renumbered by tree order
    chapters = session.scalars(
        select(Chapter).where(Chapter.novel_id == "starfarer").order_by(Chapter.chapter_index)
    ).all()
    indexes = [c.chapter_index for c in chapters]
    assert indexes == sorted(indexes)
    assert len(indexes) == len(set(indexes))


def test_paragraph_diff_detects_changes() -> None:
    left = "第一段。\n\n旧的第二段。\n\n第三段。"
    right = "第一段。\n\n新的第二段。\n\n第三段。\n\n新增段。"
    result = paragraph_diff(left, right)
    assert result["stats"]["deleted"] >= 1
    assert result["stats"]["inserted"] >= 1
    assert any(r["change"] == "equal" for r in result["left"])
