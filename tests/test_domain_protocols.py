from nanobot.agent.domain import (
    AsyncJobStatus,
    BaseDomainAgent,
    DomainAgentRegistry,
    DomainAgentRequest,
    DomainAgentResult,
    DomainContextScope,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
    NotificationDecision,
    NotificationKind,
    create_domain_registry,
)
from nanobot.identity import IdentityResolutionResult, Person
from nanobot.routing import SessionResolutionResult, SharingMode, SurfaceKind


class StubAgent(BaseDomainAgent):
    name = "scheduler"
    allowed_tools = ("cron.schedule", "memory.write")
    context_scope = DomainContextScope.PERSON

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


class BrokenAsyncAgent(BaseDomainAgent):
    name = "broken"
    supports_modes = (DomainReplyMode.ASYNC,)
    context_scope = DomainContextScope.SYSTEM

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        raise AssertionError("sync should not be used")

    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        raise RuntimeError("boom")

    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        raise AssertionError("event should not be used")


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


def test_domain_agent_descriptor_exposes_runtime_contract() -> None:
    agent = StubAgent()
    request = DomainAgentRequest(
        request_id="r0",
        agent_name="scheduler",
        person_id="p1",
        surface_id="feishu:dm:ou_123",
        session_key="person:p1:direct",
        goal="build today's plan",
    )

    descriptor = agent.describe()

    assert descriptor.name == "scheduler"
    assert descriptor.allowed_tools == ("cron.schedule", "memory.write")
    assert descriptor.context_scope is DomainContextScope.PERSON
    assert agent.context_key(request) == "scheduler:person:p1"


def test_domain_registry_supports_bulk_registration_and_descriptors() -> None:
    registry = DomainAgentRegistry([StubAgent()])

    assert registry.list_agents() == ["scheduler"]
    assert registry.describe("scheduler").allowed_tools == ("cron.schedule", "memory.write")
    assert registry.list_descriptors()[0].context_scope is DomainContextScope.PERSON


def test_create_domain_registry_supports_factories() -> None:
    registry = create_domain_registry(factories=[StubAgent])

    assert registry.list_agents() == ["scheduler"]
    assert registry.describe("scheduler").name == "scheduler"


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
    registry = DomainAgentRegistry([StubAgent()])
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
    assert finished.completed_at is not None
    assert registry.list_jobs(status=AsyncJobStatus.COMPLETED)[0].job_id == job.job_id


async def test_domain_registry_exposes_finished_jobs_for_downstream_consumers() -> None:
    registry = DomainAgentRegistry([StubAgent()])
    request = DomainAgentRequest(
        request_id="r2b",
        agent_name="scheduler",
        person_id="p1",
        surface_id="feishu:dm:ou_123",
        session_key="feishu:ou_123",
        goal="send reminder",
        reply_mode=DomainReplyMode.ASYNC,
        trigger=DomainTrigger.USER,
    )

    job = await registry.dispatch_async(request)
    await registry.wait_for_job(job.job_id)

    finished_jobs = registry.consume_finished_jobs()

    assert [item.job_id for item in finished_jobs] == [job.job_id]
    assert finished_jobs[0].result is not None
    assert finished_jobs[0].result.notify_intent is True
    assert registry.consume_finished_jobs() == []


async def test_domain_registry_async_failures_are_observable() -> None:
    registry = DomainAgentRegistry([BrokenAsyncAgent()])
    request = DomainAgentRequest(
        request_id="r2c",
        agent_name="broken",
        person_id=None,
        surface_id="system:heartbeat",
        session_key="heartbeat",
        goal="run maintenance",
        reply_mode=DomainReplyMode.ASYNC,
        trigger=DomainTrigger.SYSTEM,
    )

    job = await registry.dispatch_async(request)
    finished = await registry.wait_for_job(job.job_id)

    assert finished.status is AsyncJobStatus.FAILED
    assert finished.result is not None
    assert finished.result.status is DomainRunStatus.ERROR
    assert finished.error == "boom"
    assert registry.consume_finished_jobs()[0].job_id == job.job_id


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
