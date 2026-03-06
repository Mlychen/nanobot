from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.modes import LearningModeManager
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


def test_learning_mode_manager_enters_and_overwrites_modes() -> None:
    manager = LearningModeManager()
    session = Session(key="cli:direct")

    shenlun = manager.handle_command(session, "/shenlun")
    assert shenlun is not None
    assert shenlun.state_changed is True
    assert session.metadata["learning_mode"]["name"] == "shenlun-mode"
    assert session.metadata["learning_mode"]["skill_names"] == ["shenlun-mode"]

    xingce = manager.handle_command(session, "/xingce")
    assert xingce is not None
    assert xingce.state_changed is True
    assert session.metadata["learning_mode"]["name"] == "xingce-drill"
    assert session.metadata["learning_mode"]["skill_names"] == ["xingce-drill"]


def test_learning_mode_manager_reports_status_and_exit() -> None:
    manager = LearningModeManager()
    session = Session(key="cli:direct")

    status = manager.handle_command(session, "/mode status")
    assert status is not None
    assert status.response == "Current learning mode: normal mode."

    no_exit = manager.handle_command(session, "/mode exit")
    assert no_exit is not None
    assert no_exit.response == "Current learning mode: normal mode. Nothing to exit."

    manager.handle_command(session, "/shenlun")
    active = manager.handle_command(session, "/mode status")
    assert active is not None
    assert active.response == "Current learning mode: 申论模式 (`shenlun-mode`)."

    exited = manager.handle_command(session, "/mode exit")
    assert exited is not None
    assert exited.state_changed is True
    assert session.metadata == {}


@pytest.mark.asyncio
async def test_learning_mode_skill_injection_switch_and_exit(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        return LLMResponse(content="ok", tool_calls=[])

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    enter = await loop.process_direct("/shenlun", session_key="cli:test")
    assert "Entered 申论模式" in enter

    status = await loop.process_direct("/mode status", session_key="cli:test")
    assert status == "Current learning mode: 申论模式 (`shenlun-mode`)."

    await loop.process_direct("帮我列一个提纲", session_key="cli:test")
    shenlun_prompt = captured_messages[-1][0]["content"]
    assert "# Current Learning Mode" in shenlun_prompt
    assert "### Skill: shenlun-mode" in shenlun_prompt
    assert "### Skill: xingce-drill" not in shenlun_prompt

    switch = await loop.process_direct("/xingce", session_key="cli:test")
    assert "Entered 行测训练模式" in switch

    await loop.process_direct("这道题怎么拆", session_key="cli:test")
    xingce_prompt = captured_messages[-1][0]["content"]
    assert "### Skill: xingce-drill" in xingce_prompt
    assert "### Skill: shenlun-mode" not in xingce_prompt

    exit_response = await loop.process_direct("/mode exit", session_key="cli:test")
    assert exit_response == "Exited 行测训练模式. You're back in normal mode."

    await loop.process_direct("普通问答", session_key="cli:test")
    normal_prompt = captured_messages[-1][0]["content"]
    assert "# Current Learning Mode" not in normal_prompt
    assert "### Skill: shenlun-mode" not in normal_prompt
    assert "### Skill: xingce-drill" not in normal_prompt


@pytest.mark.asyncio
async def test_new_clears_learning_mode_before_next_turn(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        return LLMResponse(content="ok", tool_calls=[])

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    await loop.process_direct("/shenlun", session_key="cli:reset")
    reset = await loop.process_direct("/new", session_key="cli:reset")
    assert reset == "New session started."

    await loop.process_direct("普通问答", session_key="cli:reset")
    prompt = captured_messages[-1][0]["content"]
    assert "# Current Learning Mode" not in prompt
    assert "### Skill: shenlun-mode" not in prompt


@pytest.mark.asyncio
async def test_help_lists_learning_mode_commands(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)

    help_text = await loop.process_direct("/help")

    assert "/shenlun — Enter Shenlun mode" in help_text
    assert "/xingce — Enter Xingce drill mode" in help_text
    assert "/mode status — Show the current learning mode" in help_text
    assert "/mode exit — Return to normal mode" in help_text


@pytest.mark.asyncio
async def test_plain_messages_do_not_include_learning_mode_skills_by_default(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    captured_messages: list[list[dict]] = []

    async def capture_chat(messages, **kwargs):
        captured_messages.append(messages)
        return LLMResponse(content="ok", tool_calls=[])

    loop.provider.chat = AsyncMock(side_effect=capture_chat)

    await loop.process_direct("hello", session_key="cli:plain")
    prompt = captured_messages[-1][0]["content"]

    assert "# Current Learning Mode" not in prompt
    assert "### Skill: shenlun-mode" not in prompt
    assert "### Skill: xingce-drill" not in prompt
