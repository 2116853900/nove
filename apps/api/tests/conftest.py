from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import set_workspace_id
from app.agents.bible_bootstrap import (
    AgentScopeCharacterBibleAgent,
    AgentScopeWorldBibleAgent,
    heuristic_character_bible,
    heuristic_world_bible,
)
from app.agents import outline as outline_module
from app.agents.blueprint import AgentScopeBlueprintAgent, heuristic_blueprint
from app.agents.outline import heuristic_outline_children
from app.agents.skills_runtime import SkillRuntime
from app.agents.writer import AgentScopeWriter
from app.db import Base
from app.models import ModelConfig
from app.seed import ensure_seed_data
from app.services import LocalWritingModel


_ORIGINAL_OUTLINE_AGENT = outline_module.AgentScopeOutlineAgent
_ORIGINAL_OUTLINE_SKILL = SkillRuntime._outline_generate


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    set_workspace_id("local")
    with Session(engine, expire_on_commit=False) as db:
        ensure_seed_data(db, demo=True)
        db.add_all(
            [
                ModelConfig(
                    id="test-cloud-workspace",
                    workspace_id="local",
                    novel_id=None,
                    name="Test Cloud",
                    provider="OpenAI 兼容",
                    model_id="test-cloud",
                    base_url="https://cloud.test.invalid/v1",
                    status="connected",
                    roles=[],
                    is_default=True,
                ),
                ModelConfig(
                    id="test-cloud-starfarer",
                    workspace_id="local",
                    novel_id="starfarer",
                    name="Test Cloud",
                    provider="OpenAI 兼容",
                    model_id="test-cloud",
                    base_url="https://cloud.test.invalid/v1",
                    status="connected",
                    roles=["大纲", "写作", "润色"],
                ),
            ]
        )
        db.commit()

        monkeypatch.setattr(
            AgentScopeBlueprintAgent,
            "generate",
            lambda self, *, novel, volume_hint=1: heuristic_blueprint(novel),
        )
        def fake_outline_generate(self, payload):
            if outline_module.AgentScopeOutlineAgent is not _ORIGINAL_OUTLINE_AGENT:
                return _ORIGINAL_OUTLINE_SKILL(self, payload)
            nodes = heuristic_outline_children(
                novel=payload.get("novel") or {},
                parent=payload.get("parent"),
                child_kind=payload.get("child_kind") or "chapter",
                count=int(payload.get("count") or 0),
                existing_titles=payload.get("existing_titles") or [],
                start_chapter_index=int(payload.get("start_chapter_index") or 1),
                characters=payload.get("characters") or [],
                locations=payload.get("locations") or [],
            )
            return {
                "ok": True,
                "source": "model",
                "childKind": payload.get("child_kind") or "chapter",
                "count": len(nodes),
                "nodes": nodes,
            }

        monkeypatch.setattr(SkillRuntime, "_outline_generate", fake_outline_generate)
        monkeypatch.setattr(
            AgentScopeCharacterBibleAgent,
            "generate",
            lambda self, *, novel, blueprint: heuristic_character_bible(novel, blueprint),
        )
        monkeypatch.setattr(
            AgentScopeWorldBibleAgent,
            "generate",
            lambda self, *, novel, blueprint: heuristic_world_bible(novel, blueprint),
        )
        monkeypatch.setattr(
            AgentScopeWriter,
            "generate",
            lambda self, **kwargs: LocalWritingModel().generate(**kwargs),
        )
        yield db
    Base.metadata.drop_all(engine)
