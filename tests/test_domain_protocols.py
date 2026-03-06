from nanobot.agent.domain import (
    BaseDomainAgent,
    DomainAgentRegistry,
    DomainAgentRequest,
    DomainAgentResult,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
    NotificationDecision,
    NotificationKind,
)
from nanobot.identity import IdentityResolutionResult, Person
from nanobot.routing import SessionResolutionResult, SharingMode, SurfaceKind


class StubAgent(BaseDomainAgent):
    name = "scheduler"

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"sync:{request.goal}",
        )

    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"async:{request.goal}",
            notify_intent=True,
        )

    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.SKIPPED,
            summary=f"event:{request.goal}",
        )


def test_identity_resolution_result_keeps_minimal_contract() -> None:
    person = Person(person_id="p1", primary_channel="feishu", trusted_channels=["feishu", "cli"])
    result = IdentityResolutionResult(
        resolved=True,
        person_id=person.person_id,
        channel="feishu",
        external_user_id="ou_123",
        surface_kind=SurfaceKind.DM.value,
        trusted=True,
        reason="mapped",
    )
    assert result.resolved is True
    assert result.person_id == "p1"
    assert result.trusted is True


def test_session_resolution_result_uses_string_key_and_sharing_mode() -> None:
    result = SessionResolutionResult(
        session_key="feishu:ou_123",
        surface_id="feishu:dm:ou_123",
        sharing_mode=SharingMode.TRUSTED_DIRECT,
        reason="shared direct session",
    )
    assert result.session_key == "feishu:ou_123"
    assert result.sharing_mode is SharingMode.TRUSTED_DIRECT


def test_notification_decision_captures_routing_contract() -> None:
    decision = NotificationDecision(
        kind=NotificationKind.PROACTIVE,
        target_channel="feishu",
        target_chat_id="ou_123",
        requires_primary_agent=False,
        reason="preferred direct channel",
    )
    assert decision.kind is NotificationKind.PROACTIVE
    assert decision.requires_primary_agent is False


async def test_domain_registry_sync_invocation() -> None:
    registry = DomainAgentRegistry()
    registry.register(StubAgent())
    request = DomainAgentRequest(
        request_id="r1",
        agent_name="scheduler",
        person_id="p1",
        surface_id="feishu:dm:ou_123",
        session_key="feishu:ou_123",
        goal="build today's plan",
        reply_mode=DomainReplyMode.SYNC,
        trigger=DomainTrigger.USER,
    )

    result = await registry.invoke_sync(request)

    assert result.status is DomainRunStatus.OK
    assert result.summary == "sync:build today's plan"


async def test_domain_registry_async_dispatch_tracks_job_state() -> None:
    registry = DomainAgentRegistry()
    registry.register(StubAgent())
    request = DomainAgentRequest(
        request_id="r2",
        agent_name="scheduler",
        person_id="p1",
        surface_id="feishu:dm:ou_123",
        session_key="feishu:ou_123",
        goal="remind me later",
        reply_mode=DomainReplyMode.ASYNC,
        trigger=DomainTrigger.USER,
    )

    job = await registry.dispatch_async(request)
    finished = await registry.wait_for_job(job.job_id)

    assert finished.result is not None
    assert finished.result.status is DomainRunStatus.OK
    assert finished.result.notify_intent is True


async def test_domain_registry_event_dispatch() -> None:
    registry = DomainAgentRegistry()
    registry.register(StubAgent())
    request = DomainAgentRequest(
        request_id="r3",
        agent_name="scheduler",
        person_id="p1",
        surface_id="system:heartbeat",
        session_key="heartbeat",
        goal="check review cadence",
        reply_mode=DomainReplyMode.EVENT,
        trigger=DomainTrigger.HEARTBEAT,
    )

    result = await registry.dispatch_event(request)

    assert result.status is DomainRunStatus.SKIPPED
    assert result.summary == "event:check review cadence"


def test_domain_registry_rejects_duplicate_registration() -> None:
    registry = DomainAgentRegistry()
    registry.register(StubAgent())

    try:
        registry.register(StubAgent())
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("Expected duplicate registration to fail")
