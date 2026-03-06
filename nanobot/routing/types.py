"""Session and routing protocol types."""

from dataclasses import dataclass
from enum import Enum


class SurfaceKind(str, Enum):
    """Interaction surface classification."""

    DM = "dm"
    GROUP = "group"
    THREAD = "thread"
    CLI = "cli"
    SYSTEM = "system"


class SharingMode(str, Enum):
    """How a surface maps to a session key."""

    ISOLATED = "isolated"
    TRUSTED_DIRECT = "trusted_direct"
    THREAD_SCOPED = "thread_scoped"


@dataclass
class SessionResolutionResult:
    """Resolved session target for an inbound event."""

    session_key: str
    surface_id: str
    sharing_mode: SharingMode
    reason: str = ""
