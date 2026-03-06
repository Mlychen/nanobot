"""Session resolution policy for multi-surface assistants."""

from __future__ import annotations

from typing import Any

from nanobot.routing.store import SessionPolicyStore
from nanobot.routing.types import SessionResolutionResult, SharingMode, SurfaceKind


class SessionPolicy:
    """Resolve session keys from channel metadata and identity context."""

    def __init__(self, store: SessionPolicyStore):
        self.store = store

    def resolve_surface_id(
        self,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Return the concrete interaction surface identifier."""

        metadata = metadata or {}
        thread_ref = self._thread_ref(metadata)
        if thread_ref:
            return f"{channel}:{chat_id}:{thread_ref}"
        return f"{channel}:{chat_id}"

    def resolve_session_key(
        self,
        person_id: str | None,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        explicit_session_key: str | None = None,
    ) -> SessionResolutionResult:
        """Resolve the target session for an inbound event."""

        metadata = metadata or {}
        surface_kind = self._detect_surface_kind(channel, metadata)
        surface_id = self.resolve_surface_id(channel, chat_id, metadata)
        thread_ref = self._thread_ref(metadata)

        if explicit_session_key:
            sharing_mode = SharingMode.THREAD_SCOPED if surface_kind == SurfaceKind.THREAD else SharingMode.ISOLATED
            return SessionResolutionResult(
                session_key=explicit_session_key,
                surface_id=surface_id,
                sharing_mode=sharing_mode,
                reason="explicit override",
            )

        if surface_kind == SurfaceKind.THREAD and thread_ref:
            return SessionResolutionResult(
                session_key=surface_id,
                surface_id=surface_id,
                sharing_mode=SharingMode.THREAD_SCOPED,
                reason="thread-scoped surface",
            )

        if surface_kind == SurfaceKind.SYSTEM:
            return SessionResolutionResult(
                session_key=f"system:{chat_id}",
                surface_id=f"{channel}:{chat_id}",
                sharing_mode=SharingMode.ISOLATED,
                reason="system surface",
            )

        if self._should_share_trusted_direct(person_id, channel, surface_kind, metadata):
            return SessionResolutionResult(
                session_key=f"person:{person_id}:direct",
                surface_id=f"{channel}:{chat_id}",
                sharing_mode=SharingMode.TRUSTED_DIRECT,
                reason="trusted direct surface",
            )

        return SessionResolutionResult(
            session_key=f"{channel}:{chat_id}",
            surface_id=f"{channel}:{chat_id}",
            sharing_mode=SharingMode.ISOLATED,
            reason="surface-isolated session",
        )

    @staticmethod
    def enrich_metadata(
        metadata: dict[str, Any] | None,
        result: SessionResolutionResult,
    ) -> dict[str, Any]:
        """Attach session resolution data to metadata."""

        enriched = dict(metadata or {})
        enriched["session"] = {
            "session_key": result.session_key,
            "surface_id": result.surface_id,
            "sharing_mode": result.sharing_mode.value,
            "reason": result.reason,
        }
        return enriched

    def _should_share_trusted_direct(
        self,
        person_id: str | None,
        channel: str,
        surface_kind: SurfaceKind,
        metadata: dict[str, Any],
    ) -> bool:
        if not person_id or surface_kind not in {SurfaceKind.DM, SurfaceKind.CLI}:
            return False

        identity = metadata.get("identity", {})
        if not isinstance(identity, dict):
            return False
        if not identity.get("resolved") or not identity.get("trusted"):
            return False
        if not self.store.trusted_direct_enabled():
            return False
        return channel in self.store.trusted_direct_channels()

    def _detect_surface_kind(self, channel: str, metadata: dict[str, Any]) -> SurfaceKind:
        if channel == "system":
            return SurfaceKind.SYSTEM
        if channel == "cli":
            return SurfaceKind.CLI
        if self._thread_ref(metadata):
            return SurfaceKind.THREAD

        chat_type = metadata.get("chat_type")
        channel_type = metadata.get("channel_type")
        slack_meta = metadata.get("slack")

        if isinstance(slack_meta, dict):
            channel_type = channel_type or slack_meta.get("channel_type")

        if chat_type == "group" or channel_type in {"channel", "group"}:
            return SurfaceKind.GROUP

        identity = metadata.get("identity", {})
        if isinstance(identity, dict):
            surface_kind = identity.get("surface_kind")
            try:
                if surface_kind:
                    return SurfaceKind(surface_kind)
            except ValueError:
                pass

        return SurfaceKind.DM

    @staticmethod
    def _thread_ref(metadata: dict[str, Any]) -> str | None:
        thread_id = metadata.get("thread_id") or metadata.get("thread_ts")
        if thread_id:
            return str(thread_id)

        slack_meta = metadata.get("slack")
        if isinstance(slack_meta, dict) and slack_meta.get("thread_ts"):
            return str(slack_meta["thread_ts"])

        return None
