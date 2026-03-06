"""Workspace-local persistence for identity mappings."""

import json
from pathlib import Path

from loguru import logger

from nanobot.identity.models import ChannelIdentity, Person
from nanobot.utils.helpers import ensure_dir


class IdentityStore:
    """Persistent store for people and channel bindings."""

    def __init__(self, workspace: Path):
        self.identity_dir = ensure_dir(workspace / "identity")
        self.store_path = self.identity_dir / "store.json"

    def load(self) -> tuple[dict[str, Person], list[ChannelIdentity]]:
        """Load people and bindings from disk."""

        if not self.store_path.exists():
            return {}, []

        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load identity store {}: {}", self.store_path, exc)
            return {}, []

        people: dict[str, Person] = {}
        for item in data.get("people", []):
            if not isinstance(item, dict) or not item.get("person_id"):
                continue
            person = Person(
                person_id=str(item["person_id"]),
                display_name=item.get("display_name"),
                primary_channel=item.get("primary_channel"),
                trusted_channels=[str(v) for v in item.get("trusted_channels", []) if v is not None],
                preferences=item.get("preferences") or {},
            )
            people[person.person_id] = person

        bindings: list[ChannelIdentity] = []
        for item in data.get("bindings", []):
            if not isinstance(item, dict):
                continue
            person_id = item.get("person_id")
            channel = item.get("channel")
            external_user_id = item.get("external_user_id")
            if not (person_id and channel and external_user_id):
                continue
            bindings.append(
                ChannelIdentity(
                    person_id=str(person_id),
                    channel=str(channel),
                    external_user_id=str(external_user_id),
                    is_verified=bool(item.get("is_verified", False)),
                )
            )

        return people, bindings

    def save(self, people: dict[str, Person], bindings: list[ChannelIdentity]) -> None:
        """Persist people and bindings to disk."""

        data = {
            "version": 1,
            "people": [
                {
                    "person_id": person.person_id,
                    "display_name": person.display_name,
                    "primary_channel": person.primary_channel,
                    "trusted_channels": person.trusted_channels,
                    "preferences": person.preferences,
                }
                for person in sorted(people.values(), key=lambda p: p.person_id)
            ],
            "bindings": [
                {
                    "person_id": binding.person_id,
                    "channel": binding.channel,
                    "external_user_id": binding.external_user_id,
                    "is_verified": binding.is_verified,
                }
                for binding in sorted(bindings, key=lambda b: (b.person_id, b.channel, b.external_user_id))
            ],
        }
        self.store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_person(self, person_id: str) -> Person | None:
        """Return a person by id."""

        people, _ = self.load()
        return people.get(person_id)

    def find_binding(self, channel: str, external_user_id: str) -> ChannelIdentity | None:
        """Find a binding by channel identity."""

        _, bindings = self.load()
        for binding in bindings:
            if binding.channel == channel and binding.external_user_id == external_user_id:
                return binding
        return None


    def find_binding_for_person(self, person_id: str, channel: str) -> ChannelIdentity | None:
        """Find a channel binding for a specific person."""

        _, bindings = self.load()
        for binding in bindings:
            if binding.person_id == person_id and binding.channel == channel:
                return binding
        return None
    def upsert_person(self, person: Person) -> None:
        """Create or replace a person record."""

        people, bindings = self.load()
        people[person.person_id] = person
        self.save(people, bindings)

    def bind_identity(
        self,
        person_id: str,
        channel: str,
        external_user_id: str,
        *,
        is_verified: bool = True,
    ) -> None:
        """Create or replace a channel binding."""

        people, bindings = self.load()
        new_binding = ChannelIdentity(
            person_id=person_id,
            channel=channel,
            external_user_id=external_user_id,
            is_verified=is_verified,
        )
        updated = [b for b in bindings if not (b.channel == channel and b.external_user_id == external_user_id)]
        updated.append(new_binding)
        self.save(people, updated)
