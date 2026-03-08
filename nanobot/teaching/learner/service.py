"""Placeholder learner-state service used by the first teaching-runtime slice."""

from __future__ import annotations

from nanobot.session.manager import Session
from nanobot.teaching.learner.models import LearnerSnapshot, RecentSignal
from nanobot.teaching.protocol import (
    MountRequest,
    MountResult,
    MountStatus,
    TeachingEnvelope,
    TeachingSlotKey,
)


class TeachingLearnerService:
    """Resolve state.* slots with deterministic placeholder payloads."""

    def load_slot(
        self,
        request: MountRequest,
        *,
        envelope: TeachingEnvelope,
        session: Session,
    ) -> MountResult:
        """Load a single learner-state slot requested by Teacher Core."""

        if request.slot_key is TeachingSlotKey.STATE_LEARNER_SNAPSHOT:
            snapshot = LearnerSnapshot(
                focus_area=envelope.learning_mode or "general-study",
                confidence="unknown",
                fatigue_level="unknown",
                source="placeholder",
            )
            return MountResult(
                slot_key=request.slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=snapshot.model_dump(),
                summary="Loaded placeholder learner snapshot.",
            )

        if request.slot_key is TeachingSlotKey.STATE_RECENT_SIGNALS:
            last_user_turn = next(
                (msg for msg in reversed(session.messages) if msg.get("role") == "user"),
                None,
            )
            signals = [
                RecentSignal(
                    signal_type="recent_turns",
                    value=str(sum(1 for msg in session.messages if msg.get("role") == "user")),
                    source="placeholder",
                ),
                RecentSignal(
                    signal_type="last_user_excerpt",
                    value=(str(last_user_turn.get("content"))[:40] if last_user_turn else "none"),
                    source="placeholder",
                ),
            ]
            return MountResult(
                slot_key=request.slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=[signal.model_dump() for signal in signals],
                summary="Loaded placeholder recent learner signals.",
            )

        return MountResult(
            slot_key=request.slot_key,
            detail_level=request.detail_level,
            params=request.params,
            status=MountStatus.REJECTED,
            summary="The requested state slot is not supported by the placeholder service.",
            missing_reason="Unsupported state slot.",
        )
