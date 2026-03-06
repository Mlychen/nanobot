"""Identity resolution and metadata enrichment."""

from __future__ import annotations

from typing import Any

from nanobot.identity.models import IdentityResolutionResult, Person
from nanobot.identity.store import IdentityStore
from nanobot.routing.types import SurfaceKind


class IdentityMapper:
    """Resolve inbound channel identities to a unified person id."""

    def __init__(self, store: IdentityStore):
        self.store = store

    def resolve_person(
        self,
        channel: str,
        sender_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> IdentityResolutionResult:
        """Resolve a person from channel identity and message metadata."""

        metadata = metadata or {}
        binding = self.store.find_binding(channel, str(sender_id))
        surface_kind = self._detect_surface_kind(channel, metadata).value
        if binding is None:
            return IdentityResolutionResult(
                resolved=False,
                person_id=None,
                channel=channel,
                external_user_id=str(sender_id),
                surface_kind=surface_kind,
                trusted=False,
                reason="unbound identity",
            )

        person = self.store.get_person(binding.person_id)
        trusted = bool(person and channel in person.trusted_channels)
        reason = "mapped identity"
        if person is None:
            reason = "binding exists but person record missing"

        return IdentityResolutionResult(
            resolved=person is not None,
            person_id=binding.person_id if person is not None else None,
            channel=channel,
            external_user_id=str(sender_id),
            surface_kind=surface_kind,
            trusted=trusted,
            reason=reason,
        )

    def enrich_metadata(
        self,
        channel: str,
        sender_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach identity resolution results to message metadata."""

        enriched = dict(metadata or {})
        result = self.resolve_person(channel, sender_id, enriched)
        enriched["person_id"] = result.person_id
        enriched["identity"] = {
            "resolved": result.resolved,
            "person_id": result.person_id,
            "channel": result.channel,
            "external_user_id": result.external_user_id,
            "surface_kind": result.surface_kind,
            "trusted": result.trusted,
            "reason": result.reason,
        }
        return enriched

    def bind_identity(
        self,
        person_id: str,
        channel: str,
        external_user_id: str,
        *,
        is_verified: bool = True,
    ) -> None:
        """Persist a channel binding."""

        self.store.bind_identity(
            person_id=person_id,
            channel=channel,
            external_user_id=external_user_id,
            is_verified=is_verified,
        )

    def upsert_person(self, person: Person) -> None:
        """Persist a person definition."""

        self.store.upsert_person(person)

    @staticmethod
    def _detect_surface_kind(channel: str, metadata: dict[str, Any]) -> SurfaceKind:
        """Infer surface type from channel and message metadata."""

        if channel == "cli":
            return SurfaceKind.CLI
        if channel == "system":
            return SurfaceKind.SYSTEM
        if metadata.get("thread_ts") or metadata.get("thread_id"):
            return SurfaceKind.THREAD
        if metadata.get("chat_type") == "group" or metadata.get("channel_type") in {"channel", "group"}:
            return SurfaceKind.GROUP
        return SurfaceKind.DM
