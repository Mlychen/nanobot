import asyncio
from contextlib import suppress
from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.cli.commands import _make_primary_orchestrator
from nanobot.config.schema import Config
from nanobot.identity import IdentityStore, Person


class DummyConfig:
    allow_from = ["*"]


class RecordingChannel(BaseChannel):
    name = "feishu"

    def __init__(self, name: str, bus: MessageBus):
        super().__init__(DummyConfig(), bus)
        self.name = name
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


class StubProvider:
    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, *args, **kwargs):  # pragma: no cover - direct path should bypass provider
        raise AssertionError("provider should not be used in scheduler integration tests")


async def _dispatch_single(manager: ChannelManager, bus: MessageBus, msg: OutboundMessage) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await bus.publish_outbound(msg)
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _seed_identity(store: IdentityStore) -> None:
    store.upsert_person(
        Person(person_id="owner", primary_channel="feishu", trusted_channels=["feishu", "cli"])
    )
    store.bind_identity("owner", "feishu", "ou_123")
    store.bind_identity("owner", "cli", "cli-user")


@pytest.mark.asyncio
async def test_scheduler_sync_path_returns_plan_from_registered_agent(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=StubProvider(),
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        primary_orchestrator=_make_primary_orchestrator(tmp_path),
    )

    result = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="cli-user",
            chat_id="direct",
            content="请帮我安排今天学习",
            metadata={
                "person_id": "owner",
                "identity": {"trusted": True, "surface_kind": "cli"},
                "session": {"session_key": "person:owner:direct", "surface_id": "cli:direct"},
                "orchestrator": {
                    "agent_name": "scheduler",
                    "reply_mode": "sync",
                    "goal": "安排今天学习",
                    "constraints": {
                        "now": "2026-03-06T08:00:00",
                        "plan_date": "2026-03-06",
                        "time_blocks": [
                            {"label": "行测刷题", "start_at": "09:00", "end_at": "10:00"},
                            {"label": "申论复盘", "start_at": "10:30", "end_at": "11:15"},
                        ],
                        "review_due_at": "12:00",
                    },
                },
            },
        ),
        session_key="person:owner:direct",
    )

    assert result is not None
    assert "今日学习计划（2026-03-06）" in result.content
    assert "行测刷题" in result.content
    assert "申论复盘" in result.content


@pytest.mark.asyncio
async def test_scheduler_async_path_routes_finished_notification_via_channel_manager(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    bus = MessageBus()
    manager = ChannelManager(config, bus)
    manager.channels = {"feishu": RecordingChannel("feishu", bus)}
    _seed_identity(manager.identity_store)

    loop = AgentLoop(
        bus=bus,
        provider=StubProvider(),
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        primary_orchestrator=_make_primary_orchestrator(tmp_path),
        channels_config=config.channels,
    )

    ack = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="cli-user",
            chat_id="direct",
            content="稍后提醒我开始学习",
            metadata={
                "person_id": "owner",
                "identity": {"trusted": True, "surface_kind": "cli"},
                "session": {"session_key": "person:owner:direct", "surface_id": "cli:direct"},
                "orchestrator": {
                    "agent_name": "scheduler",
                    "reply_mode": "async",
                    "goal": "开始第一块学习",
                    "constraints": {"now": "2026-03-06T08:40:00", "fatigue_level": "low"},
                },
            },
        ),
        session_key="person:owner:direct",
    )

    assert ack is not None
    assert "scheduler task" in ack.content.lower()

    jobs = loop.primary_orchestrator.registry.list_jobs()
    assert len(jobs) == 1
    await loop.primary_orchestrator.registry.wait_for_job(jobs[0].job_id)
    notifications = loop.primary_orchestrator.consume_finished_notifications()

    assert len(notifications) == 1
    await _dispatch_single(manager, bus, notifications[0])

    sent = manager.channels["feishu"].sent
    assert len(sent) == 1
    assert sent[0].chat_id == "ou_123"
    assert "学习提醒：开始第一块学习" in sent[0].content
    assert sent[0].metadata["notification"]["decision"]["deliver"] is True


@pytest.mark.asyncio
async def test_scheduler_event_path_delivers_due_reminder_once(tmp_path: Path) -> None:
    orchestrator = _make_primary_orchestrator(tmp_path)

    sync_response = await orchestrator.handle_inbound(
        InboundMessage(
            channel="cli",
            sender_id="cli-user",
            chat_id="direct",
            content="先生成计划",
            metadata={
                "person_id": "owner",
                "identity": {"trusted": True, "surface_kind": "cli"},
                "session": {"session_key": "person:owner:direct", "surface_id": "cli:direct"},
                "orchestrator": {
                    "agent_name": "scheduler",
                    "reply_mode": "sync",
                    "goal": "安排今天学习",
                    "constraints": {
                        "now": "2026-03-06T08:00:00",
                        "plan_date": "2026-03-06",
                        "time_blocks": [
                            {"label": "晨间刷题", "start_at": "09:00", "end_at": "10:00"},
                            {"label": "午前复盘", "start_at": "10:30", "end_at": "11:10"},
                        ],
                        "review_due_at": "11:40",
                    },
                },
            },
        )
    )

    assert sync_response is not None

    first = await orchestrator.handle_event(
        agent_name="scheduler",
        goal="heartbeat check",
        trigger="heartbeat",
        channel="feishu",
        chat_id="ou_123",
        person_id="owner",
        session_key="person:owner:direct",
        surface_id="feishu:ou_123",
        constraints={"now": "2026-03-06T12:00:00"},
    )

    assert first is not None
    assert "学习提醒：" in first
    assert "复盘提醒：" in first

    second = await orchestrator.handle_event(
        agent_name="scheduler",
        goal="heartbeat check",
        trigger="heartbeat",
        channel="feishu",
        chat_id="ou_123",
        person_id="owner",
        session_key="person:owner:direct",
        surface_id="feishu:ou_123",
        constraints={"now": "2026-03-06T12:05:00"},
    )

    assert second is None


