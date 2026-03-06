"""Outbound notification routing for learning-assistant flows."""

from __future__ import annotations

from typing import Any

from nanobot.agent.domain.types import NotificationDecision, NotificationKind
from nanobot.bus.events import OutboundMessage
from nanobot.identity import IdentityStore, Person


class NotificationRouter:
    """Resolve outbound notification targets without changing channel senders."""

    DIRECT_CHANNELS: tuple[str, ...] = ("feishu", "cli")

    def __init__(
        self,
        store: IdentityStore,
        *,
        deliverable_channels: set[str] | None = None,
    ):
        self.store = store
        self._deliverable_channels = set(deliverable_channels or self.DIRECT_CHANNELS)

    def set_deliverable_channels(self, channels: set[str]) -> None:
        """Update currently enabled outbound channels."""

        self._deliverable_channels = set(channels)

    def route_outbound(self, msg: OutboundMessage) -> NotificationDecision | None:
        """Route an outbound message if it declares notification metadata."""

        notification = self._notification_metadata(msg)
        if notification is None:
            return None

        kind = self._parse_kind(notification.get("kind"))
        if kind is None:
            self._record_drop(msg, "invalid notification kind")
            return None

        if kind is NotificationKind.REPLY:
            return self.route_reply(msg, notification)
        if kind is NotificationKind.PROACTIVE:
            return self.route_proactive(msg, notification)
        return self.route_confirmation(msg, notification)

    def route_reply(
        self,
        msg: OutboundMessage,
        notification: dict[str, Any] | None = None,
    ) -> NotificationDecision:
        """Replies always return to the origin surface."""

        notification = notification or self._notification_metadata(msg) or {}
        target_channel = str(notification.get("origin_channel") or msg.channel)
        target_chat_id = str(notification.get("origin_chat_id") or msg.chat_id)
        decision = NotificationDecision(
            kind=NotificationKind.REPLY,
            target_channel=target_channel,
            target_chat_id=target_chat_id,
            requires_primary_agent=True,
            reason="reply routed to origin surface",
        )
        self._record_delivery(msg, decision)
        return decision

    def route_proactive(
        self,
        msg: OutboundMessage,
        notification: dict[str, Any] | None = None,
    ) -> NotificationDecision | None:
        """Route proactive reminders to a deliverable direct channel."""

        notification = notification or self._notification_metadata(msg) or {}
        person = self._require_person(msg, notification, kind=NotificationKind.PROACTIVE)
        if person is None:
            return None

        for channel in self._candidate_channels(person):
            if not self._is_direct_deliverable(channel):
                continue
            binding = self.store.find_binding_for_person(person.person_id, channel)
            if binding is None:
                continue
            decision = NotificationDecision(
                kind=NotificationKind.PROACTIVE,
                target_channel=channel,
                target_chat_id=binding.external_user_id,
                requires_primary_agent=False,
                reason=self._channel_reason(person, channel, trusted_only=False),
            )
            self._record_delivery(msg, decision)
            return decision

        self._record_drop(msg, "no deliverable direct channel for proactive notification")
        return None

    def route_confirmation(
        self,
        msg: OutboundMessage,
        notification: dict[str, Any] | None = None,
    ) -> NotificationDecision | None:
        """Route confirmations only to trusted direct channels."""

        notification = notification or self._notification_metadata(msg) or {}
        person = self._require_person(msg, notification, kind=NotificationKind.CONFIRMATION)
        if person is None:
            return None

        trusted_channels = set(person.trusted_channels)
        for channel in self._candidate_channels(person):
            if channel not in trusted_channels or not self._is_direct_deliverable(channel):
                continue
            binding = self.store.find_binding_for_person(person.person_id, channel)
            if binding is None:
                continue
            decision = NotificationDecision(
                kind=NotificationKind.CONFIRMATION,
                target_channel=channel,
                target_chat_id=binding.external_user_id,
                requires_primary_agent=False,
                reason=self._channel_reason(person, channel, trusted_only=True),
            )
            self._record_delivery(msg, decision)
            return decision

        self._record_drop(msg, "no trusted direct channel available for confirmation")
        return None

    def _require_person(
        self,
        msg: OutboundMessage,
        notification: dict[str, Any],
        *,
        kind: NotificationKind,
    ) -> Person | None:
        person_id = notification.get("person_id")
        if not person_id:
            self._record_drop(msg, f"missing person_id for {kind.value}")
            return None

        person = self.store.get_person(str(person_id))
        if person is None:
            self._record_drop(msg, f"unknown person: {person_id}")
            return None
        return person

    def _candidate_channels(self, person: Person) -> list[str]:
        candidates: list[str] = []
        if person.primary_channel:
            candidates.append(person.primary_channel)
        for channel in self.DIRECT_CHANNELS:
            if channel not in candidates:
                candidates.append(channel)
        return candidates

    def _is_direct_deliverable(self, channel: str) -> bool:
        return channel in self.DIRECT_CHANNELS and channel in self._deliverable_channels

    @staticmethod
    def _parse_kind(value: Any) -> NotificationKind | None:
        if isinstance(value, NotificationKind):
            return value
        if isinstance(value, str):
            try:
                return NotificationKind(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _channel_reason(person: Person, channel: str, *, trusted_only: bool) -> str:
        if channel == person.primary_channel:
            return "primary trusted direct channel" if trusted_only else "primary direct channel"
        return "trusted fallback direct channel" if trusted_only else "fallback direct channel"

    @staticmethod
    def _notification_metadata(msg: OutboundMessage) -> dict[str, Any] | None:
        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        if "notification" not in metadata:
            return None
        notification = metadata.get("notification")
        if isinstance(notification, dict):
            return notification
        metadata["notification"] = {}
        return metadata["notification"]

    @staticmethod
    def _record_delivery(msg: OutboundMessage, decision: NotificationDecision) -> None:
        notification = NotificationRouter._ensure_notification(msg)
        notification["decision"] = {
            "deliver": True,
            "kind": decision.kind.value,
            "target_channel": decision.target_channel,
            "target_chat_id": decision.target_chat_id,
            "reason": decision.reason,
        }

    @staticmethod
    def _record_drop(msg: OutboundMessage, reason: str) -> None:
        notification = NotificationRouter._ensure_notification(msg)
        notification["decision"] = {
            "deliver": False,
            "kind": notification.get("kind"),
            "reason": reason,
        }

    @staticmethod
    def _ensure_notification(msg: OutboundMessage) -> dict[str, Any]:
        if not isinstance(msg.metadata, dict):
            msg.metadata = {}
        notification = msg.metadata.get("notification")
        if not isinstance(notification, dict):
            notification = {}
            msg.metadata["notification"] = notification
        return notification
