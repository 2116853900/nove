from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditConfig,
    Chapter,
    ChapterVersion,
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
from .services import AuditService


SAMPLE_CONTENT = """信标坠入大气层时，林远正站在观测台的落地窗前。橙红色的尾焰划开夜空，像一道迟到了三百年的回信。

警报声在走廊尽头响起，又很快被隔音门吞没。他没有回头，只是把掌心贴在冰凉的玻璃上，感受那束光一点点沉入远处的山脊。

「坐标已经锁定。」苏晚的声音从通讯器里传来，比平时低了半度。「但我们没有足够的燃料抵达。」

林远沉默了很久。这段独白是他与父亲最后一次对话的复写，任何改写都会破坏它的重量。

他转过身，眼神里有一种苏晚从未见过的笃定：「信标的来源，我还需要再确认。」

舱室的灯光忽明忽暗。远处，第二枚信标的光点正在缓缓升起，仿佛整片星空都在等待他们的回答。"""


def ensure_workspace_model_library(session: Session, workspace_id: str = "local") -> None:
    """Remove the retired local text model from workspace and novel scopes."""
    candidates = session.scalars(
        select(ModelConfig).where(
            ModelConfig.workspace_id == workspace_id,
        )
    ).all()
    for model in candidates:
        hostname = (urlparse(model.base_url or "").hostname or "").lower()
        if (
            model.provider in {"本地", "local", "Ollama", "vLLM"}
            or model.model_id == "nove-local"
            or hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
        ):
            session.delete(model)


def ensure_seed_data(session: Session, *, demo: bool = False) -> None:
    """Create the local workspace if missing. Demo novel only when demo=True (tests)."""
    if not session.scalar(select(func.count(Workspace.id))):
        session.add(Workspace(id="local", name="本地工作区"))
        session.flush()

    ensure_workspace_model_library(session, "local")

    if demo:
        seed_demo_novel(session)
    else:
        session.commit()


def seed_demo_novel(session: Session) -> None:
    """Insert the starfarer fixture used by automated tests."""
    if session.get(Novel, "starfarer"):
        session.commit()
        return

    workspace = session.get(Workspace, "local")
    if workspace is None:
        workspace = Workspace(id="local", name="本地工作区")
        session.add(workspace)
        session.flush()

    novel = Novel(
        id="starfarer",
        workspace_id=workspace.id,
        title="星河旅人",
        genre="科幻",
        core_idea="一名宇航员在深空发现三百年前殖民船留下的信标。",
        planned_chapters=80,
    )
    session.add(novel)
    session.flush()

    volume = OutlineNode(id="vol1", workspace_id="local", novel_id=novel.id, kind="volume", title="第一卷 · 坠落", position=1)
    arc = OutlineNode(id="arc1", workspace_id="local", novel_id=novel.id, parent_id="vol1", kind="arc", title="剧情弧 · 改变航向", position=1)
    session.add_all([volume, arc])

    chapter_specs = [
        ("c1", 1, "坠落的信标", "CONFIRMED"),
        ("c2", 2, "锈蚀舱门", "CONFIRMED"),
        ("c3", 3, "第一次接触", "CONFIRMED"),
        ("c10", 10, "静默航道", "REVIEW_REQUIRED"),
        ("c11", 11, "深空回声", "DRAFT"),
        ("c12", 12, "破碎的誓约", "PLANNED"),
        ("c13", 13, "灰烬之下", "PLANNED"),
    ]
    for order, (chapter_id, index, title, state) in enumerate(chapter_specs, start=1):
        node = OutlineNode(
            id=f"o{chapter_id}", workspace_id="local", novel_id=novel.id,
            parent_id="arc1", kind="chapter", title=f"第 {index} 章 · {title}",
            position=order, locked=index == 1,
        )
        chapter = Chapter(
            id=chapter_id, workspace_id="local", novel_id=novel.id,
            outline_node_id=node.id, chapter_index=index, title=title, state=state,
            memory_status="INDEXED" if state == "CONFIRMED" else "NOT_INDEXED",
            brief={
                "goal": "确认信标的来源并决定是否改变航向",
                "conflict": "燃料不足，团队对风险判断产生分歧",
                "must_events": ["锁定信标坐标"],
                "forbidden_events": ["提前揭示苏晚的真实身份"],
                "hook": "第二枚信标从山脊后升起",
            },
        )
        session.add_all([node, chapter])
        session.flush()
        if index <= 11:
            version = ChapterVersion(
                id=f"{chapter_id}v1", workspace_id="local", novel_id=novel.id,
                chapter_id=chapter.id, sequence=1, source="confirm" if index <= 3 else "user",
                title=title, content=SAMPLE_CONTENT if index == 1 else f"第 {index} 章 · {title}\n\n这一章的正文仍在整理。",
                content_json={}, audit_score=88 if index <= 3 else (72 if index == 10 else None),
            )
            session.add(version)
            session.flush()
            chapter.current_version_id = version.id
            chapter.confirmed_version_id = version.id if index <= 3 else None
            chapter.latest_score = version.audit_score

    rules = [
        ("超光速跳跃需要至少 3 根燃料棒", "物理规则", "高", True),
        ("泽塔信标每 300 年只出现一次", "世界设定", "高", True),
        ("深空通讯存在 8 分钟延迟", "物理规则", "中", False),
    ]
    session.add_all([
        NovelRule(workspace_id="local", novel_id=novel.id, rule=text, rule_type=kind, importance=importance, locked=locked)
        for text, kind, importance, locked in rules
    ])

    entities = [
        ("character", "林远", {"role": "主角", "status": "在观测台"}, ["背景"]),
        ("character", "苏晚", {"role": "领航员", "status": "在指挥舱"}, []),
        ("character", "老赫", {"role": "工程师", "status": "重伤 · 医疗舱"}, []),
        ("location", "曦光号", {"region": "深空", "state": "航行中", "depth": 0}, []),
        ("location", "观测台", {"region": "曦光号", "state": "正常", "depth": 1}, []),
        ("location", "指挥舱", {"region": "曦光号", "state": "正常", "depth": 1}, []),
        ("faction", "地球联合议会", {"kind": "政治", "stance": "中立", "power": "强"}, []),
        ("faction", "深空拓殖公司", {"kind": "商业", "stance": "对立", "power": "强"}, []),
        ("item", "泽塔信标", {"kind": "关键物品", "owner": "无", "state": "坠落于山脊"}, []),
        ("item", "父亲的怀表", {"kind": "情感物品", "owner": "林远", "state": "随身携带"}, []),
    ]
    session.add_all([
        StoryEntity(workspace_id="local", novel_id=novel.id, entity_type=kind, name=name, data=data, locked_fields=locked)
        for kind, name, data, locked in entities
    ])

    session.add_all([
        StoryEvent(workspace_id="local", novel_id=novel.id, chapter_id="c1", story_time="航行第 812 天 · 夜", sequence=1, subjects=["林远"], action="目睹信标坠落", location="观测台", consequences="决定改变航向"),
        StoryEvent(workspace_id="local", novel_id=novel.id, chapter_id="c1", story_time="航行第 812 天 · 夜", sequence=2, subjects=["苏晚"], action="锁定坠落坐标", location="指挥舱", consequences="发现燃料不足"),
    ])
    session.add_all([
        PlotThread(workspace_id="local", novel_id=novel.id, name="父亲失踪之谜", kind="谜团", status="DEVELOPING", planted="第 1 章", payoff="第 40 章", importance="高", latest="第 9 章出现新线索"),
        PlotThread(workspace_id="local", novel_id=novel.id, name="信标的真实来源", kind="伏笔", status="PLANTED", planted="第 1 章", payoff="第 25 章", importance="高", latest="尚未发展"),
    ])
    session.add_all([
        StoryBeat(workspace_id="local", novel_id=novel.id, chapter_label="第 1 章", beat_type="highlight", data={"text": "信标划破夜空的开场画面，奠定孤独与希望并存的基调"}),
        StoryBeat(workspace_id="local", novel_id=novel.id, chapter_label="第 12 章", beat_type="twist", data={"surface": "苏晚是普通领航员", "reality": "苏晚是深空拓殖公司安插的观察员", "clues": "第 3 章她异常熟悉禁飞航道；第 7 章私下加密通讯", "characters": "苏晚 · 林远", "aftermath": "林远对团队的信任崩塌"}),
    ])

    dimensions = AuditService.DEFAULT_DIMENSIONS
    session.add(AuditConfig(workspace_id="local", novel_id=novel.id, dimensions=dimensions))
    session.add(
        ModelConfig(
            workspace_id="local",
            novel_id=novel.id,
            name="DeepSeek-V3",
            provider="OpenAI 兼容",
            model_id="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            status="untested",
            roles=["审计", "连续性"],
        )
    )
    session.add(
        Skill(
            workspace_id="local",
            name="continuity-check",
            version="1.1.0",
            description="检查锁定内容、知识边界与必达事件",
            allowed_agents=["Continuity", "Auditor", "Writer"],
            input_schema={
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {"type": "string"},
                    "protected_texts": {"type": "array"},
                    "must_events": {"type": "array"},
                },
            },
        )
    )
    session.add(
        Skill(
            workspace_id="local",
            name="entity-lookup",
            version="1.0.0",
            description="按名称检索故事圣经实体（只读）",
            allowed_agents=["Writer", "Auditor", "Memory", "Plot", "Continuity"],
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        )
    )
    session.add(
        Skill(
            workspace_id="local",
            name="outline-generate",
            version="1.0.0",
            description="为大纲父节点生成下级节点草案（不写库，由 OutlineService 提交）",
            allowed_agents=["Outline", "Plot", "Writer"],
            input_schema={
                "type": "object",
                "required": ["child_kind", "count"],
                "properties": {
                    "child_kind": {"type": "string"},
                    "count": {"type": "integer"},
                    "novel": {"type": "object"},
                    "parent": {"type": "object"},
                    "existing_titles": {"type": "array"},
                    "start_chapter_index": {"type": "integer"},
                },
            },
            output_schema={"type": "object"},
        )
    )
    session.commit()
