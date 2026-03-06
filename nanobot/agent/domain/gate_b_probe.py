"""Minimal runtime agent used to validate Gate B orchestration flows."""

from __future__ import annotations

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.types import DomainAgentRequest, DomainAgentResult, DomainRunStatus


class GateBProbeAgent(BaseDomainAgent):
    """Deterministic probe agent for sync/async/event Gate B validation."""

    name = "gate-b-probe"

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"gate-b sync:{request.goal}",
            suggested_user_reply=f"gate-b sync:{request.goal}",
            artifacts={"context_key": self.context_key(request), "reply_mode": request.reply_mode.value},
        )

    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"gate-b async:{request.goal}",
            suggested_user_reply=f"gate-b async:{request.goal}",
            notify_intent=True,
            artifacts={"context_key": self.context_key(request), "reply_mode": request.reply_mode.value},
        )

    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"gate-b event:{request.goal}",
            suggested_user_reply=f"gate-b event:{request.goal}",
            artifacts={"context_key": self.context_key(request), "reply_mode": request.reply_mode.value},
        )


def create_gate_b_probe_agent() -> GateBProbeAgent:
    """Factory entrypoint used by runtime assembly."""

    return GateBProbeAgent()
