import json
from pathlib import Path

import pytest

from nanobot.agent.domain import DomainAgentRequest, DomainReplyMode, DomainRunStatus, DomainTrigger
from nanobot.agent.domain.knowledge_agent import KnowledgeAgent
from nanobot.config.schema import LightRAGConfig


@pytest.mark.asyncio
async def test_knowledge_agent_sync_returns_query_reply(monkeypatch, tmp_path: Path) -> None:
    agent = KnowledgeAgent(tmp_path, LightRAGConfig(enabled=True))

    async def _fake_execute(**kwargs):
        assert kwargs["query"] == "explain docs"
        return json.dumps({"response": "Knowledge answer", "mode": "hybrid"}, ensure_ascii=False)

    monkeypatch.setattr(agent.query_tool, "execute", _fake_execute)
    result = await agent.handle_sync(
        DomainAgentRequest(
            request_id="req-1",
            agent_name="knowledge",
            person_id="owner",
            surface_id="cli:direct",
            session_key="cli:direct",
            goal="explain docs",
            constraints={},
            reply_mode=DomainReplyMode.SYNC,
            trigger=DomainTrigger.USER,
        )
    )

    assert result.status is DomainRunStatus.OK
    assert result.suggested_user_reply == "Knowledge answer"


@pytest.mark.asyncio
async def test_knowledge_agent_async_returns_track_id(monkeypatch, tmp_path: Path) -> None:
    agent = KnowledgeAgent(tmp_path, LightRAGConfig(enabled=True))

    async def _fake_execute(**kwargs):
        assert kwargs["file_paths"] == ["docs/a.md"]
        return json.dumps({"status": "accepted", "track_id": "trk-9", "target": "files"}, ensure_ascii=False)

    monkeypatch.setattr(agent.ingest_tool, "execute", _fake_execute)
    result = await agent.handle_async(
        DomainAgentRequest(
            request_id="req-2",
            agent_name="knowledge",
            person_id="owner",
            surface_id="cli:direct",
            session_key="cli:direct",
            goal="index docs",
            constraints={},
            artifacts={"file_paths": ["docs/a.md"]},
            reply_mode=DomainReplyMode.ASYNC,
            trigger=DomainTrigger.USER,
        )
    )

    assert result.status is DomainRunStatus.ACCEPTED
    assert "Track ID: trk-9" in (result.suggested_user_reply or "")


@pytest.mark.asyncio
async def test_knowledge_agent_event_is_skipped(tmp_path: Path) -> None:
    agent = KnowledgeAgent(tmp_path, LightRAGConfig(enabled=True))
    result = await agent.handle_event(
        DomainAgentRequest(
            request_id="req-3",
            agent_name="knowledge",
            person_id="owner",
            surface_id="cli:direct",
            session_key="cli:direct",
            goal="heartbeat",
            reply_mode=DomainReplyMode.EVENT,
            trigger=DomainTrigger.HEARTBEAT,
        )
    )

    assert result.status is DomainRunStatus.SKIPPED
