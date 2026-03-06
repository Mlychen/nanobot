"""Registry and minimal runtime shell for domain agents."""

import asyncio
import uuid
from collections import deque
from collections.abc import Iterable
from datetime import datetime

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.types import (
    AsyncDomainJob,
    AsyncJobStatus,
    DomainAgentDescriptor,
    DomainAgentRequest,
    DomainAgentResult,
    DomainReplyMode,
    DomainRunStatus,
)


class DomainAgentRegistry:
    """Register and invoke domain agents via a stable protocol."""

    def __init__(self, agents: Iterable[BaseDomainAgent] | None = None):
        self._agents: dict[str, BaseDomainAgent] = {}
        self._jobs: dict[str, AsyncDomainJob] = {}
        self._requests: dict[str, DomainAgentRequest] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._finished_job_ids: deque[str] = deque()
        if agents:
            self.register_many(agents)

    def register(self, agent: BaseDomainAgent) -> None:
        """Register a domain agent by name."""

        if not getattr(agent, "name", ""):
            raise ValueError("Domain agent must declare a non-empty name")
        if agent.name in self._agents:
            raise ValueError(f"Domain agent already registered: {agent.name}")
        self._agents[agent.name] = agent

    def register_many(self, agents: Iterable[BaseDomainAgent]) -> None:
        """Register multiple agents in a single composition step."""

        for agent in agents:
            self.register(agent)

    def get(self, name: str) -> BaseDomainAgent | None:
        """Return a registered agent if present."""

        return self._agents.get(name)

    def require(self, name: str) -> BaseDomainAgent:
        """Return a registered agent or raise a clear error."""

        agent = self.get(name)
        if agent is None:
            raise KeyError(f"Unknown domain agent: {name}")
        return agent

    def describe(self, name: str) -> DomainAgentDescriptor:
        """Return the runtime contract for a registered agent."""

        return self.require(name).describe()

    def list_agents(self) -> list[str]:
        """Return registered domain-agent names."""

        return sorted(self._agents)

    def list_descriptors(self) -> list[DomainAgentDescriptor]:
        """Return runtime descriptors for all registered agents."""

        return [self._agents[name].describe() for name in self.list_agents()]

    async def invoke_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Invoke a domain agent synchronously."""

        if request.reply_mode is not DomainReplyMode.SYNC:
            raise ValueError("invoke_sync requires reply_mode=sync")
        agent = self.require(request.agent_name)
        if not agent.supports(DomainReplyMode.SYNC):
            raise ValueError(f"Domain agent {agent.name} does not support sync mode")
        return await agent.handle_sync(request)

    async def dispatch_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        """Dispatch an event-triggered request."""

        if request.reply_mode is not DomainReplyMode.EVENT:
            raise ValueError("dispatch_event requires reply_mode=event")
        agent = self.require(request.agent_name)
        if not agent.supports(DomainReplyMode.EVENT):
            raise ValueError(f"Domain agent {agent.name} does not support event mode")
        return await agent.handle_event(request)

    async def dispatch_async(self, request: DomainAgentRequest) -> AsyncDomainJob:
        """Schedule an asynchronous domain-agent request."""

        if request.reply_mode is not DomainReplyMode.ASYNC:
            raise ValueError("dispatch_async requires reply_mode=async")
        agent = self.require(request.agent_name)
        if not agent.supports(DomainReplyMode.ASYNC):
            raise ValueError(f"Domain agent {agent.name} does not support async mode")

        job_id = str(uuid.uuid4())[:8]
        job = AsyncDomainJob(job_id=job_id, request_id=request.request_id, agent_name=agent.name)
        self._jobs[job_id] = job
        self._requests[job_id] = request
        self._tasks[job_id] = asyncio.create_task(self._run_async_job(job_id, agent, request))
        return job

    def get_job(self, job_id: str) -> AsyncDomainJob | None:
        """Return async job state if present."""

        return self._jobs.get(job_id)

    def list_jobs(self, status: AsyncJobStatus | None = None) -> list[AsyncDomainJob]:
        """Return observed async jobs, optionally filtered by lifecycle state."""

        jobs = list(self._jobs.values())
        if status is not None:
            jobs = [job for job in jobs if job.status is status]
        return sorted(jobs, key=lambda job: job.created_at)

    def consume_finished_jobs(self) -> list[AsyncDomainJob]:
        """Drain terminal async jobs for downstream notification or inspection."""

        finished: list[AsyncDomainJob] = []
        while self._finished_job_ids:
            job_id = self._finished_job_ids.popleft()
            job = self._jobs.get(job_id)
            if job is not None:
                finished.append(job)
        return finished


    def request_for_job(self, job_id: str) -> DomainAgentRequest | None:
        """Return the original async request for a job if present."""

        return self._requests.get(job_id)

    async def wait_for_job(self, job_id: str) -> AsyncDomainJob:
        """Wait for an async job to finish and return its state."""

        task = self._tasks.get(job_id)
        if task is None:
            job = self.get_job(job_id)
            if job is None:
                raise KeyError(f"Unknown async domain job: {job_id}")
            return job
        await asyncio.shield(task)
        return self._jobs[job_id]

    async def _run_async_job(
        self,
        job_id: str,
        agent: BaseDomainAgent,
        request: DomainAgentRequest,
    ) -> None:
        job = self._jobs[job_id]
        job.status = AsyncJobStatus.RUNNING
        job.updated_at = datetime.now()

        try:
            result = await agent.handle_async(request)
            if result.status is DomainRunStatus.ACCEPTED:
                result.status = DomainRunStatus.OK
            job.result = result
            job.status = AsyncJobStatus.COMPLETED
            job.error = result.error
        except Exception as exc:
            job.status = AsyncJobStatus.FAILED
            job.error = str(exc)
            job.result = DomainAgentResult(
                request_id=request.request_id,
                agent_name=agent.name,
                status=DomainRunStatus.ERROR,
                error=str(exc),
            )
        finally:
            timestamp = datetime.now()
            job.updated_at = timestamp
            job.completed_at = timestamp
            self._finished_job_ids.append(job_id)
            self._tasks.pop(job_id, None)
