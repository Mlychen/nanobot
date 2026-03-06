import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.domain import (
    BaseDomainAgent,
    DomainAgentRequest,
    DomainAgentResult,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
    create_domain_registry,
)
from nanobot.agent.loop import AgentLoop
from nanobot.agent.primary import PrimaryAgentOrchestrator, PrimaryDecisionType
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


class StubAgent(BaseDomainAgent):
    name = "scheduler"

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"sync:{request.goal}",
        )

    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"async:{request.goal}",
            notify_intent=True,
        )

    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"event:{request.goal}",
        )


class SyncOnlyAgent(StubAgent):
    name = "sync-only"
    supports_modes = (DomainReplyMode.SYNC,)


class BrokenAgent(StubAgent):
    name = "broken"

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        raise RuntimeError("boom")


def _make_orchestrator(*agents: BaseDomainAgent) -> PrimaryAgentOrchestrator:
    registry = create_domain_registry(agents=agents)
    return PrimaryAgentOrchestrator(registry)


def _make_loop(tmp_path: Path, orchestrator: PrimaryAgentOrchestrator | None = None) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        primary_orchestrator=orchestrator,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_orchestrator_direct_messages_fall_back_to_main_loop() -> None:
    orchestrator = _make_orchestrator(StubAgent())
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")

    decision = orchestrator.decide(msg)
    response = await orchestrator.handle_inbound(msg)

    assert decision.decision_type is PrimaryDecisionType.DIRECT_ANSWER
    assert response is None


def test_orchestrator_exposes_runtime_descriptors() -> None:
    orchestrator = _make_orchestrator(StubAgent())

    descriptor = orchestrator.describe_agent("scheduler")

    assert descriptor is not None
    assert descriptor.name == "scheduler"
    assert orchestrator.list_agent_descriptors()[0].name == "scheduler"


@pytest.mark.asyncio
async def test_orchestrator_handles_sync_delegate_command() -> None:
    orchestrator = _make_orchestrator(StubAgent())
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="/delegate-sync scheduler build today's plan",
    )

    response = await orchestrator.handle_inbound(msg)

    assert response is not None
    assert response.content == "sync:build today's plan"


@pytest.mark.asyncio
async def test_orchestrator_handles_async_delegate_command() -> None:
    orchestrator = _make_orchestrator(StubAgent())
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="/delegate-async scheduler remind me later",
    )

    response = await orchestrator.handle_inbound(msg)

    assert response is not None
    assert "scheduler task" in response.content
    assert "Job ID:" in response.content


@pytest.mark.asyncio
async def test_orchestrator_respects_runtime_supported_modes() -> None:
    orchestrator = _make_orchestrator(SyncOnlyAgent())
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="/delegate-async sync-only remind me later",
    )

    response = await orchestrator.handle_inbound(msg)

    assert response is None


@pytest.mark.asyncio
async def test_orchestrator_routes_metadata_events() -> None:
    orchestrator = _make_orchestrator(StubAgent())
    msg = InboundMessage(
        channel="system",
        sender_id="heartbeat",
        chat_id="feishu:ou_123",
        content="heartbeat work",
        metadata={
            "orchestrator": {
                "agent_name": "scheduler",
                "trigger": DomainTrigger.HEARTBEAT.value,
                "goal": "check review cadence",
            }
        },
    )

    response = await orchestrator.handle_inbound(msg)

    assert response is not None
    assert response.channel == "feishu"
    assert response.chat_id == "ou_123"
    assert response.content == "event:check review cadence"


@pytest.mark.asyncio
async def test_orchestrator_falls_back_when_agent_is_missing() -> None:
    orchestrator = _make_orchestrator()
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="/delegate-sync scheduler build today's plan",
    )

    response = await orchestrator.handle_inbound(msg)

    assert response is None


@pytest.mark.asyncio
async def test_orchestrator_falls_back_on_sync_errors() -> None:
    orchestrator = _make_orchestrator(BrokenAgent())
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content="/delegate-sync broken test error path",
    )

    response = await orchestrator.handle_inbound(msg)

    assert response is None


@pytest.mark.asyncio
async def test_agent_loop_with_orchestrator_preserves_direct_path(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, _make_orchestrator(StubAgent()))
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content="Hello from main loop", tool_calls=[]))

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    )

    assert result is not None
    assert result.content == "Hello from main loop"


@pytest.mark.asyncio
async def test_process_direct_uses_orchestrator_for_async_delegate(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, _make_orchestrator(StubAgent()))
    loop.provider.chat = AsyncMock(side_effect=AssertionError("provider should not be used"))

    result = await loop.process_direct("/delegate-async scheduler remind me later")

    assert "Job ID:" in result


@pytest.mark.asyncio
async def test_agent_loop_without_orchestrator_keeps_legacy_path(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content="Legacy path", tool_calls=[]))

    result = await loop.process_direct("plain message")

    assert result == "Legacy path"
    assert loop.provider.chat.await_count == 1

@pytest.mark.asyncio
async def test_orchestrator_exposes_finished_async_notifications() -> None:
    orchestrator = _make_orchestrator(StubAgent())
    msg = InboundMessage(
        channel="feishu",
        sender_id="user",
        chat_id="oc_group",
        content="/delegate-async scheduler remind me later",
        metadata={
            "person_id": "owner",
            "identity": {"trusted": False, "surface_kind": "group"},
        },
    )

    response = await orchestrator.handle_inbound(msg)
    assert response is not None

    job = orchestrator.registry.list_jobs()[0]
    await orchestrator.registry.wait_for_job(job.job_id)
    notifications = orchestrator.consume_finished_notifications()

    assert len(notifications) == 1
    outbound = notifications[0]
    assert outbound.content == "async:remind me later"
    assert outbound.metadata["notification"]["kind"] == "proactive"
    assert outbound.metadata["notification"]["person_id"] == "owner"
    assert outbound.metadata["notification"]["origin_channel"] == "feishu"
    assert outbound.metadata["notification"]["origin_chat_id"] == "oc_group"


@pytest.mark.asyncio
async def test_agent_loop_drains_finished_job_notifications(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(StubAgent())
    loop = _make_loop(tmp_path, orchestrator)
    loop.provider.chat = AsyncMock(side_effect=AssertionError("provider should not be used"))

    result = await loop._process_message(
        InboundMessage(
            channel="feishu",
            sender_id="user",
            chat_id="oc_group",
            content="/delegate-async scheduler remind me later",
            metadata={
                "person_id": "owner",
                "identity": {"trusted": False, "surface_kind": "group"},
            },
        )
    )

    assert result is not None
    assert "Job ID:" in result.content

    job = orchestrator.registry.list_jobs()[0]
    await orchestrator.registry.wait_for_job(job.job_id)
    await loop._drain_primary_finished_jobs()
    outbound = await asyncio.wait_for(loop.bus.consume_outbound(), timeout=1.0)

    assert outbound.content == "async:remind me later"
    assert outbound.metadata["notification"]["kind"] == "proactive"
    assert outbound.metadata["notification"]["person_id"] == "owner"
