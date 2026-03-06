"""Domain-agent protocols and registry."""

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.registry import DomainAgentRegistry
from nanobot.agent.domain.types import (
    AsyncDomainJob,
    DomainAgentRequest,
    DomainAgentResult,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
    NotificationDecision,
    NotificationKind,
)

__all__ = [
    "AsyncDomainJob",
    "BaseDomainAgent",
    "DomainAgentRegistry",
    "DomainAgentRequest",
    "DomainAgentResult",
    "DomainReplyMode",
    "DomainRunStatus",
    "DomainTrigger",
    "NotificationDecision",
    "NotificationKind",
]
