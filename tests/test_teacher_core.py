from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.providers.base import LLMResponse
from nanobot.teaching.context import TeachingContextBuilder
from nanobot.teaching.prompting import render_teacher_core_prompt
from nanobot.teaching.protocol import TeachingEnvelope, TeachingEventType, TeachingTask
from nanobot.teaching.teacher_core import TeacherCoreClient, TeacherCoreParseError


def _make_task() -> TeachingTask:
    return TeachingTask(
        envelope=TeachingEnvelope(
            trace_id="trace-1",
            request_id="request-1",
            event_type=TeachingEventType.CHAT,
            raw_message="hello teacher",
            person_id="owner",
            surface_id="cli:direct",
            session_key="cli:direct",
            learning_mode=None,
            command_name=None,
            explicit_item_id=None,
            answer_payload=None,
            surface_metadata={},
            recent_history=[],
        )
    )


def test_render_teacher_core_prompt_contains_strict_contract() -> None:
    prompt = render_teacher_core_prompt()

    assert "slot_key" in prompt
    assert "reason" in prompt
    assert "summary" in prompt and "standard" in prompt and "full" in prompt
    assert "Do not use `slot`; always use `slot_key`." in prompt
    assert '"done": false' in prompt.lower()
    assert '"done": true' in prompt.lower()


@pytest.mark.asyncio
async def test_teacher_core_repairs_invalid_json_once(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.chat = AsyncMock(
        side_effect=[
            LLMResponse(
                content=json.dumps(
                    {
                        "done": False,
                        "mount_requests": [
                            {
                                "slot": "knowledge.current_item",
                                "detail_level": "standard",
                                "params": {},
                            }
                        ],
                        "final_response": None,
                        "diagnosis": None,
                        "proposed_state_updates": None,
                        "proposed_plan_updates": None,
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            ),
            LLMResponse(
                content=json.dumps(
                    {
                        "done": False,
                        "mount_requests": [
                            {
                                "slot_key": "knowledge.current_item",
                                "detail_level": "standard",
                                "params": {},
                                "reason": "Need the current teaching object before answering.",
                            }
                        ],
                        "final_response": None,
                        "diagnosis": None,
                        "proposed_state_updates": [],
                        "proposed_plan_updates": [],
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            ),
        ]
    )
    client = TeacherCoreClient(
        provider,
        TeachingContextBuilder(tmp_path),
        model="test-model",
        temperature=0.1,
        max_tokens=256,
    )

    control, teacher_messages, attempts = await client.run_turn(
        _make_task(),
        mount_round_index=0,
        max_mount_rounds=2,
    )

    assert control.mount_requests[0].slot_key.value == "knowledge.current_item"
    assert provider.chat.await_count == 2
    assert len(attempts) == 2
    assert attempts[0]["validation_error"] is not None
    assert attempts[1]["repair_attempt"] is True
    assert attempts[1]["validation_error"] is None
    assert teacher_messages[0]["content"].startswith("# Teacher Core")
    assert "# Teaching Runtime Contract" in teacher_messages[0]["content"]
    assert "# nanobot 🐈" not in teacher_messages[0]["content"]
    assert "## Workspace" not in teacher_messages[0]["content"]
    assert teacher_messages[-1]["role"] == "user"
    assert "Use slot_key, not slot." in teacher_messages[-1]["content"]


@pytest.mark.asyncio
async def test_teacher_core_raises_after_repair_retry_limit(tmp_path: Path) -> None:
    provider = MagicMock()
    invalid_payload = json.dumps(
        {
            "done": False,
            "mount_requests": [
                {
                    "slot": "knowledge.current_item",
                    "detail_level": "standard",
                    "params": {},
                }
            ],
            "final_response": None,
            "diagnosis": None,
            "proposed_state_updates": None,
            "proposed_plan_updates": None,
        },
        ensure_ascii=False,
    )
    provider.chat = AsyncMock(
        side_effect=[
            LLMResponse(content=invalid_payload, tool_calls=[]),
            LLMResponse(content=invalid_payload, tool_calls=[]),
        ]
    )
    client = TeacherCoreClient(
        provider,
        TeachingContextBuilder(tmp_path),
        model="test-model",
        temperature=0.1,
        max_tokens=256,
    )

    with pytest.raises(TeacherCoreParseError) as exc_info:
        await client.run_turn(
            _make_task(),
            mount_round_index=0,
            max_mount_rounds=2,
        )

    assert exc_info.value.attempt_count == 2
    assert "slot_key" in exc_info.value.last_validation_error
