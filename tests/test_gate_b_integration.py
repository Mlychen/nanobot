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
        raise AssertionError("provider should not be used in Gate B orchestrator tests")


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


def _make_loop(tmp_path: Path) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=StubProvider(),
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        primary_orchestrator=_make_primary_orchestrator(),
    )


def test_gate_b_primary_orchestrator_uses_runtime_assembly() -> None:
    orchestrator = _make_primary_orchestrator()

    descriptor = orchestrator.describe_agent("gate-b-probe")

    assert descriptor is not None
    assert descriptor.name == "gate-b-probe"


@pytest.mark.asyncio
async def test_gate_b_sync_path_returns_user_reply_from_registered_agent(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)

    result = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="cli-user",
            chat_id="direct",
            content="/delegate-sync gate-b-probe check sync",
            metadata={
                "person_id": "owner",
                "identity": {"trusted": True, "surface_kind": "cli"},
                "session": {"session_key": "person:owner:direct", "surface_id": "cli:direct"},
            },
        ),
        session_key="person:owner:direct",
    )

    assert result is not None
    assert result.content == "gate-b sync:check sync"


@pytest.mark.asyncio
async def test_gate_b_event_path_returns_event_reply_from_registered_agent(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)

    result = await loop._process_message(
        InboundMessage(
            channel="system",
            sender_id="heartbeat",
            chat_id="feishu:ou_123",
            content="check cadence",
            metadata={
                "person_id": "owner",
                "orchestrator": {
                    "agent_name": "gate-b-probe",
                    "trigger": "heartbeat",
                    "goal": "check cadence",
                },
                "identity": {"trusted": True, "surface_kind": "dm"},
            },
        )
    )

    assert result is not None
    assert result.channel == "feishu"
    assert result.chat_id == "ou_123"
    assert result.content == "gate-b event:check cadence"


@pytest.mark.asyncio
async def test_gate_b_async_path_routes_finished_notification_via_channel_manager(tmp_path: Path) -> None:
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
        primary_orchestrator=_make_primary_orchestrator(),
        channels_config=config.channels,
    )

    ack = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="cli-user",
            chat_id="direct",
            content="/delegate-async gate-b-probe remind later",
            metadata={
                "person_id": "owner",
                "identity": {"trusted": True, "surface_kind": "cli"},
                "session": {"session_key": "person:owner:direct", "surface_id": "cli:direct"},
            },
        ),
        session_key="person:owner:direct",
    )

    assert ack is not None
    assert "Job ID:" in ack.content

    jobs = loop.primary_orchestrator.registry.list_jobs()
    assert len(jobs) == 1
    await loop.primary_orchestrator.registry.wait_for_job(jobs[0].job_id)
    notifications = loop.primary_orchestrator.consume_finished_notifications()

    assert len(notifications) == 1
    await _dispatch_single(manager, bus, notifications[0])

    sent = manager.channels["feishu"].sent
    assert len(sent) == 1
    assert sent[0].channel == "feishu"
    assert sent[0].chat_id == "ou_123"
    assert sent[0].content == "gate-b async:remind later"
    assert sent[0].metadata["notification"]["decision"]["deliver"] is True


@pytest.mark.asyncio
async def test_gate_b_missing_agent_falls_back_without_crashing(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.primary_orchestrator.registry = loop.primary_orchestrator.registry.__class__()

    result = await loop.primary_orchestrator.handle_inbound(
        InboundMessage(
            channel="cli",
            sender_id="cli-user",
            chat_id="direct",
            content="/delegate-sync gate-b-probe missing",
        )
    )

    assert result is None
