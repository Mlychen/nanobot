import json

from nanobot.agent.domain.types import DomainReplyMode
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.identity import IdentityMapper, IdentityStore, Person
from nanobot.routing import SurfaceKind


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


def test_identity_store_persists_people_and_bindings(tmp_path) -> None:
    store = IdentityStore(tmp_path)
    store.upsert_person(Person(person_id="owner", trusted_channels=["feishu", "cli"]))
    store.bind_identity("owner", "feishu", "ou_123", is_verified=True)

    people, bindings = store.load()

    assert people["owner"].trusted_channels == ["feishu", "cli"]
    assert len(bindings) == 1
    assert bindings[0].external_user_id == "ou_123"


def test_identity_store_returns_empty_on_invalid_json(tmp_path) -> None:
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True)
    (identity_dir / "store.json").write_text("{bad json", encoding="utf-8")

    store = IdentityStore(tmp_path)
    people, bindings = store.load()

    assert people == {}
    assert bindings == []


def test_identity_mapper_resolves_bound_user_and_marks_trusted(tmp_path) -> None:
    store = IdentityStore(tmp_path)
    mapper = IdentityMapper(store)
    mapper.upsert_person(Person(person_id="owner", trusted_channels=["feishu", "cli"]))
    mapper.bind_identity("owner", "feishu", "ou_123")

    result = mapper.resolve_person("feishu", "ou_123", {"chat_type": "p2p"})

    assert result.resolved is True
    assert result.person_id == "owner"
    assert result.trusted is True
    assert result.surface_kind == SurfaceKind.DM.value


def test_identity_mapper_returns_unresolved_for_unknown_binding(tmp_path) -> None:
    mapper = IdentityMapper(IdentityStore(tmp_path))

    metadata = mapper.enrich_metadata("feishu", "ou_missing", {"chat_type": "group", "msg_type": "text"})

    assert metadata["person_id"] is None
    assert metadata["identity"]["resolved"] is False
    assert metadata["identity"]["surface_kind"] == SurfaceKind.GROUP.value
    assert metadata["msg_type"] == "text"


async def test_base_channel_enriches_metadata_when_mapper_is_attached(tmp_path) -> None:
    bus = MessageBus()
    channel = DummyChannel(DummyConfig(), bus)
    mapper = IdentityMapper(IdentityStore(tmp_path))
    mapper.upsert_person(Person(person_id="owner", trusted_channels=["dummy"]))
    mapper.bind_identity("owner", "dummy", "alice")
    channel.identity_mapper = mapper

    await channel._handle_message(
        sender_id="alice",
        chat_id="chat-1",
        content="hello",
        metadata={"chat_type": "p2p"},
    )

    msg = await bus.consume_inbound()
    assert msg.metadata["person_id"] == "owner"
    assert msg.metadata["identity"]["trusted"] is True


def test_identity_store_file_layout_is_human_editable(tmp_path) -> None:
    store = IdentityStore(tmp_path)
    store.upsert_person(Person(person_id="owner", display_name="Sunji", trusted_channels=["cli"]))
    store.bind_identity("owner", "cli", "sunji")

    data = json.loads((tmp_path / "identity" / "store.json").read_text(encoding="utf-8"))

    assert data["version"] == 1
    assert data["people"][0]["person_id"] == "owner"
    assert data["bindings"][0]["channel"] == "cli"
    assert DomainReplyMode.SYNC.value == "sync"
