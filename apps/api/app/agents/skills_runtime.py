from __future__ import annotations

import json
import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Skill, SkillRun, StoryEntity, new_id


AGENT_ALIASES = {
    "Writer": {"Writer", "写作"},
    "Auditor": {"Auditor", "审计"},
    "Continuity": {"Continuity", "连续性"},
    "Plot": {"Plot", "大纲"},
    "Outline": {"Outline", "Plot", "大纲"},
    "Memory": {"Memory", "提取", "记忆"},
}

SYSTEM_SKILL_NAMES = {
    "continuity-check",
    "entity-lookup",
    "outline-generate",
    "outline-coherence",
}


def _agent_allowed(skill: Skill, agent_name: str) -> bool:
    allowed = set(skill.allowed_agents or [])
    if not allowed:
        return True
    aliases = AGENT_ALIASES.get(agent_name, {agent_name})
    return bool(allowed & aliases) or agent_name in allowed


class SkillRuntime:
    """Whitelist skill registry + execution log (no direct DB writes by skills)."""

    def __init__(self, session: Session, *, novel_id: str, chapter_id: str | None = None):
        self.session = session
        self.novel_id = novel_id
        self.chapter_id = chapter_id
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "continuity-check": self._continuity_check,
            "entity-lookup": self._entity_lookup,
            "outline-generate": self._outline_generate,
            "outline-coherence": self._outline_coherence,
        }

    def list_enabled(self, agent_name: str) -> list[Skill]:
        skills = self.session.scalars(select(Skill).where(Skill.enabled.is_(True))).all()
        return [s for s in skills if _agent_allowed(s, agent_name)]

    def invoke(
        self,
        *,
        skill_name: str,
        agent_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        skill = self.session.scalar(select(Skill).where(Skill.name == skill_name))
        if skill is None:
            return {"ok": False, "error": f"skill not found: {skill_name}"}

        started = time.perf_counter()
        status = "ok"
        error = None
        output: dict[str, Any]

        if not skill.enabled:
            status = "denied"
            error = f"skill disabled: {skill_name}"
            output = {"ok": False, "error": error}
        elif not _agent_allowed(skill, agent_name):
            status = "denied"
            error = f"agent {agent_name} not allowed for {skill_name}"
            output = {"ok": False, "error": error}
        else:
            handler = self._handlers.get(skill_name)
            try:
                if handler is None:
                    raise ValueError(f"no handler registered for skill {skill_name}")
                required = []
                props = (skill.input_schema or {}).get("required")
                if isinstance(props, list):
                    required = props
                missing = [key for key in required if key not in payload]
                if missing:
                    raise ValueError(f"missing required fields: {', '.join(missing)}")
                output = handler(payload)
                if not isinstance(output, dict):
                    raise ValueError("skill output must be an object")
                model_error = output.pop("_modelError", None)
                if model_error:
                    # Keep provider diagnostics in the server-side run record;
                    # callers receive only the generic modelFallback marker.
                    status = "fallback"
                    error = str(model_error)
            except Exception as exc:
                status = "error"
                error = str(exc)
                output = {"ok": False, "error": error}

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        run = SkillRun(
            workspace_id=skill.workspace_id,
            novel_id=self.novel_id,
            chapter_id=self.chapter_id,
            skill_id=skill.id,
            skill_name=skill.name,
            skill_version=skill.version,
            agent_name=agent_name,
            status=status,
            input_summary=json.dumps(payload, ensure_ascii=False)[:500],
            output_summary=json.dumps(output, ensure_ascii=False)[:500],
            duration_ms=elapsed_ms,
            error=error,
        )
        self.session.add(run)
        self.session.commit()
        return output

    def build_agentscope_toolkit(self, agent_name: str) -> Any | None:
        """Optional AgentScope Toolkit for allowed skills."""
        enabled = self.list_enabled(agent_name)
        if not enabled:
            return None
        try:
            from agentscope.tool import FunctionTool, Toolkit
        except Exception:
            return None

        tools = []
        runtime = self

        for skill in enabled:
            if skill.name not in self._handlers:
                continue

            def make_tool(skill_name: str):
                def _tool(**kwargs: Any) -> str:
                    result = runtime.invoke(
                        skill_name=skill_name,
                        agent_name=agent_name,
                        payload=dict(kwargs),
                    )
                    return json.dumps(result, ensure_ascii=False)

                _tool.__name__ = skill_name.replace("-", "_")
                _tool.__doc__ = skill.description or skill_name
                return FunctionTool(_tool, name=skill_name.replace("-", "_"), description=skill.description)

            tools.append(make_tool(skill.name))

        if not tools:
            return None
        return Toolkit(tools=tools)

    def _outline_generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Draft outline child nodes with the configured cloud model.

        Skills never write OutlineNode rows — caller (OutlineService) commits.
        """
        from .models import model_config_for_role
        from .outline import AgentScopeOutlineAgent, normalize_outline_nodes

        child_kind = str(payload.get("child_kind") or "chapter").strip()
        if child_kind not in {"volume", "arc", "chapter", "scene"}:
            return {"ok": False, "error": f"invalid child_kind: {child_kind}"}
        try:
            count = int(payload["count"]) if "count" in payload else 3
        except (TypeError, ValueError):
            return {"ok": False, "error": "count must be an integer"}
        count = max(0, min(200, count))

        novel = payload.get("novel") if isinstance(payload.get("novel"), dict) else {}
        parent = payload.get("parent") if isinstance(payload.get("parent"), dict) else None
        existing_titles = [
            str(t) for t in (payload.get("existing_titles") or []) if t is not None
        ]
        try:
            start_chapter_index = int(payload.get("start_chapter_index") or 1)
        except (TypeError, ValueError):
            start_chapter_index = 1
        characters = payload.get("characters") if isinstance(payload.get("characters"), list) else []
        locations = payload.get("locations") if isinstance(payload.get("locations"), list) else []
        rules = [str(r) for r in (payload.get("rules") or []) if r]
        prior = (
            payload.get("prior_chapter_briefs")
            if isinstance(payload.get("prior_chapter_briefs"), list)
            else []
        )
        mode = str(payload.get("mode") or "children")
        blueprint = (
            payload.get("blueprint")
            if isinstance(payload.get("blueprint"), dict)
            else {}
        )
        volume_plan = (
            payload.get("volume_plan")
            if isinstance(payload.get("volume_plan"), dict)
            else {}
        )
        arc_plan = (
            payload.get("arc_plan")
            if isinstance(payload.get("arc_plan"), dict)
            else {}
        )
        pacing = (
            payload.get("pacing")
            if isinstance(payload.get("pacing"), dict)
            else {}
        )
        unresolved = [
            str(item).strip()
            for item in (payload.get("unresolved_foreshadow") or [])
            if str(item).strip()
        ]

        config = model_config_for_role(self.session, self.novel_id, "大纲")
        if config is None:
            config = model_config_for_role(self.session, self.novel_id, "写作")
        if config is None:
            raise ValueError("请先连接可用的云端模型，再生成大纲。")
        try:
            raw = AgentScopeOutlineAgent(config).generate_children(
                novel=novel,
                parent=parent,
                child_kind=child_kind,
                count=count,
                existing_titles=existing_titles,
                start_chapter_index=start_chapter_index,
                characters=[c for c in characters if isinstance(c, dict)],
                locations=[location for location in locations if isinstance(location, dict)],
                rules=rules,
                prior_chapter_briefs=[p for p in prior if isinstance(p, dict)],
                mode=mode,
                blueprint=blueprint,
                volume_plan=volume_plan,
                arc_plan=arc_plan,
                pacing=pacing,
                unresolved_foreshadow=unresolved,
            )
        except Exception as exc:
            raise ValueError("云端模型未能生成大纲，请检查连接后重试。") from exc

        # Re-normalize to enforce kind/count even if model returned extras.
        nodes = normalize_outline_nodes(
            {"nodes": list(raw or [])}, child_kind=child_kind, count=count
        )
        if len(nodes) < count:
            raise ValueError("云端模型返回的大纲数量不足，请重试。")

        return {
            "ok": True,
            "source": "model",
            "childKind": child_kind,
            "count": len(nodes),
            "nodes": nodes,
        }

    def _outline_coherence(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Heuristic coherence check for a batch of outline drafts."""
        nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        existing_titles = [
            str(t).strip() for t in (payload.get("existing_titles") or []) if str(t).strip()
        ]
        prior = (
            payload.get("prior_chapter_briefs")
            if isinstance(payload.get("prior_chapter_briefs"), list)
            else []
        )
        volume_plan = (
            payload.get("volume_plan") if isinstance(payload.get("volume_plan"), dict) else {}
        )
        unresolved = [
            str(x).strip()
            for x in (payload.get("unresolved_foreshadow") or [])
            if str(x).strip()
        ]
        child_kind = str(payload.get("child_kind") or "").strip()
        issues: list[dict[str, Any]] = []

        goals: list[str] = []
        titles: list[str] = []
        highlights: list[str] = []
        plants_all: list[str] = []
        payoffs_all: list[str] = []
        for item in nodes:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            is_volume = child_kind == "volume"
            raw_goal = details.get("stage_goal") if is_volume else details.get("goal")
            goal = str(raw_goal or "").strip()
            must = details.get("must_events") or []
            hook = str(details.get("hook") or "").strip()
            highlight = str(details.get("highlight") or "").strip()
            twist = str(details.get("twist") or "").strip()
            plants = [str(x).strip() for x in (details.get("foreshadow_plant") or []) if str(x).strip()]
            payoffs = [str(x).strip() for x in (details.get("foreshadow_payoff") or []) if str(x).strip()]
            titles.append(title)
            goals.append(goal)
            highlights.append(highlight)
            plants_all.extend(plants)
            payoffs_all.extend(payoffs)

            if not goal:
                issues.append(
                    {
                        "severity": "major",
                        "title": title or "(无标题)",
                        "reason": "缺少分卷阶段目标 stage_goal"
                        if is_volume
                        else "缺少章节目标 goal",
                    }
                )
            if is_volume:
                if not str(details.get("arc_summary") or "").strip():
                    issues.append(
                        {
                            "severity": "major",
                            "title": title or "(无标题)",
                            "reason": "缺少分卷剧情梗概 arc_summary",
                        }
                    )
                if not details.get("key_turns"):
                    issues.append(
                        {
                            "severity": "minor",
                            "title": title or "(无标题)",
                            "reason": "缺少分卷关键转折 key_turns",
                        }
                    )
                try:
                    planned_chapters = int(details.get("planned_chapters") or 0)
                except (TypeError, ValueError):
                    planned_chapters = 0
                if planned_chapters < 1:
                    issues.append(
                        {
                            "severity": "major",
                            "title": title or "(无标题)",
                            "reason": "缺少有效的分卷章节预算 planned_chapters",
                        }
                    )
            if not is_volume and not must:
                issues.append(
                    {
                        "severity": "minor",
                        "title": title or "(无标题)",
                        "reason": "缺少必达事件 must_events",
                    }
                )
            if not is_volume and not highlight:
                issues.append(
                    {
                        "severity": "minor",
                        "title": title or "(无标题)",
                        "reason": "缺少亮点 highlight",
                    }
                )
            if not is_volume and not twist:
                issues.append(
                    {
                        "severity": "minor",
                        "title": title or "(无标题)",
                        "reason": "缺少转折 twist",
                    }
                )
            if not hook:
                issues.append(
                    {
                        "severity": "minor",
                        "title": title or "(无标题)",
                        "reason": "缺少章末钩子 hook",
                    }
                )
            if title and title in existing_titles:
                issues.append(
                    {
                        "severity": "major",
                        "title": title,
                        "reason": "标题与已有大纲节点重复",
                    }
                )

        # Adjacent goals must advance rather than paraphrase one another.
        def _norm(s: str) -> str:
            return "".join(ch for ch in s if ch.isalnum())

        for i in range(1, len(goals)):
            a, b = _norm(goals[i - 1]), _norm(goals[i])
            if not a or not b:
                continue
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if len(shorter) >= 6 and shorter in longer:
                issues.append(
                    {
                        "severity": "major",
                        "title": titles[i] or f"节点{i + 1}",
                        "reason": f"目标与上一节点高度相似，缺少递进",
                    }
                )

        # Compare first new goal against last prior brief.
        if prior and goals:
            last = prior[-1] if isinstance(prior[-1], dict) else {}
            prev_goal = _norm(str(last.get("goal") or ""))
            first = _norm(goals[0])
            if prev_goal and first and len(first) >= 6 and (first in prev_goal or prev_goal in first):
                issues.append(
                    {
                        "severity": "major",
                        "title": titles[0] or "首个新节点",
                        "reason": "目标与已有最近章节过于接近",
                    }
                )

        # 网文专项：章节目标是否服务所属卷 stage_goal。
        if child_kind == "chapter" and volume_plan:
            stage_goal = _norm(str(volume_plan.get("stage_goal") or ""))
            if stage_goal:
                stage_terms = {t for t in _split_terms(str(volume_plan.get("stage_goal") or "")) if len(t) >= 2}
                served = 0
                for goal in goals:
                    if not goal:
                        continue
                    gnorm = _norm(goal)
                    if any(term in goal for term in stage_terms) or (
                        len(stage_goal) >= 6 and (stage_goal in gnorm or gnorm in stage_goal)
                    ):
                        served += 1
                # If a batch of chapters barely relates to the volume goal, flag it.
                if goals and served == 0:
                    issues.append(
                        {
                            "severity": "major",
                            "title": titles[0] if titles else "本批章节",
                            "reason": "整批章节目标未体现所属卷的阶段目标 stage_goal",
                        }
                    )

        # 网文专项：爽点（highlight）连续雷同 —— 强度/套路缺乏起伏。
        for i in range(1, len(highlights)):
            a, b = _norm(highlights[i - 1]), _norm(highlights[i])
            if not a or not b:
                continue
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if len(shorter) >= 6 and shorter in longer:
                issues.append(
                    {
                        "severity": "minor",
                        "title": titles[i] or f"节点{i + 1}",
                        "reason": "爽点与上一章高度雷同，缺少强度/套路递进",
                    }
                )

        # 网文专项：伏笔去向 —— 本批埋下的伏笔若数量偏多而全无回收标注，提示。
        if child_kind == "chapter" and len(nodes) >= 3:
            if plants_all and not payoffs_all and not unresolved:
                issues.append(
                    {
                        "severity": "minor",
                        "title": titles[0] if titles else "本批章节",
                        "reason": "本批只埋伏笔无任何回收，注意后续安排回收节点",
                    }
                )

        major = sum(1 for i in issues if i.get("severity") == "major")
        score = max(0, 100 - major * 15 - (len(issues) - major) * 5)
        return {
            "ok": True,
            "issue_count": len(issues),
            "issues": issues[:40],
            "score": score,
            "pass": major == 0,
        }

    def _entity_lookup(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "name required"}
        entities = self.session.scalars(
            select(StoryEntity).where(StoryEntity.novel_id == self.novel_id)
        ).all()
        hits = [
            {
                "id": item.id,
                "type": item.entity_type,
                "name": item.name,
                "summary": item.summary,
                "facts": item.data,
            }
            for item in entities
            if name in item.name or item.name in name
        ]
        return {"ok": True, "matches": hits}

    def _continuity_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = str(payload.get("content") or "")
        protected = payload.get("protected_texts") or []
        must_events = payload.get("must_events") or []
        forbidden_events = payload.get("forbidden_events") or []
        chapter_index = int(payload.get("chapter_index") or 0)
        issues: list[dict[str, Any]] = []

        for text in protected:
            if text and text not in content:
                issues.append(
                    {
                        "severity": "fatal",
                        "type": "锁定内容",
                        "evidence": str(text)[:120],
                        "reason": "锁定原文缺失",
                    }
                )
        if "早就知道" in content:
            issues.append(
                {
                    "severity": "fatal",
                    "type": "知识边界",
                    "evidence": "早就知道",
                    "reason": "疑似知识泄漏",
                }
            )
        for event in must_events:
            if event and event not in content:
                issues.append(
                    {
                        "severity": "major",
                        "type": "大纲完成度",
                        "evidence": f"缺失：{event}",
                        "reason": "必达事件未出现",
                    }
                )

        for event in forbidden_events:
            if event and event in content:
                issues.append(
                    {
                        "severity": "fatal",
                        "type": "禁止事件",
                        "evidence": str(event)[:120],
                        "reason": "正文出现本章大纲明确禁止的事件",
                        "source": "chapter.brief.forbidden_events",
                    }
                )

        # Structured state checks (death / destroyed locations / knowledge).
        try:
            from ..services_state import StateService

            state_issues = StateService(self.session).continuity_issues_from_states(
                novel_id=self.novel_id,
                chapter_index=chapter_index,
                content=content,
            )
            issues.extend(state_issues)
        except Exception:
            pass

        # Dedupe by type+evidence.
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for item in issues:
            key = (str(item.get("type") or ""), str(item.get("evidence") or "")[:80])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return {
            "ok": True,
            "issue_count": len(unique),
            "issues": unique,
            "pass": not any(i["severity"] == "fatal" for i in unique),
        }


def ensure_default_skills(session: Session, workspace_id: str = "local") -> None:
    """Idempotently ensure runtime skills exist (safe for existing DBs)."""
    specs = [
        {
            "name": "continuity-check",
            "version": "1.1.0",
            "description": "检查锁定内容、知识边界与必达事件",
            "allowed_agents": ["Continuity", "Auditor", "Writer"],
            "input_schema": {
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {"type": "string"},
                    "protected_texts": {"type": "array"},
                    "must_events": {"type": "array"},
                    "forbidden_events": {"type": "array"},
                },
            },
            "output_schema": {"type": "object"},
        },
        {
            "name": "entity-lookup",
            "version": "1.0.0",
            "description": "按名称检索故事圣经实体（只读）",
            "allowed_agents": ["Writer", "Auditor", "Memory", "Plot", "Continuity"],
            "input_schema": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
            "output_schema": {"type": "object"},
        },
        {
            "name": "outline-generate",
            "version": "1.3.0",
            "description": "为大纲父节点生成下级节点草案（不写库，由 OutlineService 提交）",
            "allowed_agents": ["Outline", "Plot", "Writer"],
            "input_schema": {
                "type": "object",
                "required": ["child_kind", "count"],
                "properties": {
                    "child_kind": {
                        "type": "string",
                        "description": "volume|arc|chapter|scene",
                    },
                    "count": {"type": "integer"},
                    "novel": {"type": "object"},
                    "parent": {"type": "object"},
                    "existing_titles": {"type": "array"},
                    "start_chapter_index": {"type": "integer"},
                    "characters": {"type": "array"},
                    "locations": {"type": "array"},
                    "rules": {"type": "array"},
                    "prior_chapter_briefs": {"type": "array"},
                    "mode": {"type": "string"},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "source": {"type": "string"},
                    "nodes": {"type": "array"},
                },
            },
        },
        {
            "name": "outline-coherence",
            "version": "1.0.0",
            "description": "检查一批大纲草案的目标递进、重复与必填字段",
            "allowed_agents": ["Outline", "Plot", "Continuity", "Auditor"],
            "input_schema": {
                "type": "object",
                "required": ["nodes"],
                "properties": {
                    "nodes": {"type": "array"},
                    "existing_titles": {"type": "array"},
                    "prior_chapter_briefs": {"type": "array"},
                },
            },
            "output_schema": {"type": "object"},
        },
    ]
    for spec in specs:
        spec["input_schema"] = {**spec["input_schema"], "x-nove-origin": "system"}
        existing = session.scalar(select(Skill).where(Skill.name == spec["name"]))
        if existing:
            existing.version = spec["version"]
            existing.description = spec["description"]
            existing.allowed_agents = spec["allowed_agents"]
            existing.input_schema = spec["input_schema"]
            existing.output_schema = spec["output_schema"]
            existing.enabled = True
            continue
        session.add(
            Skill(
                id=new_id(),
                workspace_id=workspace_id,
                name=spec["name"],
                version=spec["version"],
                description=spec["description"],
                allowed_agents=spec["allowed_agents"],
                input_schema=spec["input_schema"],
                output_schema=spec["output_schema"],
                enabled=True,
            )
        )
    session.commit()
