"""Base interface for domain agents."""

from abc import ABC, abstractmethod

from nanobot.agent.domain.types import DomainAgentRequest, DomainAgentResult, DomainReplyMode


class BaseDomainAgent(ABC):
    """Abstract base for long-lived domain agents."""

    name: str
    supports_modes: tuple[DomainReplyMode, ...] = (
        DomainReplyMode.SYNC,
        DomainReplyMode.ASYNC,
        DomainReplyMode.EVENT,
    )
    allowed_tools: tuple[str, ...] = ()

    def supports(self, mode: DomainReplyMode) -> bool:
        """Return whether the agent supports a given invocation mode."""

        return mode in self.supports_modes

    @abstractmethod
    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Handle a synchronous request."""

    @abstractmethod
    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Handle an asynchronous request."""

    @abstractmethod
    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Handle an event-triggered request."""
