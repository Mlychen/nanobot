"""Identity-layer models for multi-channel assistants."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Person:
    """A unified user identity across channels."""

    person_id: str
    display_name: str | None = None
    primary_channel: str | None = None
    trusted_channels: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelIdentity:
    """A channel-specific identity bound to a person."""

    person_id: str
    channel: str
    external_user_id: str
    is_verified: bool = False


@dataclass
class IdentityResolutionResult:
    """Resolved identity data attached to inbound metadata."""

    resolved: bool
    person_id: str | None
    channel: str
    external_user_id: str
    surface_kind: str | None = None
    trusted: bool = False
    reason: str = ""
