"""Shared protocols for primary/domain-agent coordination."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DomainReplyMode(str, Enum):
    """How a domain agent is invoked."""

    SYNC = "sync"
    ASYNC = "async"
    EVENT = "event"


class DomainContextScope(str, Enum):
    """How a domain agent scopes its local runtime context."""

    PERSON = "person"
    SESSION = "session"
    SURFACE = "surface"
    SYSTEM = "system"


class DomainTrigger(str, Enum):
    """What initiated a domain-agent request."""

    USER = "user"
    CRON = "cron"
    HEARTBEAT = "heartbeat"
    SYSTEM = "system"


class DomainRunStatus(str, Enum):
    """Normalized execution result for domain-agent runs."""

    OK = "ok"
    ERROR = "error"
    ACCEPTED = "accepted"
    SKIPPED = "skipped"


class NotificationKind(str, Enum):
    """Outbound notification category."""

    REPLY = "reply"
    PROACTIVE = "proactive"
    CONFIRMATION = "confirmation"


class AsyncJobStatus(str, Enum):
    """Lifecycle state for async domain jobs."""

    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DomainAgentRequest:
    """Request issued by the primary agent or a system trigger."""

    request_id: str
    agent_name: str
    person_id: str | None
    surface_id: str
    session_key: str
    goal: str
    constraints: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    reply_mode: DomainReplyMode = DomainReplyMode.SYNC
    trigger: DomainTrigger = DomainTrigger.USER


@dataclass
class DomainAgentResult:
    """Structured result returned by a domain agent."""

    request_id: str
    agent_name: str
    status: DomainRunStatus
    summary: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)
    memory_updates: dict[str, Any] = field(default_factory=dict)
    notify_intent: bool = False
    suggested_user_reply: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class DomainAgentDescriptor:
    """Static runtime contract exposed by a domain agent."""

    name: str
    supports_modes: tuple[DomainReplyMode, ...]
    allowed_tools: tuple[str, ...] = ()
    context_scope: DomainContextScope = DomainContextScope.PERSON


@dataclass
class NotificationDecision:
    """A routing decision for outbound delivery."""

    kind: NotificationKind
    target_channel: str
    target_chat_id: str
    requires_primary_agent: bool = True
    reason: str = ""


@dataclass
class AsyncDomainJob:
    """Minimal observable state for an async domain-agent run."""

    job_id: str
    request_id: str
    agent_name: str
    status: AsyncJobStatus = AsyncJobStatus.ACCEPTED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: DomainAgentResult | None = None
    error: str | None = None
