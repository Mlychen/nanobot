"""Teacher Core client for the first teaching-runtime slice."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from json_repair import repair_json
from loguru import logger
from pydantic import ValidationError

from nanobot.agent.context import ContextBuilder
from nanobot.providers.base import LLMProvider
from nanobot.teaching.prompting import render_teacher_core_repair_prompt
from nanobot.teaching.protocol import TeacherTurnControl, TeachingTask


@dataclass(frozen=True)
class TeacherCoreAttempt:
    """One Teacher Core output attempt, including repair retries."""

    repair_attempt: bool
    request_messages: list[dict[str, Any]]
    raw_content: str
    repaired_content: str
    validation_error: str | None = None

    def to_trace_dict(self) -> dict[str, Any]:
        """Convert the attempt into a JSON-safe trace payload."""

        return {
            "repair_attempt": self.repair_attempt,
            "request_messages": self.request_messages,
            "raw_content": self.raw_content,
            "repaired_content": self.repaired_content,
            "validation_error": self.validation_error,
        }


class TeacherCoreParseError(Exception):
    """Raised when Teacher Core fails strict JSON validation after retry."""

    def __init__(self, attempts: list[TeacherCoreAttempt]) -> None:
        self.attempts = attempts
        self.last_validation_error = next(
            (attempt.validation_error for attempt in reversed(attempts) if attempt.validation_error),
            "Teacher Core JSON validation failed.",
        )
        self.teacher_messages = attempts[-1].request_messages if attempts else []
        self.attempt_count = len(attempts)
        super().__init__(
            f"Teacher Core JSON validation failed after {self.attempt_count} attempts: "
            f"{self.last_validation_error}"
        )


class TeacherCoreClient:
    """Call the LLM with the teaching protocol and parse structured control output."""

    def __init__(
        self,
        provider: LLMProvider,
        context_builder: ContextBuilder,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str | None = None,
        max_repair_attempts: int = 1,
    ) -> None:
        self.provider = provider
        self.context_builder = context_builder
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.max_repair_attempts = max_repair_attempts

    async def run_turn(
        self,
        task: TeachingTask,
        *,
        mount_round_index: int,
        max_mount_rounds: int,
        skill_names: list[str] | None = None,
    ) -> tuple[TeacherTurnControl, list[dict[str, Any]], list[dict[str, Any]]]:
        """Execute one Teacher Core call and return parsed control output."""

        system_prompt = self.context_builder.build_system_prompt(skill_names)
        user_payload = {
            "mount_round_index": mount_round_index,
            "max_mount_rounds": max_mount_rounds,
            "teaching_task": task.model_dump(mode="json"),
        }
        base_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
        ]

        attempts: list[TeacherCoreAttempt] = []
        raw_content, repaired_content, validation_error = await self._request_and_validate(
            base_messages,
            attempts,
            repair_attempt=False,
        )
        if validation_error is None:
            parsed = TeacherTurnControl.model_validate_json(repaired_content)
            return parsed, base_messages, [attempt.to_trace_dict() for attempt in attempts]

        logger.warning("[teacher-branch] Teacher Core initial parse failed, requesting repair")
        repair_messages = [
            *base_messages,
            {"role": "assistant", "content": raw_content},
            {
                "role": "user",
                "content": render_teacher_core_repair_prompt(
                    raw_content=raw_content,
                    repaired_content=repaired_content,
                    validation_error=validation_error,
                ),
            },
        ]

        for repair_index in range(self.max_repair_attempts):
            _, repaired_output, repair_error = await self._request_and_validate(
                repair_messages,
                attempts,
                repair_attempt=True,
            )
            if repair_error is None:
                logger.info("[teacher-branch] Teacher Core repair succeeded on retry {}", repair_index + 1)
                parsed = TeacherTurnControl.model_validate_json(repaired_output)
                return parsed, repair_messages, [attempt.to_trace_dict() for attempt in attempts]

        logger.error("[teacher-branch] Teacher Core repair failed after retry limit")
        raise TeacherCoreParseError(attempts)

    async def _request_and_validate(
        self,
        messages: list[dict[str, Any]],
        attempts: list[TeacherCoreAttempt],
        *,
        repair_attempt: bool,
    ) -> tuple[str, str, str | None]:
        """Call the provider once and validate the returned strict JSON content."""

        response = await self.provider.chat(
            messages=messages,
            tools=None,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
        )
        raw_content = response.content or ""
        repaired_content = repair_json(raw_content, ensure_ascii=False)
        validation_error: str | None = None
        try:
            TeacherTurnControl.model_validate_json(repaired_content)
        except ValidationError as exc:
            validation_error = str(exc)

        attempts.append(
            TeacherCoreAttempt(
                repair_attempt=repair_attempt,
                request_messages=[dict(message) for message in messages],
                raw_content=raw_content,
                repaired_content=repaired_content,
                validation_error=validation_error,
            )
        )
        return raw_content, repaired_content, validation_error


