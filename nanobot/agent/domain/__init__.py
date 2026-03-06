"""Domain-agent protocols and registry."""

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.registry import DomainAgentRegistry
from nanobot.agent.domain.runtime import DomainAgentFactory, create_domain_registry
from nanobot.agent.domain.types import (
    AsyncDomainJob,
    AsyncJobStatus,
    DomainAgentDescriptor,
    DomainAgentRequest,
    DomainAgentResult,
    DomainContextScope,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
    NotificationDecision,
    NotificationKind,
)

__all__ = [
    "AsyncDomainJob",
    "AsyncJobStatus",
    "BaseDomainAgent",
    "DomainAgentDescriptor",
    "DomainAgentFactory",
    "DomainAgentRegistry",
    "DomainAgentRequest",
    "DomainAgentResult",
    "DomainContextScope",
    "DomainReplyMode",
    "DomainRunStatus",
    "DomainTrigger",
    "NotificationDecision",
    "NotificationKind",
    "create_domain_registry",
]
