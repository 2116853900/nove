from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, parse_json_object, run_async


class CharacterDraft(TypedDict):
    name: str
    role: str
    summary: str
    goal: str
    flaw: str
    voice: str
    relationship_to_protagonist: str
    status: str


class CharacterBibleDraft(TypedDict):
    characters: list[CharacterDraft]


class LocationDraft(TypedDict):
    name: str
    region: str
    state: str
    summary: str
    depth: int


class FactionDraft(TypedDict):
    name: str
    kind: str
    stance: str
    power: str
    summary: str


class RuleDraft(TypedDict):
    rule: str
    type: str
    importance: str


class WorldBibleDraft(TypedDict):
    locations: list[LocationDraft]
    factions: list[FactionDraft]
    rules: list[RuleDraft]


CHARACTER_BIBLE_SYSTEM = """你是 Nove 的人物设定助手。根据故事蓝图准备可直接用于长篇小说的人物阵容。
只输出 JSON，不要解释，也不要留下待定项。

schema:
{
  "characters": [
    {
      "name": "具体中文姓名",
      "role": "主角|主要对手|关键盟友|重要配角",
      "summary": "人物身份、处境与戏剧作用",
      "goal": "人物主动追求的目标",
      "flaw": "会造成可见后果的缺陷或局限",
      "voice": "有辨识度的说话方式",
      "relationship_to_protagonist": "与主角的关系和张力",
      "status": "开篇时的状态"
    }
  ]
}

规则：
1. 必须生成 1 名主角、1 名主要对手和 2-4 名配角。
2. 人物必须服务核心冲突，并拥有彼此不同的目标、方法和说话方式。
3. 主要对手应与主角形成价值或方法上的镜像，而不是只写成抽象势力。
4. 缺陷必须能在剧情中导致代价；关系必须能产生选择或冲突。
5. 只使用蓝图事实和合理原创推断，不复制参考作品的专有角色。
"""


WORLD_BIBLE_SYSTEM = """你是 Nove 的世界设定助手。根据故事蓝图准备可直接用于长篇小说的地点、势力和世界规则。
只输出 JSON，不要解释，也不要留下待定项。

schema:
{
  "locations": [
    {"name": "地点名", "region": "所属区域", "state": "开篇状态", "summary": "用途、氛围与冲突价值", "depth": 0}
  ],
  "factions": [
    {"name": "势力名", "kind": "组织类型", "stance": "对主角的立场", "power": "势力范围或力量等级", "summary": "目标、手段与内部矛盾"}
  ],
  "rules": [
    {"rule": "可验证的世界规则或能力边界", "type": "世界设定|能力限制|社会规则", "importance": "高|中|低"}
  ]
}

规则：
1. 必须生成至少 3 个能承载不同剧情功能的地点、2 个立场不同的势力和 2-4 条规则。
2. 地点要能支持开场、冲突升级和阶段高潮，避免只有景观描述。
3. 势力必须有目标、手段和利益冲突；规则必须能在正文中验证。
4. 能力或特殊优势必须有边界与代价，不能为剧情需要临时改变。
5. 只使用蓝图事实和合理原创推断，不复制参考作品的专有地点或组织。
"""


class AgentScopeCharacterBibleAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def generate(
        self, *, novel: dict[str, Any], blueprint: dict[str, Any]
    ) -> CharacterBibleDraft:
        return run_async(self._generate_async(novel=novel, blueprint=blueprint))

    async def _generate_async(
        self, *, novel: dict[str, Any], blueprint: dict[str, Any]
    ) -> CharacterBibleDraft:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.5
            agent = Agent(
                name="CharacterBible",
                system_prompt=CHARACTER_BIBLE_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {"novel": novel, "blueprint": blueprint}
            reply = await agent.reply(
                UserMsg(
                    name="nove",
                    content="请生成人物设定，只返回 JSON：\n"
                    + json.dumps(payload, ensure_ascii=False),
                )
            )
            return normalize_character_bible(parse_json_object(extract_text(reply)))
        finally:
            await close_chat_model(model)


class AgentScopeWorldBibleAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def generate(
        self, *, novel: dict[str, Any], blueprint: dict[str, Any]
    ) -> WorldBibleDraft:
        return run_async(self._generate_async(novel=novel, blueprint=blueprint))

    async def _generate_async(
        self, *, novel: dict[str, Any], blueprint: dict[str, Any]
    ) -> WorldBibleDraft:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.45
            agent = Agent(
                name="WorldBible",
                system_prompt=WORLD_BIBLE_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {"novel": novel, "blueprint": blueprint}
            reply = await agent.reply(
                UserMsg(
                    name="nove",
                    content="请生成世界设定，只返回 JSON：\n"
                    + json.dumps(payload, ensure_ascii=False),
                )
            )
            return normalize_world_bible(parse_json_object(extract_text(reply)))
        finally:
            await close_chat_model(model)


def normalize_character_bible(data: dict[str, Any]) -> CharacterBibleDraft:
    raw = data.get("characters") if isinstance(data.get("characters"), list) else []
    characters: list[CharacterDraft] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))[:200]
        if not name or name in names:
            continue
        names.add(name)
        characters.append(
            {
                "name": name,
                "role": _text(item.get("role")) or "重要配角",
                "summary": _text(item.get("summary")),
                "goal": _text(item.get("goal")),
                "flaw": _text(item.get("flaw")),
                "voice": _text(item.get("voice")),
                "relationship_to_protagonist": _text(
                    item.get("relationship_to_protagonist")
                ),
                "status": _text(item.get("status")) or "尚未登场",
            }
        )
        if len(characters) >= 8:
            break
    return {"characters": characters}


def normalize_world_bible(data: dict[str, Any]) -> WorldBibleDraft:
    locations: list[LocationDraft] = []
    location_names: set[str] = set()
    raw_locations = data.get("locations") if isinstance(data.get("locations"), list) else []
    for item in raw_locations:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))[:200]
        if not name or name in location_names:
            continue
        location_names.add(name)
        locations.append(
            {
                "name": name,
                "region": _text(item.get("region")) or "核心区域",
                "state": _text(item.get("state")) or "正常",
                "summary": _text(item.get("summary")),
                "depth": _bounded_int(item.get("depth"), minimum=0, maximum=4),
            }
        )
        if len(locations) >= 8:
            break

    factions: list[FactionDraft] = []
    faction_names: set[str] = set()
    raw_factions = data.get("factions") if isinstance(data.get("factions"), list) else []
    for item in raw_factions:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))[:200]
        if not name or name in faction_names:
            continue
        faction_names.add(name)
        factions.append(
            {
                "name": name,
                "kind": _text(item.get("kind")) or "组织",
                "stance": _text(item.get("stance")) or "中立",
                "power": _text(item.get("power")) or "区域级",
                "summary": _text(item.get("summary")),
            }
        )
        if len(factions) >= 6:
            break

    rules: list[RuleDraft] = []
    seen_rules: set[str] = set()
    raw_rules = data.get("rules") if isinstance(data.get("rules"), list) else []
    for item in raw_rules:
        if isinstance(item, str):
            item = {"rule": item}
        if not isinstance(item, dict):
            continue
        rule = _text(item.get("rule"))
        if not rule or rule in seen_rules:
            continue
        seen_rules.add(rule)
        importance = _text(item.get("importance"))
        rules.append(
            {
                "rule": rule,
                "type": _text(item.get("type")) or "世界设定",
                "importance": importance if importance in {"高", "中", "低"} else "中",
            }
        )
        if len(rules) >= 4:
            break
    return {"locations": locations, "factions": factions, "rules": rules}


def heuristic_character_bible(
    novel: dict[str, Any], blueprint: dict[str, Any]
) -> CharacterBibleDraft:
    idea = _text(novel.get("coreIdea")) or _text(blueprint.get("logline")) or "主线危机"
    protagonist = blueprint.get("protagonist") if isinstance(blueprint.get("protagonist"), dict) else {}
    protagonist_name = _text(protagonist.get("name")) or "林川"
    antagonist_text = _text(blueprint.get("antagonist"))
    antagonist_name = _person_name(antagonist_text, fallback="顾临渊")
    if antagonist_name == protagonist_name:
        antagonist_name = "顾临渊"
    support_names = [name for name in ("许知微", "周野", "沈栖") if name not in {protagonist_name, antagonist_name}]
    goal = _text(protagonist.get("goal")) or idea
    flaw = _text(protagonist.get("flaw_or_start")) or "急于证明自己，容易在信息不足时冒险"
    characters: list[CharacterDraft] = [
        {
            "name": protagonist_name,
            "role": "主角",
            "summary": _text(protagonist.get("identity")) or f"被卷入「{idea[:60]}」的核心行动者",
            "goal": goal,
            "flaw": flaw,
            "voice": "先问关键事实，再用短句作出决定",
            "relationship_to_protagonist": "本人",
            "status": "正被开篇危机逼迫作出选择",
        },
        {
            "name": antagonist_name,
            "role": "主要对手",
            "summary": antagonist_text or "以更激进的方法争夺同一目标的核心对手",
            "goal": f"抢在{protagonist_name}之前控制核心机会，并证明自己的方法才有效",
            "flaw": "过度相信控制和效率，会低估他人的主动选择",
            "voice": "措辞克制而精确，习惯把威胁说成条件",
            "relationship_to_protagonist": "目标相近、方法相反的镜像对手",
            "status": "已经先行布局，但尚未公开全部目的",
        },
        {
            "name": support_names[0],
            "role": "关键盟友",
            "summary": "掌握现实资源和地方信息，能把主角的判断转化为行动",
            "goal": "查明危机背后的真实受益者，并保护自己在意的人",
            "flaw": "对承诺看得太重，即使局势变化也不愿轻易后退",
            "voice": "观察细，常用反问指出计划中的漏洞",
            "relationship_to_protagonist": "可靠但会质疑主角冒险倾向的盟友",
            "status": "因一条异常线索与主角相遇",
        },
        {
            "name": support_names[1],
            "role": "重要配角",
            "summary": "处在冲突双方之间，拥有一块不可替代的信息拼图",
            "goal": "摆脱被利用的处境，为自己争取安全退路",
            "flaw": "习惯保留关键信息，容易在需要信任时错失时机",
            "voice": "表面随意，谈到关键事实时会刻意换词",
            "relationship_to_protagonist": "既需要主角帮助，也可能因自保隐瞒真相",
            "status": "尚未决定把关键线索交给哪一方",
        },
    ]
    return {"characters": characters}


def heuristic_world_bible(
    novel: dict[str, Any], blueprint: dict[str, Any]
) -> WorldBibleDraft:
    genre = _text(novel.get("genre")) or _text(blueprint.get("genre")) or "悬疑"
    idea = _text(novel.get("coreIdea")) or _text(blueprint.get("logline")) or "主线危机"
    world = blueprint.get("world") if isinstance(blueprint.get("world"), dict) else {}
    setting = _text(world.get("setting")) or f"围绕「{idea[:60]}」展开的{genre}世界"
    location_sets = {
        "悬疑": ("旧城邮局", "雾河公寓", "封存档案馆"),
        "科幻": ("近地转运站", "环城数据港", "静默实验区"),
        "仙侠": ("青崖外门", "沉星坊市", "禁谷遗址"),
        "玄幻": ("临渊城", "黑石集市", "断脉古地"),
        "都市": ("南桥街区", "远峰中心", "旧工业园"),
        "历史": ("东城驿站", "都护府", "北境关城"),
    }
    names = next((value for key, value in location_sets.items() if key in genre), location_sets["悬疑"])
    antagonist = _text(blueprint.get("antagonist"))
    antagonist_faction = _faction_name(antagonist, fallback="镜塔会")
    raw_rules = world.get("rules") if isinstance(world.get("rules"), list) else []
    rules: list[RuleDraft] = []
    for index, item in enumerate(raw_rules[:4]):
        text = _text(item)
        if text and all(existing["rule"] != text for existing in rules):
            rules.append(
                {
                    "rule": text,
                    "type": "世界设定" if index == 0 else "能力限制",
                    "importance": "高" if index < 2 else "中",
                }
            )
    additions = [
        "任何关键能力都必须通过已展示的条件触发，并付出对应代价",
        "信息、资源与身份变化会留下可追溯的现实后果",
        "同一规则对主角、盟友和对手一视同仁",
    ]
    for text in additions:
        if len(rules) >= 4:
            break
        if all(existing["rule"] != text for existing in rules):
            rules.append({"rule": text, "type": "能力限制", "importance": "高"})
    return {
        "locations": [
            {
                "name": names[0],
                "region": "故事起点",
                "state": "表面平静，异常已经出现",
                "summary": f"承载开篇事件与第一批线索；其日常秩序能反衬「{idea[:50]}」带来的异常。",
                "depth": 0,
            },
            {
                "name": names[1],
                "region": "核心城区",
                "state": "多方势力暗中争夺",
                "summary": "资源、消息与人物关系交汇处，适合让冲突升级并产生公开后果。",
                "depth": 0,
            },
            {
                "name": names[2],
                "region": "限制区域",
                "state": "入口受控，内部记录不完整",
                "summary": f"保存与世界核心设定相关的证据，是阶段高潮和规则验证发生地。世界基底：{setting}",
                "depth": 0,
            },
        ],
        "factions": [
            {
                "name": "临时调查同盟",
                "kind": "松散合作组织",
                "stance": "支持主角但保留条件",
                "power": "地方级人脉与调查资源",
                "summary": "希望阻止危机扩大，成员对公开真相的代价存在分歧。",
            },
            {
                "name": antagonist_faction,
                "kind": "利益组织",
                "stance": "与主角竞争并阻挠调查",
                "power": "掌握关键资源与信息渠道",
                "summary": antagonist or "试图垄断核心机会，以秩序和效率为名排除不可控者。",
            },
        ],
        "rules": rules[:4],
    }


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return minimum


def _person_name(value: str, *, fallback: str) -> str:
    candidate = re.split(r"[，,。；;：:（(]", value, maxsplit=1)[0].strip()
    if not candidate or len(candidate) > 6 or any(
        marker in candidate for marker in ("势力", "组织", "家族", "宗门", "集团", "环境", "制度")
    ):
        return fallback
    return candidate


def _faction_name(value: str, *, fallback: str) -> str:
    candidate = re.split(r"[，,。；;：:（(]", value, maxsplit=1)[0].strip()
    if not candidate or len(candidate) > 12:
        return fallback
    if any(marker in candidate for marker in ("势力", "组织", "家族", "宗门", "集团", "会")):
        return candidate
    return fallback
