"""Composition helpers for domain-agent runtime assembly."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.registry import DomainAgentRegistry

DomainAgentFactory = Callable[[], BaseDomainAgent]


def create_domain_registry(
    *,
    agents: Iterable[BaseDomainAgent] = (),
    factories: Iterable[DomainAgentFactory] = (),
) -> DomainAgentRegistry:
    """Create a registry from concrete agents and deferred factories."""

    registry = DomainAgentRegistry()
    registry.register_many(agents)
    for factory in factories:
        registry.register(factory())
    return registry
