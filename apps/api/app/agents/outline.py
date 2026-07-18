from __future__ import annotations

import json
from typing import Any

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, parse_json_object, run_async


OUTLINE_SYSTEM = """你是 Nove 的 Outline Agent，为长篇中文网络小说展开结构化大纲。
你严格遵循自顶向下的层级：故事蓝图(blueprint) → 分卷规划(volume) → 剧情阶段(arc) → 分章细纲(chapter) → 场景(scene)。
下级节点必须服务于上级的目标与节奏，不可脱离蓝图与所属卷的规划。
只输出 JSON，不要解释。

按 childKind 使用对应 schema：

【当 childKind = volume】每个 volume 是一个完整叙事阶段（通常 40-80 章，除全书本身较短外严禁超过 100 章）：
{
  "nodes": [
    {
      "kind": "volume",
      "title": "第 N 卷 · 卷名",
      "details": {
        "stage_goal": "本卷阶段目标（主角在本卷要达成/改变什么）",
        "power_level": "本卷主角实力/处境基线与终点（体现沿力量体系的升级）",
        "arc_summary": "本卷剧情梗概（2-3 句：起因→发展→高潮）",
        "planned_chapters": 60,
        "key_turns": ["起：开局处境", "承：矛盾升级", "转：关键反转", "合：卷末高潮与新钩子"],
        "core_conflict": "本卷核心矛盾",
        "foreshadow_plant": ["本卷埋下的伏笔"],
        "foreshadow_payoff": ["本卷回收的前置伏笔"],
        "characters": ["本卷重点出场人物"],
        "locations": ["本卷重点出场地点"],
        "plot_arcs": ["剧情阶段 1：本卷内的阶段推进", "剧情阶段 2：中段升级或反转", "剧情阶段 3：卷末高潮"],
        "hook": "卷末钩子（引向下一卷）"
      }
    }
  ]
}

【当 childKind = arc】每个剧情阶段必须是卷内可独立推进的一段，不要把整卷拆成同义反复：
{
  "nodes": [
    {
      "kind": "arc",
      "title": "剧情阶段 · 短标题",
      "details": {
        "goal": "本剧情阶段要完成的明确推进",
        "conflict": "阻碍目标的核心矛盾",
        "planned_chapters": 12,
        "opening_state": "弧线开始时的局面/人物状态",
        "turning_points": ["中段升级或反转", "弧末不可逆变化"],
        "closing_state": "弧线结束后局面如何改变，并为下一弧留下什么",
        "must_events": ["弧线必须发生的事件"],
        "forbidden_events": ["本弧不能提前揭开的信息"],
        "characters": ["本剧情阶段重点出场人物"],
        "locations": ["本剧情阶段重点出场地点"],
        "highlight": "本弧核心高光",
        "twist": "本弧核心转折",
        "hook": "引向下一弧的钩子"
      }
    }
  ]
}

【当 childKind = chapter 或 scene】：
{
  "nodes": [
    {
      "kind": "arc|chapter|scene",
      "title": "节点标题",
       "details": {
         "goal": "本章/节点目标（一句话，须服务所属卷 stage_goal 且与前后章递进）",
         "conflict": "核心冲突",
         "obstacle": "阻碍目标的具体人/资源/信息限制",
         "cost": "本章选择产生的不可忽略代价",
         "time_anchor": "故事内明确时间锚点",
         "chapter_span": "本章覆盖的故事时间跨度",
         "gap_from_previous": "与上一章的故事时间差；闪回必须明确标注",
         "countdown": "倒计时状态；没有则写无",
         "must_events": ["必达事件1", "必达事件2"],
         "forbidden_events": ["禁止雷点或勿提前揭秘"],
         "cbn": "主体 | 开场动作/变化 | 对象/结果",
         "cpns": ["主体 | 中段推进 | 对象/结果", "主体 | 中段转折 | 对象/结果"],
         "cen": "主体 | 收束动作/变化 | 对象/结果",
         "must_cover_nodes": ["最多4个，优先 CBN、CEN 与核心 CPN"],
         "forbidden_zones": ["最多5个本章绝对不能发生的事件"],
         "highlight": "本章亮点（爽点/名场面/情绪高点，须落地为具体事件，一句话）",
         "twist": "本章转折（预期被打破或局势反转，一句话）",
         "hook": "章末钩子/悬念",
         "chapter_end_open_question": "章末尚未闭合、能自然承接下一章的问题",
         "strand": "本章主导线：主线/感情/成长/悬疑等",
         "antagonist_level": "本章对手层级及其目标",
         "pov_character": "本章视角角色",
         "chapter_change": "章末相较章初发生的可验证变化",
         "foreshadow_plant": ["本章埋下的伏笔（可空）"],
        "foreshadow_payoff": ["本章回收的伏笔（可空）"],
        "characters": ["出场人物"],
        "locations": ["出场地点"]
      }
    }
  ]
}

通用规则：
1. kind 必须与请求的 childKind 一致；count 大于 0 时数量严格遵循 count。count = 0 时由你自主规划合理数量：
   - volume：根据 blueprint 的阶段变化、力量成长、核心冲突升级、高潮与收束判断自然卷界，不可机械按固定章数切分，也不可为了省事压缩成少数超长卷；通常 4-10 卷。
   - arc：根据 volumePlan.planned_chapters 自主规划，通常 3-8 条。
   自主规划时，每个节点的 planned_chapters 必须合理，合计贴近上级总章数。
2. 章节标题优先「第 N 章 · 短标题」，N 从 startChapterIndex 连续递增。
3. 只生成新草案，不改写 existingTitles 中的已有节点。
4. 充分利用 blueprint（故事蓝图）、volumePlan（所属卷规划）、characters / locations / rules / priorChapterBriefs。
5. 所有内容必须贴合 blueprint：主角目标/动机/金手指、核心矛盾、世界观、力量体系。
6. 当生成 volume 时，planned_chapters 必须为正整数；所有分卷之和应贴近 novel.plannedChapters。严禁把 400 章长篇压缩成两三个 100 章以上的超长卷。blueprint.arcs_outline 已给出顶层叙事阶段时，应优先让每个阶段对应一卷，再根据阶段内容合理分配不同章数。
7. 当生成 arc 时，planned_chapters 必须为正整数；所有剧情阶段之和应贴近 volumePlan.planned_chapters。
8. 生成 volume 或 arc 时，characters 和 locations 必须列出该阶段实际会出场的重点人物与地点；生成 volume 时还必须给出 3-5 条 plot_arcs，用于后续创建正式剧情阶段节点。
8.1 当 mode = master_outline_enrich 时，只补全 volumePlan 指定的这一卷；保持其卷名、阶段目标与 planned_chapters，不得生成其他卷或改写全书分卷结构。

网文专项规则（生成 chapter 时务必遵守）：
9. 每章必须服务 volumePlan.stage_goal 与 arcPlan.goal，并在卷的 key_turns 节奏中找准自己的位置。
10. 按 pacingPlan 中与当前节点序号对应的节奏位置调整强度：
   - 铺垫期(setup)：埋线、积累、制造压迫感，highlight 可较克制但须留钩子；
   - 升级期(build)：冲突与实力逐级抬升，爽点递增，避免与前章同强度重复；
   - 高潮期(climax)：兑现前期铺垫，爆发式爽点/打脸/翻盘，情绪拉满；
   - 收尾期(resolve)：结算收益（地位/资源/关系提升），并抛出下一阶段钩子。
11. 爽点须遵循 blueprint.satisfaction_loop 的节拍循环，且必须落地为具体事件（谁对谁做了什么、结果如何），不能只写"很爽"。
12. 爽点强度要有起伏递进，严禁连续多章相同套路、相同强度（读者会疲劳）。
13. 章末 hook 强制非空，制造"必须追读下一章"的悬念或期待。
14. 伏笔管理：优先回收 unresolvedForeshadow 中列出的未回收伏笔；新埋的伏笔要在 foreshadow_plant 标注，便于后续回收。
15. 批量生成时整体呈现"铺垫→升级→转折→高潮→收尾"的完整节奏曲线，避免流水账与原地打转。
16. 每章固定 1 个 CBN、2-4 个按时间顺序排列的 CPN、1 个 CEN；节点统一使用“主体 | 动作/变化 | 对象/结果”。
17. 相邻章节必须满足“上一章 CEN 能导致下一章 CBN”；必须覆盖节点不超过 4 个，本章禁区不超过 5 个。
18. 时间锚点与章内跨度必须非空；时间回跳只能在 gap_from_previous 明确标注闪回时使用，倒计时算术必须连续。
19. 每章都要写出阻力、代价和章末可验证变化，不能只有目标、爽点和钩子。
"""


class AgentScopeOutlineAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def generate_children(
        self,
        *,
        novel: dict[str, Any],
        parent: dict[str, Any] | None,
        child_kind: str,
        count: int,
        existing_titles: list[str],
        start_chapter_index: int = 1,
        characters: list[dict[str, Any]] | None = None,
        locations: list[dict[str, Any]] | None = None,
        rules: list[str] | None = None,
        prior_chapter_briefs: list[dict[str, Any]] | None = None,
        mode: str = "children",
        blueprint: dict[str, Any] | None = None,
        volume_plan: dict[str, Any] | None = None,
        arc_plan: dict[str, Any] | None = None,
        pacing: dict[str, Any] | None = None,
        unresolved_foreshadow: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return run_async(
            self._generate_async(
                novel=novel,
                parent=parent,
                child_kind=child_kind,
                count=count,
                existing_titles=existing_titles,
                start_chapter_index=start_chapter_index,
                characters=characters or [],
                locations=locations or [],
                rules=rules or [],
                prior_chapter_briefs=prior_chapter_briefs or [],
                mode=mode,
                blueprint=blueprint or {},
                volume_plan=volume_plan or {},
                arc_plan=arc_plan or {},
                pacing=pacing or {},
                unresolved_foreshadow=unresolved_foreshadow or [],
            )
        )

    async def _generate_async(
        self,
        *,
        novel: dict[str, Any],
        parent: dict[str, Any] | None,
        child_kind: str,
        count: int,
        existing_titles: list[str],
        start_chapter_index: int,
        characters: list[dict[str, Any]],
        locations: list[dict[str, Any]],
        rules: list[str],
        prior_chapter_briefs: list[dict[str, Any]],
        mode: str,
        blueprint: dict[str, Any],
        volume_plan: dict[str, Any],
        arc_plan: dict[str, Any],
        pacing: dict[str, Any],
        unresolved_foreshadow: list[str],
    ) -> list[dict[str, Any]]:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.4

            agent = Agent(
                name="Outline",
                system_prompt=OUTLINE_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {
                "mode": mode,
                "novel": novel,
                "blueprint": blueprint or None,
                "volumePlan": volume_plan or None,
                "arcPlan": arc_plan or None,
                "pacing": pacing or None,
                "pacingPlan": (pacing.get("nodes") or [])[:30],
                "unresolvedForeshadow": (unresolved_foreshadow or [])[:20],
                "parent": parent,
                "childKind": child_kind,
                "count": count,
                "startChapterIndex": start_chapter_index,
                "existingTitles": existing_titles,
                "characters": characters[:20],
                "locations": locations[:20],
                "rules": rules[:15],
                "priorChapterBriefs": prior_chapter_briefs[:12],
            }

            async def request_nodes(
                request_payload: dict[str, Any], expected_count: int
            ) -> list[dict[str, Any]]:
                reply = await agent.reply(
                    UserMsg(
                        name="nove",
                        content="请生成下级大纲节点，只返回 JSON：\n"
                        + json.dumps(request_payload, ensure_ascii=False),
                    )
                )
                return normalize_outline_nodes(
                    parse_json_object(extract_text(reply)),
                    child_kind=child_kind,
                    count=expected_count,
                )

            # Chapter batches can exceed a provider's reliable JSON output budget. Generate
            # them serially so each call has one small, independently valid response.
            if mode == "batch_chapters" and child_kind == "chapter" and count > 1:
                nodes: list[dict[str, Any]] = []
                titles = list(existing_titles)
                briefs = list(prior_chapter_briefs)
                pacing_plan = list(pacing.get("nodes") or [])
                for offset in range(count):
                    chapter_payload = dict(payload)
                    chapter_payload["count"] = 1
                    chapter_payload["startChapterIndex"] = start_chapter_index + offset
                    chapter_payload["existingTitles"] = titles
                    chapter_payload["priorChapterBriefs"] = briefs[-12:]
                    chapter_payload["pacingPlan"] = pacing_plan[offset : offset + 1]
                    generated = await request_nodes(chapter_payload, 1)
                    if not generated:
                        raise ValueError("configured model returned no valid outline node")
                    node = generated[0]
                    nodes.append(node)
                    titles.append(node["title"])
                    briefs.append(
                        {
                            "title": node["title"],
                            "goal": node["details"].get("goal", ""),
                            "twist": node["details"].get("twist", ""),
                            "hook": node["details"].get("hook", ""),
                            "cen": node["details"].get("cen", ""),
                            "time_anchor": node["details"].get("time_anchor", ""),
                        }
                    )
                return nodes

            return await request_nodes(payload, count)
        finally:
            await close_chat_model(model)


def heuristic_outline_children(
    *,
    novel: dict[str, Any],
    parent: dict[str, Any] | None,
    child_kind: str,
    count: int,
    existing_titles: list[str],
    start_chapter_index: int = 1,
    characters: list[dict[str, Any]] | None = None,
    locations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    idea = str(novel.get("coreIdea") or novel.get("title") or "主线推进")
    parent_title = str((parent or {}).get("title") or "总纲")
    try:
        total_chapters = max(1, int(novel.get("plannedChapters") or 80))
    except (TypeError, ValueError):
        total_chapters = 80
    parent_details = (parent or {}).get("details") or {}
    character_names = _clean_list([item.get("name") for item in characters or []])
    location_names = _clean_list([item.get("name") for item in locations or []])
    try:
        parent_budget = max(1, int(parent_details.get("planned_chapters") or total_chapters))
    except (AttributeError, TypeError, ValueError):
        parent_budget = total_chapters
    if count <= 0:
        # Keep offline fallback usable when autonomous planning has no model.
        if child_kind == "arc":
            count = max(1, min(12, round(parent_budget / 12)))
        elif child_kind == "volume":
            count = max(1, min(12, round(total_chapters / 60)))
        else:
            count = 1
    nodes: list[dict[str, Any]] = []
    for i in range(count):
        n = i + 1
        if child_kind == "volume":
            vol_no = len(existing_titles) + n
            title = f"第 {vol_no} 卷 · {idea[:12]}"
            details = {
                "stage_goal": f"围绕「{idea}」推进到第 {vol_no} 阶段，主角处境与实力再上一台阶",
                "power_level": f"由第 {vol_no} 阶段起点逐级突破至阶段终点",
                "arc_summary": f"起因：承接上一阶段遗留矛盾；发展：围绕「{idea}」冲突升级；高潮：阶段性反转与突破",
                "planned_chapters": max(1, total_chapters // max(1, count)),
                "key_turns": [
                    "起：确立本卷处境与新目标",
                    "承：矛盾与压力逐级升级",
                    "转：关键反转打破预期",
                    "合：卷末高潮兑现并抛出新钩子",
                ],
                "core_conflict": "外部压制与主角突破诉求的对抗",
                "foreshadow_plant": [f"第 {vol_no} 卷埋下的伏笔"],
                "foreshadow_payoff": [],
                "characters": character_names[:6],
                "locations": location_names[:4],
                "plot_arcs": [
                    "开局：确立本卷目标与阻力",
                    "中段：矛盾升级并发生关键反转",
                    "收束：卷末高潮兑现并抛出新钩子",
                ],
                "hook": "卷末抛出新谜团，引向下一卷",
            }
        elif child_kind == "arc":
            title = f"剧情阶段 · {parent_title.split('·')[-1].strip()[:8]}·线{n}"
            details = {
                "goal": f"在「{parent_title}」内完成一段完整冲突",
                "conflict": "目标与代价的拉扯",
                "planned_chapters": max(1, parent_budget // max(1, count)),
                "opening_state": "承接上一阶段的压力与目标",
                "turning_points": [f"弧线关键转折 {n}"],
                "closing_state": "局面发生不可逆改变，逼迫进入下一阶段",
                "must_events": [f"弧线关键转折 {n}"],
                "forbidden_events": [],
                "characters": character_names[:6],
                "locations": location_names[:4],
                "highlight": f"弧线高光场面 {n}",
                "twist": f"弧线关键反转 {n}",
                "hook": "引向下一弧",
            }
        elif child_kind == "scene":
            title = f"场景 {n}"
            details = {
                "goal": f"推进父节点目标的第 {n} 步",
                "conflict": "信息差或时间压力",
                "must_events": [f"完成场景动作 {n}"],
                "forbidden_events": [],
                "highlight": f"场景高光动作 {n}",
                "twist": f"场景内小反转 {n}",
                "hook": "",
            }
        else:
            idx = start_chapter_index + i
            title = f"第 {idx} 章 · 未命名推进 {n}"
            details = {
                "goal": f"围绕「{idea}」推进一章",
                "conflict": "资源/信任/信息不足",
                "obstacle": "关键资源不足且对手先一步行动",
                "cost": "主角必须消耗资源或暴露一项弱点",
                "time_anchor": f"主线推进第 {idx} 节点",
                "chapter_span": "连续数小时",
                "gap_from_previous": "紧接上一章",
                "countdown": "无",
                "must_events": [f"本章关键事件 {n}"],
                "forbidden_events": [],
                "cbn": f"主角 | 承接上一章压力并确定目标 | 进入第 {idx} 章行动",
                "cpns": [
                    f"主角 | 尝试推进但遭遇阻力 | 暴露第 {n} 个限制",
                    f"对手 | 利用限制施压 | 迫使主角付出代价",
                ],
                "cen": f"主角 | 完成阶段动作并承担后果 | 局面转入下一章",
                "must_cover_nodes": [f"本章关键事件 {n}"],
                "forbidden_zones": [],
                "highlight": f"本章高光：围绕「{idea}」的一次情绪释放",
                "twist": f"局面小幅翻转：原计划受阻并被迫改道",
                "hook": "留下下一章压力",
                "chapter_end_open_question": "新的压力将如何解决",
                "strand": "主线",
                "antagonist_level": "当前阶段对手",
                "pov_character": character_names[0] if character_names else "主角",
                "chapter_change": "主角获得进展，同时新增一项明确代价",
                "foreshadow_plant": [],
                "foreshadow_payoff": [],
                "characters": [],
                "locations": [],
            }
        nodes.append({"kind": child_kind, "title": title, "details": details})
    return nodes


def _clean_list(value: Any) -> list[str]:
    return [str(x).strip() for x in (value or []) if str(x).strip()]


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _normalize_volume_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_goal": str(details.get("stage_goal") or details.get("goal") or ""),
        "power_level": str(details.get("power_level") or ""),
        "arc_summary": str(details.get("arc_summary") or ""),
        "planned_chapters": _positive_int(details.get("planned_chapters")),
        "key_turns": _clean_list(details.get("key_turns")),
        "core_conflict": str(details.get("core_conflict") or details.get("conflict") or ""),
        "foreshadow_plant": _clean_list(details.get("foreshadow_plant")),
        "foreshadow_payoff": _clean_list(details.get("foreshadow_payoff")),
        "characters": _clean_list(details.get("characters")),
        "locations": _clean_list(details.get("locations")),
        "plot_arcs": _clean_list(details.get("plot_arcs")),
        "hook": str(details.get("hook") or ""),
    }


def _normalize_node_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": str(details.get("goal") or ""),
        "conflict": str(details.get("conflict") or ""),
        "obstacle": str(details.get("obstacle") or details.get("conflict") or ""),
        "cost": str(details.get("cost") or ""),
        "time_anchor": str(details.get("time_anchor") or ""),
        "chapter_span": str(details.get("chapter_span") or ""),
        "gap_from_previous": str(details.get("gap_from_previous") or ""),
        "countdown": str(details.get("countdown") or ""),
        "must_events": _clean_list(details.get("must_events")),
        "forbidden_events": _clean_list(details.get("forbidden_events")),
        "cbn": str(details.get("cbn") or details.get("CBN") or ""),
        "cpns": _clean_list(details.get("cpns") or details.get("CPNs"))[:4],
        "cen": str(details.get("cen") or details.get("CEN") or ""),
        "must_cover_nodes": _clean_list(
            details.get("must_cover_nodes") or details.get("must_events")
        )[:8],
        "forbidden_zones": _clean_list(
            details.get("forbidden_zones") or details.get("forbidden_events")
        )[:10],
        "highlight": str(details.get("highlight") or ""),
        "twist": str(details.get("twist") or ""),
        "hook": str(details.get("hook") or ""),
        "chapter_end_open_question": str(
            details.get("chapter_end_open_question") or details.get("hook") or ""
        ),
        "strand": str(details.get("strand") or ""),
        "antagonist_level": str(details.get("antagonist_level") or ""),
        "pov_character": str(details.get("pov_character") or ""),
        "chapter_change": str(details.get("chapter_change") or ""),
        "foreshadow_plant": _clean_list(details.get("foreshadow_plant")),
        "foreshadow_payoff": _clean_list(details.get("foreshadow_payoff")),
        "characters": _clean_list(details.get("characters")),
        "locations": _clean_list(details.get("locations")),
        "planned_chapters": _positive_int(details.get("planned_chapters")),
        "opening_state": str(details.get("opening_state") or ""),
        "turning_points": _clean_list(details.get("turning_points")),
        "closing_state": str(details.get("closing_state") or ""),
        "pacing": details.get("pacing") if isinstance(details.get("pacing"), dict) else {},
    }


def normalize_outline_nodes(
    data: dict[str, Any], *, child_kind: str, count: int
) -> list[dict[str, Any]]:
    raw = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    nodes: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or child_kind)
        if kind != child_kind:
            kind = child_kind
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        normalized = (
            _normalize_volume_details(details)
            if kind == "volume"
            else _normalize_node_details(details)
        )
        nodes.append({"kind": kind, "title": title, "details": normalized})
        if count > 0 and len(nodes) >= count:
            break
    return nodes
