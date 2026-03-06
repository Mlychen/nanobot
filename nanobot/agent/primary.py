"""Primary-agent orchestration for domain routing."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.domain import (
    DomainAgentDescriptor,
    DomainAgentRegistry,
    DomainAgentRequest,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
)
from nanobot.bus.events import InboundMessage, OutboundMessage


class PrimaryDecisionType(str, Enum):
    """Normalized orchestrator decision types."""

    DIRECT_ANSWER = "direct_answer"
    DELEGATE_SYNC = "delegate_sync"
    DELEGATE_ASYNC = "delegate_async"
    DISPATCH_EVENT = "dispatch_event"


@dataclass
class PrimaryDecision:
    """A concrete orchestration choice for a single inbound message."""

    decision_type: PrimaryDecisionType
    agent_name: str | None = None
    goal: str = ""
    trigger: DomainTrigger = DomainTrigger.USER
    constraints: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class PrimaryAgentOrchestrator:
    """Deterministic orchestration layer on top of the main agent loop."""

    _COMMAND_RE = re.compile(
        r"^/(?P<command>agent|delegate-sync|delegate-async|dispatch-event)"
        r"\s+(?P<agent>[a-zA-Z0-9_-]+)(?:\s+(?P<goal>.+))?$",
        re.IGNORECASE,
    )

    def __init__(self, registry: DomainAgentRegistry):
        self.registry = registry

    def list_agent_descriptors(self) -> list[DomainAgentDescriptor]:
        """Expose runtime descriptors for orchestration and inspection."""

        return self.registry.list_descriptors()

    def describe_agent(self, agent_name: str) -> DomainAgentDescriptor | None:
        """Return the runtime descriptor for a single agent if registered."""

        try:
            return self.registry.describe(agent_name)
        except KeyError:
            return None

    def consume_finished_notifications(self) -> list[OutboundMessage]:
        """Drain finished async jobs into outbound notifications."""

        messages: list[OutboundMessage] = []
        for job in self.registry.consume_finished_jobs():
            if notification := self._finished_job_notification(job):
                messages.append(notification)
        return messages

    def _finished_job_notification(self, job) -> OutboundMessage | None:
        request = self.registry.request_for_job(job.job_id)
        result = job.result
        if request is None or result is None or not result.notify_intent:
            return None

        content = self._render_finished_job_reply(result)
        origin = self._notification_origin(request)
        if not content or origin is None:
            return None

        channel, chat_id, trusted, surface_kind = origin
        metadata: dict[str, Any] = {
            "async_job": {
                "job_id": job.job_id,
                "agent_name": job.agent_name,
                "request_id": job.request_id,
                "status": job.status.value,
            }
        }
        if request.person_id:
            metadata["notification"] = {
                "kind": "proactive",
                "person_id": request.person_id,
                "origin_channel": channel,
                "origin_chat_id": chat_id,
                "trusted": trusted,
                "surface_kind": surface_kind,
            }

        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            metadata=metadata,
        )


    async def handle_inbound(
        self,
        msg: InboundMessage,
        *,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Handle an inbound message if the orchestrator can deterministically own it."""

        del on_progress  # Reserved for future orchestration progress updates.

        decision = self.decide(msg)
        if decision.decision_type is PrimaryDecisionType.DIRECT_ANSWER:
            return None

        if decision.decision_type is PrimaryDecisionType.DISPATCH_EVENT:
            channel, chat_id = self._resolve_outbound_target(msg)
            content = await self.handle_event(
                agent_name=decision.agent_name,
                goal=decision.goal,
                trigger=decision.trigger,
                channel=channel,
                chat_id=chat_id,
                person_id=self._person_id(msg.metadata),
                session_key=self._session_key(msg),
                surface_id=self._surface_id(msg),
                metadata=msg.metadata,
                constraints=decision.constraints,
                artifacts=decision.artifacts,
            )
            if content is None:
                return None
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=content,
                metadata=msg.metadata or {},
            )

        if not decision.agent_name:
            return None

        reply_mode = (
            DomainReplyMode.SYNC
            if decision.decision_type is PrimaryDecisionType.DELEGATE_SYNC
            else DomainReplyMode.ASYNC
        )
        if not self._supports_mode(decision.agent_name, reply_mode):
            logger.debug(
                "Primary orchestrator fallback: agent {} does not support {}",
                decision.agent_name,
                reply_mode.value,
            )
            return None

        request = self._build_request(
            msg=msg,
            agent_name=decision.agent_name,
            goal=decision.goal,
            reply_mode=reply_mode,
            trigger=decision.trigger,
            constraints=decision.constraints,
            artifacts=decision.artifacts,
        )

        try:
            if decision.decision_type is PrimaryDecisionType.DELEGATE_SYNC:
                result = await self.registry.invoke_sync(request)
                if result.status is DomainRunStatus.ERROR:
                    return None
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=self._render_sync_reply(result),
                    metadata=msg.metadata or {},
                )

            job = await self.registry.dispatch_async(request)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=self._render_async_reply(decision.agent_name, job.job_id),
                metadata=msg.metadata or {},
            )
        except KeyError:
            logger.debug("Primary orchestrator fallback: unknown agent {}", decision.agent_name)
            return None
        except Exception:
            logger.exception(
                "Primary orchestrator fallback: failed to handle {} for {}",
                decision.decision_type.value,
                decision.agent_name,
            )
            return None

    async def handle_event(
        self,
        *,
        agent_name: str | None,
        goal: str,
        trigger: DomainTrigger,
        channel: str,
        chat_id: str,
        person_id: str | None = None,
        session_key: str | None = None,
        surface_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> str | None:
        """Dispatch an event-triggered domain request, returning user-safe text if handled."""

        if not agent_name or not self._supports_mode(agent_name, DomainReplyMode.EVENT):
            return None

        request = DomainAgentRequest(
            request_id=self._new_request_id(),
            agent_name=agent_name,
            person_id=person_id,
            surface_id=surface_id or f"{channel}:{chat_id}",
            session_key=session_key or f"{channel}:{chat_id}",
            goal=goal,
            constraints=dict(constraints or {}),
            artifacts=dict(artifacts or self._extract_artifacts(metadata)),
            reply_mode=DomainReplyMode.EVENT,
            trigger=trigger,
        )

        try:
            result = await self.registry.dispatch_event(request)
        except KeyError:
            logger.debug("Primary orchestrator event fallback: unknown agent {}", agent_name)
            return None
        except Exception:
            logger.exception(
                "Primary orchestrator event fallback: failed to dispatch {}",
                agent_name,
            )
            return None

        if result.status is DomainRunStatus.ERROR:
            return None
        return self._render_event_reply(result)

    def decide(self, msg: InboundMessage) -> PrimaryDecision:
        """Choose a deterministic routing decision for an inbound message."""

        metadata = msg.metadata or {}
        if event_decision := self._metadata_event_decision(metadata):
            return event_decision

        if msg.channel == "system" and msg.sender_id in {"cron", "heartbeat"}:
            return PrimaryDecision(
                decision_type=PrimaryDecisionType.DISPATCH_EVENT,
                agent_name=None,
                goal=msg.content,
                trigger=DomainTrigger.SYSTEM,
                reason="system sender event",
            )

        if routed := self._metadata_delegate_decision(metadata):
            return routed

        if explicit := self._parse_command(msg.content):
            return explicit

        return PrimaryDecision(
            decision_type=PrimaryDecisionType.DIRECT_ANSWER,
            goal=msg.content,
            reason="fallback to main agent loop",
        )

    def _metadata_event_decision(self, metadata: dict[str, Any]) -> PrimaryDecision | None:
        orchestrator = self._orchestrator_metadata(metadata)
        trigger = self._coerce_trigger(orchestrator.get("trigger") or metadata.get("trigger"))
        if trigger not in {DomainTrigger.CRON, DomainTrigger.HEARTBEAT, DomainTrigger.SYSTEM}:
            return None

        return PrimaryDecision(
            decision_type=PrimaryDecisionType.DISPATCH_EVENT,
            agent_name=self._extract_agent_name(metadata),
            goal=str(orchestrator.get("goal") or metadata.get("goal") or ""),
            trigger=trigger,
            constraints=self._extract_constraints(metadata),
            artifacts=self._extract_artifacts(metadata),
            reason="metadata event routing",
        )

    def _metadata_delegate_decision(self, metadata: dict[str, Any]) -> PrimaryDecision | None:
        agent_name = self._extract_agent_name(metadata)
        if not agent_name:
            return None

        orchestrator = self._orchestrator_metadata(metadata)
        reply_mode = self._coerce_reply_mode(orchestrator.get("reply_mode") or metadata.get("reply_mode"))
        if reply_mode is None:
            reply_mode = DomainReplyMode.SYNC

        decision_type = (
            PrimaryDecisionType.DELEGATE_ASYNC
            if reply_mode is DomainReplyMode.ASYNC
            else PrimaryDecisionType.DELEGATE_SYNC
        )

        return PrimaryDecision(
            decision_type=decision_type,
            agent_name=agent_name,
            goal=str(orchestrator.get("goal") or metadata.get("goal") or ""),
            trigger=self._coerce_trigger(orchestrator.get("trigger") or metadata.get("trigger"))
            or DomainTrigger.USER,
            constraints=self._extract_constraints(metadata),
            artifacts=self._extract_artifacts(metadata),
            reason="metadata delegation",
        )

    def _parse_command(self, content: str) -> PrimaryDecision | None:
        match = self._COMMAND_RE.match(content.strip())
        if not match:
            return None

        command = match.group("command").lower()
        agent_name = match.group("agent")
        goal = (match.group("goal") or "").strip()

        if command == "delegate-async":
            return PrimaryDecision(
                decision_type=PrimaryDecisionType.DELEGATE_ASYNC,
                agent_name=agent_name,
                goal=goal,
                trigger=DomainTrigger.USER,
                reason="explicit async command",
            )
        if command == "dispatch-event":
            return PrimaryDecision(
                decision_type=PrimaryDecisionType.DISPATCH_EVENT,
                agent_name=agent_name,
                goal=goal,
                trigger=DomainTrigger.SYSTEM,
                reason="explicit event command",
            )

        return PrimaryDecision(
            decision_type=PrimaryDecisionType.DELEGATE_SYNC,
            agent_name=agent_name,
            goal=goal,
            trigger=DomainTrigger.USER,
            reason="explicit sync command",
        )

    def _supports_mode(self, agent_name: str | None, mode: DomainReplyMode) -> bool:
        if not agent_name:
            return False
        descriptor = self.describe_agent(agent_name)
        return descriptor is not None and mode in descriptor.supports_modes

    def _build_request(
        self,
        *,
        msg: InboundMessage,
        agent_name: str,
        goal: str,
        reply_mode: DomainReplyMode,
        trigger: DomainTrigger,
        constraints: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> DomainAgentRequest:
        return DomainAgentRequest(
            request_id=self._new_request_id(),
            agent_name=agent_name,
            person_id=self._person_id(msg.metadata),
            surface_id=self._surface_id(msg),
            session_key=self._session_key(msg),
            goal=goal,
            constraints=dict(constraints or {}),
            artifacts=self._request_artifacts(msg, artifacts),
            reply_mode=reply_mode,
            trigger=trigger,
        )

    def _request_artifacts(
        self,
        msg: InboundMessage,
        artifacts: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(artifacts or self._extract_artifacts(msg.metadata))
        identity = (msg.metadata or {}).get("identity")
        origin = merged.get("notification_origin") if isinstance(merged.get("notification_origin"), dict) else {}
        if not isinstance(identity, dict):
            identity = {}

        origin = dict(origin)
        origin.setdefault("channel", msg.channel)
        origin.setdefault("chat_id", msg.chat_id)
        origin.setdefault("trusted", bool(identity.get("trusted", False)))
        if identity.get("surface_kind"):
            origin.setdefault("surface_kind", identity["surface_kind"])
        merged["notification_origin"] = origin
        return merged

    @staticmethod
    def _notification_origin(request: DomainAgentRequest) -> tuple[str, str, bool, str] | None:
        artifacts = request.artifacts if isinstance(request.artifacts, dict) else {}
        origin = artifacts.get("notification_origin") if isinstance(artifacts.get("notification_origin"), dict) else {}
        channel = origin.get("channel")
        chat_id = origin.get("chat_id")

        if not channel or not chat_id:
            parts = request.surface_id.split(":", 2)
            if len(parts) >= 2:
                channel = channel or parts[0]
                chat_id = chat_id or parts[1]

        if not channel or not chat_id:
            return None

        trusted = bool(origin.get("trusted", False))
        surface_kind = str(origin.get("surface_kind") or "dm")
        return str(channel), str(chat_id), trusted, surface_kind

    @staticmethod
    def _render_finished_job_reply(result) -> str | None:
        if result.suggested_user_reply:
            return result.suggested_user_reply.strip()
        if result.summary:
            return result.summary.strip()
        return None

    @staticmethod
    def _render_sync_reply(result) -> str:
        if result.suggested_user_reply:
            return result.suggested_user_reply.strip()
        if result.summary:
            return result.summary.strip()
        if result.status is DomainRunStatus.SKIPPED:
            return "I checked that, but there was nothing to do."
        return "I handled that request."

    @staticmethod
    def _render_async_reply(agent_name: str, job_id: str) -> str:
        return f"I've started the {agent_name} task in the background. Job ID: {job_id}."

    @staticmethod
    def _render_event_reply(result) -> str | None:
        if result.suggested_user_reply:
            return result.suggested_user_reply.strip()
        if result.summary:
            return result.summary.strip()
        if result.status is DomainRunStatus.SKIPPED:
            return None
        return "I handled that background task."

    @staticmethod
    def _orchestrator_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return {}
        value = metadata.get("orchestrator")
        return value if isinstance(value, dict) else {}

    def _extract_agent_name(self, metadata: dict[str, Any] | None) -> str | None:
        orchestrator = self._orchestrator_metadata(metadata)
        for key in ("agent_name", "domain_agent"):
            value = orchestrator.get(key) or (metadata or {}).get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_constraints(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        orchestrator = self._orchestrator_metadata(metadata)
        value = orchestrator.get("constraints") or (metadata or {}).get("constraints")
        return dict(value) if isinstance(value, dict) else {}

    def _extract_artifacts(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        orchestrator = self._orchestrator_metadata(metadata)
        value = orchestrator.get("artifacts") or (metadata or {}).get("artifacts")
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _coerce_reply_mode(value: Any) -> DomainReplyMode | None:
        if value is None:
            return None
        try:
            return DomainReplyMode(str(value))
        except ValueError:
            return None

    @staticmethod
    def _coerce_trigger(value: Any) -> DomainTrigger | None:
        if value is None:
            return None
        try:
            return DomainTrigger(str(value))
        except ValueError:
            return None

    @staticmethod
    def _person_id(metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("person_id")
        return str(value) if value else None

    @staticmethod
    def _surface_id(msg: InboundMessage) -> str:
        session_meta = (msg.metadata or {}).get("session")
        if isinstance(session_meta, dict):
            surface_id = session_meta.get("surface_id")
            if isinstance(surface_id, str) and surface_id:
                return surface_id
        return f"{msg.channel}:{msg.chat_id}"

    @staticmethod
    def _session_key(msg: InboundMessage) -> str:
        session_meta = (msg.metadata or {}).get("session")
        if isinstance(session_meta, dict):
            session_key = session_meta.get("session_key")
            if isinstance(session_key, str) and session_key:
                return session_key
        return msg.session_key

    @staticmethod
    def _resolve_outbound_target(msg: InboundMessage) -> tuple[str, str]:
        if msg.channel == "system" and ":" in msg.chat_id:
            channel, chat_id = msg.chat_id.split(":", 1)
            return channel, chat_id
        return msg.channel, msg.chat_id

    @staticmethod
    def _new_request_id() -> str:
        return str(uuid.uuid4())[:8]




