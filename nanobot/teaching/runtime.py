"""Assembly helpers for the first teaching-runtime slice."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.providers.base import LLMProvider
from nanobot.teaching.context import TeachingContextBuilder
from nanobot.teaching.f1 import TeachingF1Orchestrator
from nanobot.teaching.observation.logger import TeachingTraceLogger
from nanobot.teaching.teacher_core import TeacherCoreClient


def create_teaching_orchestrator(
    provider: LLMProvider,
    workspace: Path,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None = None,
    max_mount_rounds: int = 2,
    teacher_core_prompt_components: list[str] | None = None,
) -> TeachingF1Orchestrator:
    """Build the teaching-first orchestrator with placeholder downstream services."""

    context_builder = ContextBuilder(workspace)
    teacher_context_builder = TeachingContextBuilder(
        workspace,
        teacher_core_prompt_components=teacher_core_prompt_components,
    )
    teacher_core = TeacherCoreClient(
        provider,
        teacher_context_builder,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    trace_logger = TeachingTraceLogger(workspace)
    return TeachingF1Orchestrator(
        teacher_core,
        context_builder,
        trace_logger=trace_logger,
        max_mount_rounds=max_mount_rounds,
    )
