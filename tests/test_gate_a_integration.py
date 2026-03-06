import json
from pathlib import Path

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.identity import IdentityMapper, IdentityStore
from nanobot.routing import SessionPolicy, SessionPolicyStore, SharingMode
from nanobot.session.manager import SessionManager


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


def _seed_gate_a_workspace(tmp_path: Path) -> None:
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    (identity_dir / "store.json").write_text(
        json.dumps(
            {
                "version": 1,
                "people": [
                    {
                        "person_id": "owner",
                        "primary_channel": "feishu",
                        "trusted_channels": ["feishu", "cli"],
                        "preferences": {},
                    }
                ],
                "bindings": [
                    {
                        "person_id": "owner",
                        "channel": "feishu",
                        "external_user_id": "ou_123",
                        "is_verified": True,
                    },
                    {
                        "person_id": "owner",
                        "channel": "cli",
                        "external_user_id": "cli-user",
                        "is_verified": True,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    routing_dir = tmp_path / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    (routing_dir / "session_policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "trusted_direct": {
                    "enabled": True,
                    "channels": ["feishu", "cli"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


async def test_gate_a_feishu_and_cli_share_direct_session_for_same_person(tmp_path) -> None:
    _seed_gate_a_workspace(tmp_path)
    store = IdentityStore(tmp_path)
    mapper = IdentityMapper(store)
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    feishu_metadata = mapper.enrich_metadata("feishu", "ou_123", {"chat_type": "p2p"})
    cli_metadata = mapper.enrich_metadata("cli", "cli-user", {})

    feishu_result = policy.resolve_session_key(
        person_id=feishu_metadata["person_id"],
        channel="feishu",
        chat_id="ou_123",
        metadata=feishu_metadata,
    )
    cli_result = policy.resolve_session_key(
        person_id=cli_metadata["person_id"],
        channel="cli",
        chat_id="direct",
        metadata=cli_metadata,
    )

    assert feishu_metadata["person_id"] == "owner"
    assert cli_metadata["person_id"] == "owner"
    assert feishu_result.session_key == "person:owner:direct"
    assert cli_result.session_key == "person:owner:direct"
    assert feishu_result.sharing_mode == SharingMode.TRUSTED_DIRECT
    assert cli_result.sharing_mode == SharingMode.TRUSTED_DIRECT


async def test_gate_a_feishu_group_does_not_share_direct_session(tmp_path) -> None:
    _seed_gate_a_workspace(tmp_path)
    store = IdentityStore(tmp_path)
    mapper = IdentityMapper(store)
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    metadata = mapper.enrich_metadata("feishu", "ou_123", {"chat_type": "group"})
    result = policy.resolve_session_key(
        person_id=metadata["person_id"],
        channel="feishu",
        chat_id="oc_group",
        metadata=metadata,
    )

    assert metadata["person_id"] == "owner"
    assert result.session_key == "feishu:oc_group"
    assert result.sharing_mode == SharingMode.ISOLATED


async def test_gate_a_feishu_thread_stays_thread_scoped(tmp_path) -> None:
    _seed_gate_a_workspace(tmp_path)
    store = IdentityStore(tmp_path)
    mapper = IdentityMapper(store)
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    metadata = mapper.enrich_metadata(
        "feishu",
        "ou_123",
        {"chat_type": "group", "thread_id": "omt-thread-1"},
    )
    result = policy.resolve_session_key(
        person_id=metadata["person_id"],
        channel="feishu",
        chat_id="oc_group",
        metadata=metadata,
    )

    assert result.session_key == "feishu:oc_group:omt-thread-1"
    assert result.sharing_mode == SharingMode.THREAD_SCOPED


async def test_gate_a_base_channel_applies_shared_direct_session_to_feishu_and_cli(tmp_path) -> None:
    _seed_gate_a_workspace(tmp_path)
    bus = MessageBus()
    mapper = IdentityMapper(IdentityStore(tmp_path))
    policy = SessionPolicy(SessionPolicyStore(tmp_path))

    feishu_channel = DummyChannel(DummyConfig(), bus)
    feishu_channel.name = "feishu"
    feishu_channel.identity_mapper = mapper
    feishu_channel.session_policy = policy

    cli_channel = DummyChannel(DummyConfig(), bus)
    cli_channel.name = "cli"
    cli_channel.identity_mapper = mapper
    cli_channel.session_policy = policy

    await feishu_channel._handle_message(
        sender_id="ou_123",
        chat_id="ou_123",
        content="hello from feishu",
        metadata={"chat_type": "p2p"},
    )
    await cli_channel._handle_message(
        sender_id="cli-user",
        chat_id="direct",
        content="hello from cli",
        metadata={},
    )

    feishu_msg = await bus.consume_inbound()
    cli_msg = await bus.consume_inbound()

    assert feishu_msg.session_key_override == "person:owner:direct"
    assert cli_msg.session_key_override == "person:owner:direct"


def test_gate_a_legacy_channel_chat_id_session_remains_loadable(tmp_path) -> None:
    manager = SessionManager(tmp_path)
    legacy_key = "feishu:oc_legacy"

    session = manager.get_or_create(legacy_key)
    session.add_message("user", "legacy message")
    manager.save(session)
    manager.invalidate(legacy_key)

    loaded = manager.get_or_create(legacy_key)

    assert loaded.key == legacy_key
    assert loaded.messages[-1]["content"] == "legacy message"
