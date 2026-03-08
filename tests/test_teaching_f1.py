from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.teaching.runtime import create_teaching_orchestrator
from nanobot.teaching.teacher_core import TeacherCoreParseError


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    teaching_orchestrator = create_teaching_orchestrator(
        provider,
        tmp_path,
        model="test-model",
        temperature=0.1,
        max_tokens=1024,
    )
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        teaching_orchestrator=teaching_orchestrator,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


def _read_trace_records(tmp_path: Path) -> list[dict]:
    trace_path = tmp_path / "logs" / "teaching_trace.jsonl"
    assert trace_path.exists()
    return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_plain_messages_route_to_teaching_runtime(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(
                {
                    "done": True,
                    "mount_requests": [],
                    "final_response": "Teaching runtime reply",
                    "diagnosis": {
                        "detected_user_intent": "ask_explanation",
                        "pedagogical_intent": "explain",
                        "notes": ["first-slice test"],
                    },
                    "proposed_state_updates": [],
                    "proposed_plan_updates": [],
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )
    )

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello teacher")
    )

    assert result is not None
    assert result.content == "Teaching runtime reply"
    assert result.metadata["teaching"]["event_type"] == "chat"
    assert loop.provider.chat.await_count == 1

    traces = _read_trace_records(tmp_path)
    assert len(traces) == 1
    assert traces[0]["log_scope"] == "teacher-branch"
    assert traces[0]["trace_version"] == 1
    assert traces[0]["event_type"] == "chat"
    assert traces[0]["final"]["response"]["text"] == "Teaching runtime reply"
    assert traces[0]["rounds"][0]["done"] is True
    assert traces[0]["rounds"][0]["teacher_messages"][0]["role"] == "system"
    assert traces[0]["rounds"][0]["teacher_messages"][1]["role"] == "user"


@pytest.mark.asyncio
async def test_teaching_runtime_supports_multi_round_mounts(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        payloads = [
            {
                "done": False,
                "mount_requests": [
                    {
                        "slot_key": "knowledge.refs",
                        "detail_level": "summary",
                        "params": {},
                        "reason": "Need reference candidates before answering.",
                    }
                ],
                "final_response": None,
                "diagnosis": None,
                "proposed_state_updates": [],
                "proposed_plan_updates": [],
            },
            {
                "done": False,
                "mount_requests": [
                    {
                        "slot_key": "knowledge.ref_content",
                        "detail_level": "standard",
                        "params": {"ref_id": "ref:Explain this concept:overview"},
                        "reason": "Need the selected reference content.",
                    }
                ],
                "final_response": None,
                "diagnosis": None,
                "proposed_state_updates": [],
                "proposed_plan_updates": [],
            },
            {
                "done": True,
                "mount_requests": [],
                "final_response": "Here is the grounded answer.",
                "diagnosis": {
                    "detected_user_intent": "ask_explanation",
                    "pedagogical_intent": "explain",
                    "notes": ["used multi-round mounts"],
                },
                "proposed_state_updates": [],
                "proposed_plan_updates": [],
            },
        ]
        index = len(captured_messages) - 1
        return LLMResponse(content=json.dumps(payloads[index], ensure_ascii=False), tool_calls=[])

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="Explain this concept")
    )

    assert result is not None
    assert result.content == "Here is the grounded answer."
    assert len(captured_messages) == 3
    assert '"knowledge_context"' in captured_messages[1][1]["content"]
    assert '"ref_content"' in captured_messages[2][1]["content"]

    traces = _read_trace_records(tmp_path)
    assert len(traces) == 1
    assert len(traces[0]["rounds"]) == 3
    assert traces[0]["rounds"][0]["mount_requests"][0]["slot_key"] == "knowledge.refs"
    assert traces[0]["rounds"][0]["teacher_messages"][1]["content"].startswith('{')
    assert traces[0]["rounds"][1]["mount_results"][0]["slot_key"] == "knowledge.ref_content"
    assert traces[0]["rounds"][2]["teacher_messages"][1]["content"].startswith('{')


@pytest.mark.asyncio
async def test_teaching_runtime_marks_clarify_when_slot_is_missing(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        payloads = [
            {
                "done": False,
                "mount_requests": [
                    {
                        "slot_key": "plan.active_plan",
                        "detail_level": "standard",
                        "params": {},
                        "reason": "Need the currently active plan.",
                    }
                ],
                "final_response": None,
                "diagnosis": None,
                "proposed_state_updates": [],
                "proposed_plan_updates": [],
            },
            {
                "done": True,
                "mount_requests": [],
                "final_response": "Which study plan do you want me to adjust?",
                "diagnosis": {
                    "detected_user_intent": "ask_plan_adjustment",
                    "pedagogical_intent": "clarify",
                    "notes": ["active plan missing"],
                },
                "proposed_state_updates": [],
                "proposed_plan_updates": [],
            },
        ]
        index = len(captured_messages) - 1
        return LLMResponse(content=json.dumps(payloads[index], ensure_ascii=False), tool_calls=[])

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="Please adjust my plan")
    )

    assert result is not None
    assert result.content == "Which study plan do you want me to adjust?"
    assert result.metadata["teaching"]["response_type"] == "clarify"
    assert '"missing_reason"' in captured_messages[1][1]["content"]

    traces = _read_trace_records(tmp_path)
    assert traces[0]["rounds"][0]["mount_results"][0]["status"] == "missing"
    assert traces[0]["final"]["response"]["response_type"] == "clarify"


@pytest.mark.asyncio
async def test_teaching_runtime_logs_failure_when_mount_rounds_exhausted(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(
                {
                    "done": False,
                    "mount_requests": [
                        {
                            "slot_key": "knowledge.refs",
                            "detail_level": "summary",
                            "params": {},
                            "reason": "Keep asking forever.",
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
        )
    )

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="loop forever")
    )

    assert result is not None
    assert "ran out of mount rounds" in result.content

    traces = _read_trace_records(tmp_path)
    assert traces[0]["failure"]["kind"] == "mount_round_limit"
    assert traces[0]["failure"]["max_mount_rounds"] == 2


@pytest.mark.asyncio
async def test_teaching_runtime_keeps_learning_mode_skill_prompt(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        return LLMResponse(
            content=json.dumps(
                {
                    "done": True,
                    "mount_requests": [],
                    "final_response": "mode aware reply",
                    "diagnosis": {
                        "detected_user_intent": "ask_outline",
                        "pedagogical_intent": "coach",
                        "notes": [],
                    },
                    "proposed_state_updates": [],
                    "proposed_plan_updates": [],
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
        )

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    await loop.process_direct("/shenlun", session_key="cli:test")
    result = await loop.process_direct("帮我列一个提纲", session_key="cli:test")

    assert result == "mode aware reply"
    system_prompt = captured_messages[-1][0]["content"]
    assert "# Current Learning Mode" in system_prompt
    assert "### Skill: shenlun-mode" in system_prompt


@pytest.mark.asyncio
async def test_teaching_runtime_records_repair_attempts_in_trace(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        payloads = [
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
            {
                "done": True,
                "mount_requests": [],
                "final_response": "Repaired teaching runtime reply",
                "diagnosis": {
                    "detected_user_intent": "ask_explanation",
                    "pedagogical_intent": "explain",
                    "notes": ["repair path"],
                },
                "proposed_state_updates": [],
                "proposed_plan_updates": [],
            },
        ]
        return LLMResponse(content=json.dumps(payloads[len(captured_messages) - 1], ensure_ascii=False), tool_calls=[])

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="repair me")
    )

    assert result is not None
    assert result.content == "Repaired teaching runtime reply"
    assert len(captured_messages) == 2
    assert "Use slot_key, not slot." in captured_messages[1][-1]["content"]

    traces = _read_trace_records(tmp_path)
    assert len(traces[0]["rounds"][0]["llm_attempts"]) == 2
    assert traces[0]["rounds"][0]["llm_attempts"][0]["validation_error"] is not None
    assert traces[0]["rounds"][0]["llm_attempts"][1]["repair_attempt"] is True
    assert traces[0]["rounds"][0]["llm_attempts"][1]["validation_error"] is None


@pytest.mark.asyncio
async def test_teaching_runtime_logs_teacher_core_parse_failure(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
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
    loop.provider.chat = AsyncMock(
        side_effect=[
            LLMResponse(content=invalid_payload, tool_calls=[]),
            LLMResponse(content=invalid_payload, tool_calls=[]),
        ]
    )

    with pytest.raises(TeacherCoreParseError):
        await loop._process_message(
            InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="break repair")
        )

    traces = _read_trace_records(tmp_path)
    assert traces[0]["failure"]["kind"] == "teacher_core_parse_error"
    assert traces[0]["failure"]["attempt_count"] == 2
    assert len(traces[0]["rounds"]) == 1
    assert len(traces[0]["rounds"][0]["llm_attempts"]) == 2
    assert traces[0]["rounds"][0]["llm_attempts"][1]["repair_attempt"] is True



