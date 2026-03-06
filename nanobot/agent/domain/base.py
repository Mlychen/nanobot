"""Base interface for domain agents."""

from abc import ABC, abstractmethod

from nanobot.agent.domain.types import (
    DomainAgentDescriptor,
    DomainAgentRequest,
    DomainAgentResult,
    DomainContextScope,
    DomainReplyMode,
)


class BaseDomainAgent(ABC):
    """Abstract base for long-lived domain agents."""

    name: str
    supports_modes: tuple[DomainReplyMode, ...] = (
        DomainReplyMode.SYNC,
        DomainReplyMode.ASYNC,
        DomainReplyMode.EVENT,
    )
    allowed_tools: tuple[str, ...] = ()
    context_scope: DomainContextScope = DomainContextScope.PERSON

    def supports(self, mode: DomainReplyMode) -> bool:
        """Return whether the agent supports a given invocation mode."""

        return mode in self.supports_modes

    def describe(self) -> DomainAgentDescriptor:
        """Return the runtime contract exposed to orchestrators and installers."""

        return DomainAgentDescriptor(
            name=self.name,
            supports_modes=self.supports_modes,
            allowed_tools=self.allowed_tools,
            context_scope=self.context_scope,
        )

    def context_key(self, request: DomainAgentRequest) -> str:
        """Build a stable storage key for domain-local context."""

        if self.context_scope is DomainContextScope.PERSON:
            scope_value = request.person_id or request.session_key or request.surface_id
        elif self.context_scope is DomainContextScope.SESSION:
            scope_value = request.session_key
        elif self.context_scope is DomainContextScope.SURFACE:
            scope_value = request.surface_id
        else:
            scope_value = request.trigger.value if request.trigger else request.surface_id
        return f"{self.name}:{self.context_scope.value}:{scope_value}"

    @abstractmethod
    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Handle a synchronous request."""

    @abstractmethod
    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Handle an asynchronous request."""

    @abstractmethod
    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Handle an event-triggered request."""
