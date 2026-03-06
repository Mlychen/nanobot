"""Scheduler domain agent for study plans and reminders."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.scheduler_store import SchedulerStateStore
from nanobot.agent.domain.types import DomainAgentRequest, DomainAgentResult, DomainRunStatus


class SchedulerAgent(BaseDomainAgent):
    """Deterministic scheduler agent for the learning-assistant MVP."""

    name = "scheduler"

    def __init__(self, workspace: Path):
        self.store = SchedulerStateStore(workspace)

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        now = self._constraint_now(request.constraints)
        plan_date = self._constraint_plan_date(request.constraints, now)
        time_blocks = self._normalize_time_blocks(request.constraints.get("time_blocks"), plan_date)
        review_due_at = self._constraint_review_due_at(request.constraints, now, time_blocks)
        fatigue_level = self._normalize_fatigue_level(request.constraints.get("fatigue_level"))
        recovery_protocol = self._build_recovery_protocol(fatigue_level, now)
        context_key = self.context_key(request)

        plan = {
            "goal": request.goal.strip() or "完成今日学习计划",
            "plan_date": plan_date.isoformat(),
            "items": [self._plan_item_from_block(index, block) for index, block in enumerate(time_blocks, start=1)],
            "created_at": now.isoformat(),
        }
        state = self.store.load_person_state(context_key)
        state["current_plan"] = plan
        state["pending_reminders"] = [
            self._reminder_from_block(index, block, now)
            for index, block in enumerate(time_blocks, start=1)
        ]
        state["review_nodes"] = [self._review_node(review_due_at, now)]
        state["last_recovery_protocol"] = recovery_protocol
        state["last_generated_at"] = now.isoformat()
        self.store.save_person_state(context_key, state)

        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"Generated study plan for {plan_date.isoformat()}",
            artifacts={
                "context_key": context_key,
                "plan_date": plan_date.isoformat(),
                "reminder_count": len(state["pending_reminders"]),
            },
            memory_updates={
                "current_plan": plan,
                "last_recovery_protocol": recovery_protocol,
            },
            suggested_user_reply=self._render_plan_reply(plan, recovery_protocol),
        )

    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        now = self._constraint_now(request.constraints)
        fatigue_level = self._normalize_fatigue_level(request.constraints.get("fatigue_level"))
        recovery_protocol = self._build_recovery_protocol(fatigue_level, now)
        reminder_text = request.goal.strip() or "按当前计划开始学习。"

        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"Scheduler reminder: {reminder_text}",
            artifacts={"context_key": self.context_key(request), "reminder_type": "manual"},
            notify_intent=True,
            suggested_user_reply=self._render_manual_reminder(reminder_text, recovery_protocol),
        )

    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        now = self._constraint_now(request.constraints)
        fatigue_level = self._normalize_fatigue_level(request.constraints.get("fatigue_level"))
        context_key = self.context_key(request)
        state = self.store.load_person_state(context_key)

        due_reminders = self._collect_due_items(state.get("pending_reminders"), now)
        due_reviews = self._collect_due_items(state.get("review_nodes"), now)
        if not due_reminders and not due_reviews:
            return DomainAgentResult(
                request_id=request.request_id,
                agent_name=self.name,
                status=DomainRunStatus.SKIPPED,
                summary="",
                artifacts={"context_key": context_key, "due_items": 0},
            )

        overdue_count = sum(1 for item in [*due_reminders, *due_reviews] if self._is_overdue(item, now))
        recovery_protocol = self._build_recovery_protocol(fatigue_level, now, overdue_count=overdue_count)
        for item in [*due_reminders, *due_reviews]:
            item["sent_at"] = now.isoformat()

        if recovery_protocol is not None:
            state["last_recovery_protocol"] = recovery_protocol
        self.store.save_person_state(context_key, state)

        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"Delivered {len(due_reminders) + len(due_reviews)} scheduler reminders.",
            artifacts={
                "context_key": context_key,
                "due_reminders": len(due_reminders),
                "due_reviews": len(due_reviews),
            },
            suggested_user_reply=self._render_due_reply(due_reminders, due_reviews, recovery_protocol),
        )

    @staticmethod
    def _constraint_now(constraints: dict[str, Any]) -> datetime:
        value = constraints.get("now") if isinstance(constraints, dict) else None
        parsed = SchedulerAgent._parse_datetime(value)
        return parsed or datetime.now()

    @staticmethod
    def _constraint_plan_date(constraints: dict[str, Any], now: datetime) -> date:
        if not isinstance(constraints, dict):
            return now.date()
        value = constraints.get("plan_date")
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
        return now.date()

    def _constraint_review_due_at(
        self,
        constraints: dict[str, Any],
        now: datetime,
        time_blocks: list[dict[str, Any]],
    ) -> datetime:
        value = constraints.get("review_due_at") if isinstance(constraints, dict) else None
        parsed = self._parse_datetime(value, default_date=now.date())
        if parsed is not None:
            return parsed
        if time_blocks:
            last_end = self._parse_datetime(time_blocks[-1].get("end_at"))
            if last_end is not None:
                return last_end + timedelta(minutes=30)
        return now + timedelta(hours=3)

    def _normalize_time_blocks(self, raw: Any, plan_date: date) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            return self._default_time_blocks(plan_date)

        blocks: list[dict[str, Any]] = []
        for index, item in enumerate(raw, start=1):
            normalized = self._normalize_time_block(index, item, plan_date)
            if normalized is not None:
                blocks.append(normalized)
        return blocks or self._default_time_blocks(plan_date)

    def _normalize_time_block(self, index: int, item: Any, plan_date: date) -> dict[str, Any] | None:
        if isinstance(item, str):
            label = item.strip()
            if not label:
                return None
            start_at = self._combine_date_and_time(plan_date, time(hour=8 + ((index - 1) * 2)))
            end_at = start_at + timedelta(minutes=50)
            return {
                "id": f"plan-{index}",
                "label": label,
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
            }

        if not isinstance(item, dict):
            return None

        label = str(item.get("label") or item.get("task") or f"学习块 {index}").strip()
        start_at = self._parse_datetime(item.get("start_at"), default_date=plan_date)
        if start_at is None:
            start_at = self._combine_date_and_time(plan_date, time(hour=8 + ((index - 1) * 2)))
        end_at = self._parse_datetime(item.get("end_at"), default_date=plan_date)
        if end_at is None or end_at <= start_at:
            end_at = start_at + timedelta(minutes=50)

        return {
            "id": str(item.get("id") or f"plan-{index}"),
            "label": label,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        }

    @staticmethod
    def _default_time_blocks(plan_date: date) -> list[dict[str, Any]]:
        presets = [
            ("专注学习", time(hour=9, minute=0)),
            ("巩固练习", time(hour=14, minute=0)),
            ("复盘整理", time(hour=19, minute=30)),
        ]
        blocks: list[dict[str, Any]] = []
        for index, (label, start_clock) in enumerate(presets, start=1):
            start_at = SchedulerAgent._combine_date_and_time(plan_date, start_clock)
            end_at = start_at + timedelta(minutes=60)
            blocks.append(
                {
                    "id": f"plan-{index}",
                    "label": label,
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                }
            )
        return blocks

    @staticmethod
    def _combine_date_and_time(target_date: date, value: time) -> datetime:
        return datetime.combine(target_date, value)

    @staticmethod
    def _parse_datetime(value: Any, default_date: date | None = None) -> datetime | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None

        if "T" in text:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None

        try:
            parsed_time = time.fromisoformat(text)
        except ValueError:
            return None
        if default_date is None:
            return None
        return datetime.combine(default_date, parsed_time)

    @staticmethod
    def _normalize_fatigue_level(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        level = value.strip().lower()
        if level in {"low", "medium", "high"}:
            return level
        return None

    @staticmethod
    def _plan_item_from_block(index: int, block: dict[str, Any]) -> dict[str, Any]:
        return {
            "index": index,
            "label": block["label"],
            "start_at": block["start_at"],
            "end_at": block["end_at"],
        }

    @staticmethod
    def _reminder_from_block(index: int, block: dict[str, Any], now: datetime) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4())[:8],
            "kind": "study_reminder",
            "label": block["label"],
            "due_at": block["start_at"],
            "source_plan_item": index,
            "created_at": now.isoformat(),
            "sent_at": None,
        }

    @staticmethod
    def _review_node(review_due_at: datetime, now: datetime) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4())[:8],
            "kind": "review_reminder",
            "label": "完成一次简短复盘",
            "due_at": review_due_at.isoformat(),
            "created_at": now.isoformat(),
            "sent_at": None,
        }

    def _collect_due_items(self, items: Any, now: datetime) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []

        due: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or item.get("sent_at"):
                continue
            due_at = self._parse_datetime(item.get("due_at"))
            if due_at is None or due_at > now:
                continue
            due.append(item)
        return due

    def _build_recovery_protocol(
        self,
        fatigue_level: str | None,
        now: datetime,
        *,
        overdue_count: int = 0,
    ) -> dict[str, Any] | None:
        level = fatigue_level
        if level is None and overdue_count >= 2:
            level = "medium"
        if level is None:
            return None

        template = {
            "low": "继续当前节奏，先做 2 分钟准备动作再进入学习。",
            "medium": "先休息 10 分钟，补水并收拢任务列表，再继续最重要的一项。",
            "high": "暂停当前任务 20 分钟，离开屏幕、补水、走动，恢复后只做一项最低阻力任务。",
        }[level]
        return {
            "level": level,
            "message": template,
            "generated_at": now.isoformat(),
        }

    @staticmethod
    def _format_dt(value: str) -> str:
        parsed = SchedulerAgent._parse_datetime(value)
        if parsed is None:
            return value
        return parsed.strftime("%H:%M")

    def _render_plan_reply(self, plan: dict[str, Any], recovery_protocol: dict[str, Any] | None) -> str:
        lines = [f"今日学习计划（{plan['plan_date']}）"]
        for item in plan.get("items", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                f"{item.get('index', '-')}. {self._format_dt(str(item.get('start_at', '')))}-"
                f"{self._format_dt(str(item.get('end_at', '')))} {item.get('label', '学习任务')}"
            )
        if recovery_protocol is not None:
            lines.append("")
            lines.append(f"恢复建议：{recovery_protocol['message']}")
        return "\n".join(lines)

    def _render_manual_reminder(
        self,
        reminder_text: str,
        recovery_protocol: dict[str, Any] | None,
    ) -> str:
        lines = [f"学习提醒：{reminder_text}"]
        if recovery_protocol is not None:
            lines.append(f"恢复建议：{recovery_protocol['message']}")
        return "\n".join(lines)

    def _render_due_reply(
        self,
        due_reminders: list[dict[str, Any]],
        due_reviews: list[dict[str, Any]],
        recovery_protocol: dict[str, Any] | None,
    ) -> str:
        lines: list[str] = []
        if due_reminders:
            lines.append("学习提醒：")
            for item in due_reminders:
                lines.append(
                    f"- {self._format_dt(str(item.get('due_at', '')))} 开始 {item.get('label', '学习任务')}"
                )
        if due_reviews:
            if lines:
                lines.append("")
            lines.append("复盘提醒：")
            for item in due_reviews:
                lines.append(
                    f"- {self._format_dt(str(item.get('due_at', '')))} {item.get('label', '完成复盘')}"
                )
        if recovery_protocol is not None:
            if lines:
                lines.append("")
            lines.append(f"恢复建议：{recovery_protocol['message']}")
        return "\n".join(lines)

    def _is_overdue(self, item: dict[str, Any], now: datetime) -> bool:
        due_at = self._parse_datetime(item.get("due_at"))
        if due_at is None:
            return False
        return due_at < now



def create_scheduler_agent(workspace: Path) -> SchedulerAgent:
    """Factory entrypoint used by runtime assembly."""

    return SchedulerAgent(workspace)

