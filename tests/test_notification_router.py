import asyncio
from contextlib import suppress

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config
from nanobot.identity import IdentityStore, Person
from nanobot.notifications import NotificationRouter


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


def _notification_message(kind: str, **overrides) -> OutboundMessage:
    notification = {
        "kind": kind,
        "person_id": "owner",
        "origin_channel": "feishu",
        "origin_chat_id": "oc_group",
        "trusted": False,
        "surface_kind": "group",
    }
    notification.update(overrides)
    return OutboundMessage(
        channel="system",
        chat_id="job-1",
        content="hello",
        metadata={"notification": notification},
    )


def _seed_person(store: IdentityStore, *, primary_channel: str | None = "feishu", trusted_channels: list[str] | None = None) -> None:
    store.upsert_person(
        Person(
            person_id="owner",
            primary_channel=primary_channel,
            trusted_channels=trusted_channels or ["feishu", "cli"],
        )
    )


def test_notification_router_routes_reply_back_to_origin(tmp_path) -> None:
    router = NotificationRouter(IdentityStore(tmp_path), deliverable_channels={"feishu", "cli"})
    msg = _notification_message("reply", origin_channel="slack", origin_chat_id="C123")

    decision = router.route_outbound(msg)

    assert decision is not None
    assert decision.target_channel == "slack"
    assert decision.target_chat_id == "C123"
    assert msg.metadata["notification"]["decision"]["deliver"] is True


def test_notification_router_routes_proactive_to_primary_direct_channel(tmp_path) -> None:
    store = IdentityStore(tmp_path)
    _seed_person(store)
    store.bind_identity("owner", "feishu", "ou_123")
    store.bind_identity("owner", "cli", "sunji")
    router = NotificationRouter(store, deliverable_channels={"feishu", "cli"})
    msg = _notification_message("proactive")

    decision = router.route_outbound(msg)

    assert decision is not None
    assert decision.target_channel == "feishu"
    assert decision.target_chat_id == "ou_123"
    assert decision.requires_primary_agent is False


def test_notification_router_falls_back_when_primary_not_deliverable(tmp_path) -> None:
    store = IdentityStore(tmp_path)
    _seed_person(store, primary_channel="telegram")
    store.bind_identity("owner", "feishu", "ou_123")
    store.bind_identity("owner", "cli", "sunji")
    router = NotificationRouter(store, deliverable_channels={"feishu", "cli"})
    msg = _notification_message("proactive")

    decision = router.route_outbound(msg)

    assert decision is not None
    assert decision.target_channel == "feishu"
    assert decision.reason == "fallback direct channel"


def test_notification_router_routes_confirmation_only_to_trusted_direct_channel(tmp_path) -> None:
    store = IdentityStore(tmp_path)
    _seed_person(store, primary_channel="feishu", trusted_channels=["cli"])
    store.bind_identity("owner", "feishu", "ou_123")
    store.bind_identity("owner", "cli", "sunji")
    router = NotificationRouter(store, deliverable_channels={"feishu", "cli"})
    msg = _notification_message("confirmation")

    decision = router.route_outbound(msg)

    assert decision is not None
    assert decision.target_channel == "cli"
    assert decision.target_chat_id == "sunji"
    assert decision.reason == "trusted fallback direct channel"


def test_notification_router_rejects_when_person_or_binding_missing(tmp_path) -> None:
    router = NotificationRouter(IdentityStore(tmp_path), deliverable_channels={"feishu", "cli"})
    msg = _notification_message("confirmation", person_id=None)

    decision = router.route_outbound(msg)

    assert decision is None
    assert msg.metadata["notification"]["decision"]["deliver"] is False
    assert "missing person_id" in msg.metadata["notification"]["decision"]["reason"]


async def _dispatch_single(manager: ChannelManager, bus: MessageBus, msg: OutboundMessage) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        await bus.publish_outbound(msg)
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def test_channel_manager_routes_notification_before_send(tmp_path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    bus = MessageBus()
    manager = ChannelManager(config, bus)
    channel = RecordingChannel("feishu", bus)
    manager.channels = {"feishu": channel}

    manager.identity_mapper.upsert_person(
        Person(person_id="owner", primary_channel="feishu", trusted_channels=["feishu"])
    )
    manager.identity_mapper.bind_identity("owner", "feishu", "ou_123")

    await _dispatch_single(manager, bus, _notification_message("proactive"))

    assert len(channel.sent) == 1
    assert channel.sent[0].channel == "feishu"
    assert channel.sent[0].chat_id == "ou_123"


async def test_channel_manager_drops_rejected_notification(tmp_path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    bus = MessageBus()
    manager = ChannelManager(config, bus)
    channel = RecordingChannel("feishu", bus)
    manager.channels = {"feishu": channel}

    rejected = _notification_message("confirmation", person_id=None)
    await _dispatch_single(manager, bus, rejected)

    assert channel.sent == []
    assert rejected.metadata["notification"]["decision"]["deliver"] is False


async def test_channel_manager_keeps_legacy_outbound_unchanged(tmp_path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    bus = MessageBus()
    manager = ChannelManager(config, bus)
    channel = RecordingChannel("feishu", bus)
    manager.channels = {"feishu": channel}

    legacy = OutboundMessage(channel="feishu", chat_id="oc_legacy", content="legacy")
    await _dispatch_single(manager, bus, legacy)

    assert len(channel.sent) == 1
    assert channel.sent[0].chat_id == "oc_legacy"
