"""Placeholder planning service used by the first teaching-runtime slice."""

from __future__ import annotations

from nanobot.bus.events import InboundMessage
from nanobot.session.manager import Session
from nanobot.teaching.planning.models import ActivePlan, PlanSummary, PolicyConstraints
from nanobot.teaching.protocol import (
    MountRequest,
    MountResult,
    MountStatus,
    TeachingEnvelope,
    TeachingSlotKey,
)


class TeachingPlanningService:
    """Resolve plan.* and policy.* slots with deterministic placeholder payloads."""

    def load_slot(
        self,
        request: MountRequest,
        *,
        envelope: TeachingEnvelope,
        message: InboundMessage,
        session: Session,
    ) -> MountResult:
        """Load a single planning or policy slot requested by Teacher Core."""

        if request.slot_key is TeachingSlotKey.PLAN_ACTIVE_PLAN:
            plan_id = self._active_plan_id(message)
            if not plan_id:
                return MountResult(
                    slot_key=request.slot_key,
                    detail_level=request.detail_level,
                    params=request.params,
                    status=MountStatus.MISSING,
                    summary="No active plan is attached to this turn.",
                    missing_reason="No active plan id found in safe metadata.",
                )
            active_plan = ActivePlan(
                plan_id=plan_id,
                title=f"Plan {plan_id}",
                status="active",
                source="placeholder",
            )
            return MountResult(
                slot_key=request.slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=active_plan.model_dump(),
                summary="Loaded placeholder active plan.",
            )

        if request.slot_key is TeachingSlotKey.PLAN_PLAN_SUMMARY:
            user_turns = sum(1 for msg in session.messages if msg.get("role") == "user")
            plan_summary = PlanSummary(
                active_count=1 if self._active_plan_id(message) else 0,
                note=f"Placeholder plan summary after {user_turns} recorded user turns.",
                source="placeholder",
            )
            return MountResult(
                slot_key=request.slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=plan_summary.model_dump(),
                summary="Loaded placeholder plan summary.",
            )

        if request.slot_key is TeachingSlotKey.POLICY_CONSTRAINTS:
            allow_direct_answer = envelope.event_type.value != "review_request"
            policy = PolicyConstraints(
                answer_style="concise" if envelope.learning_mode is None else "mode-aware",
                allow_direct_answer=allow_direct_answer,
                note="Placeholder policy constraints for the teaching-first runtime.",
                source="placeholder",
            )
            return MountResult(
                slot_key=request.slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=policy.model_dump(),
                summary="Loaded placeholder policy constraints.",
            )

        return MountResult(
            slot_key=request.slot_key,
            detail_level=request.detail_level,
            params=request.params,
            status=MountStatus.REJECTED,
            summary="The requested plan/policy slot is not supported by the placeholder service.",
            missing_reason="Unsupported plan/policy slot.",
        )

    @staticmethod
    def _active_plan_id(message: InboundMessage) -> str | None:
        if not isinstance(message.metadata, dict):
            return None
        teaching_meta = message.metadata.get("teaching")
        if isinstance(teaching_meta, dict):
            value = str(teaching_meta.get("active_plan_id") or "").strip()
            if value:
                return value
        return None
