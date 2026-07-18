from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.auditor import normalize_audit_result
from app.agents.models import build_chat_model, close_chat_model
from app.agents.runtime import extract_text, parse_json_object, run_async


def test_chat_model_uses_explicitly_owned_http_client() -> None:
    config = SimpleNamespace(
        name="test-model",
        base_url="http://127.0.0.1:9/v1",
        encrypted_api_key=None,
        top_p=100,
        timeout_ms=1000,
        context_size=4096,
        extra_body=None,
        temperature=50,
        max_output_tokens=512,
        model_id="test-model",
    )

    model = build_chat_model(config)
    http_client = model._nove_http_client

    assert model.client_kwargs["http_client"] is http_client
    assert http_client.is_closed is False

    run_async(close_chat_model(model))

    assert http_client.is_closed is True
    assert model._nove_http_client is None


def test_plot_agent_closes_http_client_before_loop_teardown(monkeypatch) -> None:
    from agentscope import agent as agent_module
    from app.agents import plot as plot_module

    class FakeHttpClient:
        def __init__(self) -> None:
            self.closed = False
            self.loop_was_closed = True

        async def aclose(self) -> None:
            self.loop_was_closed = asyncio.get_running_loop().is_closed()
            self.closed = True

    class FailingAgent:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def reply(self, _message: object) -> None:
            raise RuntimeError("model request failed")

    http_client = FakeHttpClient()
    model = SimpleNamespace(
        parameters=SimpleNamespace(temperature=0.0),
        _nove_http_client=http_client,
    )
    monkeypatch.setattr(agent_module, "Agent", FailingAgent)
    monkeypatch.setattr(plot_module, "build_chat_model", lambda *_args, **_kwargs: model)

    with pytest.raises(RuntimeError, match="model request failed"):
        plot_module.AgentScopePlotAgent(SimpleNamespace(name="test-model")).plan(
            title="测试章",
            brief={},
            context={},
        )

    assert http_client.closed is True
    assert http_client.loop_was_closed is False
    assert model._nove_http_client is None


def test_parse_json_object_from_fenced_output() -> None:
    text = """以下是结果：
```json
{"total_score": 90, "decision": "PASS", "issues": []}
```
"""
    data = parse_json_object(text)
    assert data["total_score"] == 90
    assert data["decision"] == "PASS"


def test_extract_text_from_plain_and_blocks() -> None:
    assert extract_text("  hello  ") == "hello"

    class Block:
        def __init__(self, text: str):
            self.text = text

    class Msg:
        def __init__(self):
            self.content = [Block("第一段"), Block("第二段")]

    assert extract_text(Msg()) == "第一段\n第二段"


def test_normalize_audit_result_fills_decision() -> None:
    result = normalize_audit_result(
        {
            "total_score": 72,
            "issues": [
                {
                    "severity": "major",
                    "type": "大纲完成度",
                    "evidence": "缺少线索",
                    "suggestion": "补上线索",
                }
            ],
            "strengths": ["节奏尚可"],
        },
        dimensions=[{"name": "连续性", "max": 20}],
        protected_texts=["锁定句"],
        brief={"forbidden_events": ["提前揭秘"]},
        pass_score=85,
        revise_score=70,
    )
    assert result["decision"] == "REVISE"
    assert result["total_score"] == 72
    assert result["rewrite_requirements"]["mustNotInclude"] == ["提前揭秘"]
    assert result["issues"][0]["type"] == "大纲完成度"


def test_normalize_audit_result_fatal_forces_rewrite() -> None:
    result = normalize_audit_result(
        {
            "total_score": 95,
            "fatal_issues": [
                {
                    "type": "知识边界",
                    "evidence": "早就知道",
                    "suggestion": "改为推测",
                }
            ],
        },
        dimensions=[{"name": "连续性", "max": 20}],
        protected_texts=[],
        brief={},
        pass_score=85,
        revise_score=70,
    )
    assert result["decision"] == "REWRITE"
    assert result["fatal_issues"]


def test_normalize_audit_result_separates_quote_from_summary() -> None:
    content = "暗渊看向三名信徒。夜歌开始收集石块，老墨则去寻找水源。"
    result = normalize_audit_result(
        {
            "total_score": 80,
            "issues": [
                {
                    "severity": "minor",
                    "type": "任务衔接",
                    "evidence": "第1章分配任务不同；本章中夜歌开始收集石块，但没有解释调整。",
                    "evidenceQuote": "夜歌开始收集石块",
                    "evidenceSource": "content",
                    "suggestion": "说明任务调整原因",
                },
                {
                    "severity": "minor",
                    "type": "大纲缺失",
                    "evidence": "chapterBrief 要求交代一年之约，但正文没有出现。",
                    "evidenceQuote": "",
                    "evidenceSource": "outline",
                    "suggestion": "补充约定",
                },
            ],
        },
        content=content,
        dimensions=[{"name": "连续性", "max": 20}],
        protected_texts=[],
        brief={},
        pass_score=85,
        revise_score=70,
    )

    exact, missing = result["issues"]
    assert exact["evidenceQuote"] == "夜歌开始收集石块"
    assert exact["evidenceSource"] == "content"
    assert exact["locatable"] is True
    assert missing["evidenceQuote"] == ""
    assert missing["evidenceSource"] == "outline"
    assert missing["locatable"] is False
