from pathlib import Path

import pytest

from nanobot.agent.domain.scheduler_agent import SchedulerAgent
from nanobot.agent.domain.scheduler_store import SchedulerStateStore
from nanobot.agent.domain.types import (
    DomainAgentRequest,
    DomainReplyMode,
    DomainRunStatus,
    DomainTrigger,
)

BASE_CONSTRAINTS = {
    "plan_date": "2026-03-06",
    "time_blocks": [
        {"label": "刷题训练", "start_at": "09:00", "end_at": "10:00"},
        {"label": "错题复盘", "start_at": "10:30", "end_at": "11:15"},
    ],
    "review_due_at": "11:45",
}


def _request(
    *,
    reply_mode: DomainReplyMode,
    trigger: DomainTrigger,
    constraints: dict | None = None,
    goal: str = "制定今天的学习计划",
    person_id: str = "owner",
) -> DomainAgentRequest:
    return DomainAgentRequest(
        request_id="req-1",
        agent_name="scheduler",
        person_id=person_id,
        surface_id="feishu:ou_123",
        session_key="person:owner:direct",
        goal=goal,
        constraints=constraints or {},
        reply_mode=reply_mode,
        trigger=trigger,
    )


def test_scheduler_store_returns_defaults_when_missing(tmp_path: Path) -> None:
    store = SchedulerStateStore(tmp_path)

    state = store.load_person_state("scheduler:person:owner")

    assert state["current_plan"] is None
    assert state["pending_reminders"] == []
    assert state["review_nodes"] == []


def test_scheduler_store_recovers_from_invalid_json(tmp_path: Path) -> None:
    store = SchedulerStateStore(tmp_path)
    store.path.write_text("{invalid", encoding="utf-8")

    data = store.load()

    assert data == {"version": 1, "people": {}}


@pytest.mark.asyncio
async def test_scheduler_sync_generates_plan_and_persists_state(tmp_path: Path) -> None:
    agent = SchedulerAgent(tmp_path)

    result = await agent.handle_sync(
        _request(
            reply_mode=DomainReplyMode.SYNC,
            trigger=DomainTrigger.USER,
            constraints={**BASE_CONSTRAINTS, "now": "2026-03-06T08:00:00", "fatigue_level": "high"},
        )
    )

    assert result.status is DomainRunStatus.OK
    assert result.suggested_user_reply is not None
    assert "今日学习计划（2026-03-06）" in result.suggested_user_reply
    assert "恢复建议" in result.suggested_user_reply

    state = agent.store.load_person_state("scheduler:person:owner")
    assert state["current_plan"]["goal"] == "制定今天的学习计划"
    assert len(state["pending_reminders"]) == 2
    assert len(state["review_nodes"]) == 1
    assert state["last_recovery_protocol"]["level"] == "high"


@pytest.mark.asyncio
async def test_scheduler_async_returns_notify_intent(tmp_path: Path) -> None:
    agent = SchedulerAgent(tmp_path)

    result = await agent.handle_async(
        _request(
            reply_mode=DomainReplyMode.ASYNC,
            trigger=DomainTrigger.USER,
            goal="开始第一块刷题训练",
            constraints={"now": "2026-03-06T08:30:00", "fatigue_level": "low"},
        )
    )

    assert result.status is DomainRunStatus.OK
    assert result.notify_intent is True
    assert result.suggested_user_reply == "学习提醒：开始第一块刷题训练\n恢复建议：继续当前节奏，先做 2 分钟准备动作再进入学习。"


@pytest.mark.asyncio
async def test_scheduler_event_marks_due_items_only_once(tmp_path: Path) -> None:
    agent = SchedulerAgent(tmp_path)
    await agent.handle_sync(
        _request(
            reply_mode=DomainReplyMode.SYNC,
            trigger=DomainTrigger.USER,
            constraints={**BASE_CONSTRAINTS, "now": "2026-03-06T08:00:00"},
        )
    )

    first = await agent.handle_event(
        _request(
            reply_mode=DomainReplyMode.EVENT,
            trigger=DomainTrigger.HEARTBEAT,
            constraints={"now": "2026-03-06T12:00:00"},
            goal="heartbeat check",
        )
    )

    assert first.status is DomainRunStatus.OK
    assert first.suggested_user_reply is not None
    assert "学习提醒：" in first.suggested_user_reply
    assert "复盘提醒：" in first.suggested_user_reply

    state = agent.store.load_person_state("scheduler:person:owner")
    assert all(item["sent_at"] for item in state["pending_reminders"])
    assert all(item["sent_at"] for item in state["review_nodes"])

    second = await agent.handle_event(
        _request(
            reply_mode=DomainReplyMode.EVENT,
            trigger=DomainTrigger.HEARTBEAT,
            constraints={"now": "2026-03-06T12:05:00"},
            goal="heartbeat check",
        )
    )

    assert second.status is DomainRunStatus.SKIPPED


@pytest.mark.asyncio
async def test_scheduler_event_infers_recovery_when_multiple_items_are_overdue(tmp_path: Path) -> None:
    agent = SchedulerAgent(tmp_path)
    await agent.handle_sync(
        _request(
            reply_mode=DomainReplyMode.SYNC,
            trigger=DomainTrigger.USER,
            constraints={**BASE_CONSTRAINTS, "now": "2026-03-06T08:00:00"},
        )
    )

    result = await agent.handle_event(
        _request(
            reply_mode=DomainReplyMode.EVENT,
            trigger=DomainTrigger.HEARTBEAT,
            constraints={"now": "2026-03-06T12:00:00"},
            goal="heartbeat check",
        )
    )

    assert result.status is DomainRunStatus.OK
    assert result.suggested_user_reply is not None
    assert "恢复建议：先休息 10 分钟" in result.suggested_user_reply

    state = agent.store.load_person_state("scheduler:person:owner")
    assert state["last_recovery_protocol"]["level"] == "medium"
