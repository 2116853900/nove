from __future__ import annotations

import json
from typing import Any

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, parse_json_object, run_async


MEMORY_SYSTEM = """你是 Nove 的 Memory Agent。
从用户确认的章节正文中提取事实增量候选。只输出 JSON，不要解释。

schema:
{
  "events": [
    {
      "story_time": "故事内时间或相对顺序",
      "subjects": ["人物名"],
      "action": "发生了什么",
      "location": "地点",
      "consequences": "后果"
    }
  ],
  "entity_updates": [
    {
      "name": "实体名",
      "entity_type": "character|location|faction|item",
      "summary": "更新后的摘要",
      "facts": {"key": "value"}
    }
  ],
  "plot_threads": [
    {
      "name": "线索名",
      "kind": "foreshadowing|mystery|promise|conflict|relationship",
      "status": "PLANTED|DEVELOPING|READY_FOR_PAYOFF|PAID_OFF|ABANDONED",
      "latest": "本章进展"
    }
  ],
  "resolved_threads": ["已回收线索名"]
}

规则：
1. 只提取正文明确发生的事实，不把推测写成事实。
2. 事件 subjects 尽量使用正文中的人物名。
3. 没有变化时返回空数组，不要编造。
"""


class AgentScopeMemoryAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def extract(
        self,
        *,
        title: str,
        content: str,
        brief: dict[str, Any],
        existing_entities: list[dict[str, Any]],
        existing_threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return run_async(
            self._extract_async(
                title=title,
                content=content,
                brief=brief,
                existing_entities=existing_entities,
                existing_threads=existing_threads,
            )
        )

    async def _extract_async(
        self,
        *,
        title: str,
        content: str,
        brief: dict[str, Any],
        existing_entities: list[dict[str, Any]],
        existing_threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.0

            agent = Agent(
                name="Memory",
                system_prompt=MEMORY_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {
                "chapterTitle": title,
                "content": content,
                "chapterBrief": brief,
                "existingEntities": existing_entities,
                "existingPlotThreads": existing_threads,
            }
            reply = await agent.reply(
                UserMsg(
                    name="nove",
                    content="请提取事实增量候选，只返回 JSON：\n"
                    + json.dumps(payload, ensure_ascii=False),
                )
            )
            data = parse_json_object(extract_text(reply))
            return normalize_memory_delta(data)
        finally:
            await close_chat_model(model)


def heuristic_memory_delta(
    *,
    title: str,
    content: str,
    brief: dict[str, Any],
    chapter_index: int,
) -> dict[str, Any]:
    must = [e for e in (brief.get("must_events") or []) if e and e in content]
    events = []
    for index, action in enumerate(must or [f"推进了章节《{title}》"], start=1):
        events.append(
            {
                "story_time": f"第 {chapter_index} 章",
                "subjects": [],
                "action": action,
                "location": "",
                "consequences": "",
            }
        )
    return {
        "events": events,
        "entity_updates": [],
        "plot_threads": [],
        "resolved_threads": [],
        "source": "heuristic",
    }


def normalize_memory_delta(data: dict[str, Any]) -> dict[str, Any]:
    def as_list(key: str) -> list[Any]:
        value = data.get(key)
        return value if isinstance(value, list) else []

    events = []
    for item in as_list("events"):
        if not isinstance(item, dict) or not item.get("action"):
            continue
        subjects = item.get("subjects") if isinstance(item.get("subjects"), list) else []
        events.append(
            {
                "story_time": str(item.get("story_time") or ""),
                "subjects": [str(s) for s in subjects],
                "action": str(item.get("action")),
                "location": str(item.get("location") or ""),
                "consequences": str(item.get("consequences") or ""),
            }
        )

    entity_updates = []
    for item in as_list("entity_updates"):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        entity_updates.append(
            {
                "name": str(item.get("name")),
                "entity_type": str(item.get("entity_type") or "character"),
                "summary": str(item.get("summary") or ""),
                "facts": item.get("facts") if isinstance(item.get("facts"), dict) else {},
            }
        )

    threads = []
    for item in as_list("plot_threads"):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        status = str(item.get("status") or "DEVELOPING").upper()
        if status not in {
            "PLANTED",
            "DEVELOPING",
            "READY_FOR_PAYOFF",
            "PAID_OFF",
            "ABANDONED",
        }:
            status = "DEVELOPING"
        threads.append(
            {
                "name": str(item.get("name")),
                "kind": str(item.get("kind") or "mystery"),
                "status": status,
                "latest": str(item.get("latest") or ""),
            }
        )

    return {
        "events": events,
        "entity_updates": entity_updates,
        "plot_threads": threads,
        "resolved_threads": [str(x) for x in as_list("resolved_threads")],
        "source": "agentscope",
    }
