import json

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.identity import IdentityMapper, IdentityStore, Person
from nanobot.routing import SessionPolicy, SessionPolicyStore, SharingMode, SurfaceKind


class DummyChannel(BaseChannel):
    name = "dummy"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg) -> None:
        return None


class DummyConfig:
    allow_from = ["*"]


def test_session_policy_store_defaults_when_missing(tmp_path) -> None:
    store = SessionPolicyStore(tmp_path)

    assert store.trusted_direct_enabled() is False
    assert store.trusted_direct_channels() == ["feishu", "cli"]


def test_session_policy_store_defaults_when_invalid(tmp_path) -> None:
    routing_dir = tmp_path / "routing"
    routing_dir.mkdir(parents=True)
    (routing_dir / "session_policy.json").write_text("{bad json", encoding="utf-8")

    store = SessionPolicyStore(tmp_path)

    assert store.trusted_direct_enabled() is False
    assert store.trusted_direct_channels() == ["feishu", "cli"]


def test_session_policy_reads_workspace_file(tmp_path) -> None:
    routing_dir = tmp_path / "routing"
    routing_dir.mkdir(parents=True)
    (routing_dir / "session_policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "trusted_direct": {
                    "enabled": True,
                    "channels": ["feishu", "cli"],
                },
            }
        ),
        encoding="utf-8",
    )

    store = SessionPolicyStore(tmp_path)

    assert store.trusted_direct_enabled() is True
    assert store.trusted_direct_channels() == ["feishu", "cli"]


def test_session_policy_defaults_to_isolated_dm(tmp_path) -> None:
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    result = policy.resolve_session_key(
        person_id="owner",
        channel="feishu",
        chat_id="ou_123",
        metadata={"identity": {"resolved": True, "trusted": True, "surface_kind": SurfaceKind.DM.value}},
    )

    assert result.session_key == "feishu:ou_123"
    assert result.sharing_mode == SharingMode.ISOLATED


def test_session_policy_enables_trusted_direct_when_configured(tmp_path) -> None:
    routing_dir = tmp_path / "routing"
    routing_dir.mkdir(parents=True)
    (routing_dir / "session_policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "trusted_direct": {
                    "enabled": True,
                    "channels": ["feishu", "cli"],
                },
            }
        ),
        encoding="utf-8",
    )

    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    feishu_result = policy.resolve_session_key(
        person_id="owner",
        channel="feishu",
        chat_id="ou_123",
        metadata={"identity": {"resolved": True, "trusted": True, "surface_kind": SurfaceKind.DM.value}},
    )
    cli_result = policy.resolve_session_key(
        person_id="owner",
        channel="cli",
        chat_id="direct",
        metadata={"identity": {"resolved": True, "trusted": True, "surface_kind": SurfaceKind.CLI.value}},
    )

    assert feishu_result.session_key == "person:owner:direct"
    assert cli_result.session_key == "person:owner:direct"
    assert feishu_result.sharing_mode == SharingMode.TRUSTED_DIRECT


def test_session_policy_preserves_explicit_override(tmp_path) -> None:
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    result = policy.resolve_session_key(
        person_id="owner",
        channel="slack",
        chat_id="C123",
        metadata={"slack": {"thread_ts": "171.2", "channel_type": "channel"}},
        explicit_session_key="slack:C123:171.2",
    )

    assert result.session_key == "slack:C123:171.2"
    assert result.sharing_mode == SharingMode.THREAD_SCOPED
    assert result.surface_id == "slack:C123:171.2"


def test_session_policy_detects_nested_slack_thread_metadata(tmp_path) -> None:
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    result = policy.resolve_session_key(
        person_id=None,
        channel="slack",
        chat_id="C123",
        metadata={"slack": {"thread_ts": "171.2", "channel_type": "channel"}},
    )

    assert result.session_key == "slack:C123:171.2"
    assert result.sharing_mode == SharingMode.THREAD_SCOPED


async def test_base_channel_applies_session_policy_after_identity(tmp_path) -> None:
    routing_dir = tmp_path / "routing"
    routing_dir.mkdir(parents=True)
    (routing_dir / "session_policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "trusted_direct": {
                    "enabled": True,
                    "channels": ["dummy", "cli"],
                },
            }
        ),
        encoding="utf-8",
    )

    bus = MessageBus()
    channel = DummyChannel(DummyConfig(), bus)
    mapper = IdentityMapper(IdentityStore(tmp_path))
    mapper.upsert_person(Person(person_id="owner", trusted_channels=["dummy", "cli"]))
    mapper.bind_identity("owner", "dummy", "alice")
    channel.identity_mapper = mapper
    channel.session_policy = SessionPolicy(SessionPolicyStore(tmp_path))

    await channel._handle_message(
        sender_id="alice",
        chat_id="dm-1",
        content="hello",
        metadata={"chat_type": "p2p"},
    )

    msg = await bus.consume_inbound()
    assert msg.session_key_override == "person:owner:direct"
    assert msg.metadata["session"]["sharing_mode"] == SharingMode.TRUSTED_DIRECT.value
    assert msg.metadata["identity"]["trusted"] is True
