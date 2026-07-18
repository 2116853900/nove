from __future__ import annotations

import json
from typing import Any

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, parse_json_object, run_async


PLOT_SYSTEM = """你是 Nove 的 Plot Agent，负责把章节任务拆成可执行的场景节拍。
只输出 JSON，不要解释。

schema:
{
  "beats": [
    {
      "order": 1,
      "scene": "场景地点",
      "goal": "本拍目标",
      "conflict": "冲突",
      "action": "关键动作",
      "turn": "转折或信息变化",
      "exit": "如何进入下一拍"
    }
  ],
  "hook": "章末钩子",
  "must_cover": ["必达事件列表"],
  "avoid": ["禁止内容"]
}

要求：
1. 3-6 个节拍，顺序推进。
2. 覆盖 must_events，不触碰 forbidden_events。
3. 考虑出场人物与未解决剧情线。
4. 若写作合同包含 CBN/CPNs/CEN，节拍必须逐项承接，不能另起一套剧情。
5. 每拍写清目标、阻力、动作、变化与退出条件；最终拍落实章末未闭合问题。
"""


class AgentScopePlotAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def plan(self, *, title: str, brief: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return run_async(self._plan_async(title=title, brief=brief, context=context))

    async def _plan_async(
        self, *, title: str, brief: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.4

            agent = Agent(
                name="Plot",
                system_prompt=PLOT_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {
                "chapterTitle": title,
                "chapterBrief": {k: v for k, v in brief.items() if k != "_context"},
                "authoritativeContext": context,
            }
            reply = await agent.reply(
                UserMsg(
                    name="nove",
                    content="请规划本章场景节拍，只返回 JSON：\n"
                    + json.dumps(payload, ensure_ascii=False),
                )
            )
            data = parse_json_object(extract_text(reply))
            return normalize_plot_plan(data, brief=brief)
        finally:
            await close_chat_model(model)


def heuristic_plot_plan(*, title: str, brief: dict[str, Any]) -> dict[str, Any]:
    goal = brief.get("goal") or "推动当前冲突"
    conflict = brief.get("conflict") or "信息不足与时间压力"
    must = list(brief.get("must_events") or [])
    forbidden = list(brief.get("forbidden_events") or [])
    hook = brief.get("hook") or "留下未解的新压力"
    beats = [
        {
            "order": 1,
            "scene": "开场场景",
            "goal": f"建立处境：{goal}",
            "conflict": conflict,
            "action": "人物进入局面并感知压力",
            "turn": "暴露一个新线索或限制",
            "exit": "被迫作出初步选择",
        },
        {
            "order": 2,
            "scene": "对抗升级",
            "goal": "执行关键行动",
            "conflict": "代价开始显现",
            "action": must[0] if must else "推进核心事件",
            "turn": "判断出现裂缝",
            "exit": "进入后果阶段",
        },
        {
            "order": 3,
            "scene": "收束与钩子",
            "goal": "落实本章变化",
            "conflict": "旧方案失效",
            "action": must[1] if len(must) > 1 else "人物承担后果",
            "turn": hook,
            "exit": "指向下一章压力",
        },
    ]
    return {
        "beats": beats,
        "hook": hook,
        "must_cover": must,
        "avoid": forbidden,
        "source": "heuristic",
        "title": title,
    }


def normalize_plot_plan(data: dict[str, Any], *, brief: dict[str, Any]) -> dict[str, Any]:
    beats_raw = data.get("beats") if isinstance(data.get("beats"), list) else []
    beats: list[dict[str, Any]] = []
    for index, item in enumerate(beats_raw, start=1):
        if not isinstance(item, dict):
            continue
        beats.append(
            {
                "order": int(item.get("order") or index),
                "scene": str(item.get("scene") or f"场景 {index}"),
                "goal": str(item.get("goal") or ""),
                "conflict": str(item.get("conflict") or ""),
                "action": str(item.get("action") or ""),
                "turn": str(item.get("turn") or ""),
                "exit": str(item.get("exit") or ""),
            }
        )
    if not beats:
        return heuristic_plot_plan(title="", brief=brief)
    return {
        "beats": beats,
        "hook": str(data.get("hook") or brief.get("hook") or ""),
        "must_cover": list(data.get("must_cover") or brief.get("must_events") or []),
        "avoid": list(data.get("avoid") or brief.get("forbidden_events") or []),
        "source": "agentscope",
    }
