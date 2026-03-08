"""Structured protocol models for the teaching-first runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class TeachingEventType(str, Enum):
    """How an inbound turn entered the teaching runtime."""

    CHAT = "chat"  # Default for ordinary natural-language messages.
    ANSWER_SUBMIT = "answer_submit"  # Structured answer-submission payloads.
    REVIEW_REQUEST = "review_request"  # Explicit review entrypoints or review cards.
    PLAN_REQUEST = "plan_request"  # Explicit plan entrypoints or plan cards.
    DAILY_CHECKIN = "daily_checkin"  # Explicit check-in entrypoints or scheduled check-ins.


class MountDetailLevel(str, Enum):
    """Requested payload size for a mounted slot."""

    SUMMARY = "summary"  # Short abstract suitable for quick grounding.
    STANDARD = "standard"  # Normal working context for most teaching turns.
    FULL = "full"  # Richest allowed payload for the requested slot.


class TeachingSlotKey(str, Enum):
    """Whitelist of context slots the Teacher Core may request."""

    KNOWLEDGE_CURRENT_ITEM = "knowledge.current_item"  # Current teaching object, usually the active item/question.
    KNOWLEDGE_EXPLANATION = "knowledge.explanation"  # Explanation or reference analysis for the current object.
    KNOWLEDGE_RUBRIC = "knowledge.rubric"  # Evaluation rubric, scoring criteria, or feedback framework.
    KNOWLEDGE_REFS = "knowledge.refs"  # Reference index; points to evidence but does not inline all source text.
    KNOWLEDGE_REF_CONTENT = "knowledge.ref_content"  # Expanded content for a specific reference chosen from refs.
    STATE_LEARNER_SNAPSHOT = "state.learner_snapshot"  # Stable learner-state snapshot for this person/session.
    STATE_RECENT_SIGNALS = "state.recent_signals"  # Recent fatigue, motivation, or performance signals.
    PLAN_ACTIVE_PLAN = "plan.active_plan"  # The currently active plan being executed now.
    PLAN_PLAN_SUMMARY = "plan.plan_summary"  # High-level summary of plan state and progress.
    POLICY_CONSTRAINTS = "policy.constraints"  # Teaching-policy and response-boundary constraints.


class MountStatus(str, Enum):
    """Outcome of a slot load attempted by F1."""

    LOADED = "loaded"  # F1 successfully resolved the requested slot payload.
    MISSING = "missing"  # The slot is valid, but the needed data is unavailable.
    REJECTED = "rejected"  # F1 refused the request due to whitelist or validation rules.


class LearningResponseType(str, Enum):
    """What kind of user-facing reply F1 is returning."""

    ANSWER = "answer"  # Normal teaching answer or explanation.
    CLARIFY = "clarify"  # The runtime needs the learner to clarify missing context.
    ERROR = "error"  # Internal protocol or runtime failure.


class ConversationTurn(BaseModel):
    """Compact turn history entry included in the teaching envelope."""

    role: str = Field(description="Conversation role, typically user or assistant.")
    content: str = Field(description="Plain-text content preserved for teaching continuity.")


class TeachingEnvelope(BaseModel):
    """Minimal turn input assembled before any context slots are loaded."""

    trace_id: str = Field(description="Stable trace identifier for all calls in the current turn.")
    request_id: str = Field(description="Request identifier for the inbound turn.")
    event_type: TeachingEventType = Field(
        description="Coarse inbound trigger type. This is set by F1, not by Teacher Core."
    )
    raw_message: str = Field(description="Original user message text for this turn.")
    person_id: str | None = Field(default=None, description="Stable person identity if available.")
    surface_id: str = Field(description="Surface identifier for the current channel/chat target.")
    session_key: str = Field(description="Conversation session key used by the runtime.")
    learning_mode: str | None = Field(
        default=None,
        description="Active learning mode name, if a mode-specific skill is currently enabled.",
    )
    command_name: str | None = Field(
        default=None,
        description="Explicit formatted command name if the turn entered through a structured command.",
    )
    explicit_item_id: str | None = Field(
        default=None,
        description="Current item identifier provided by metadata or structured payload.",
    )
    answer_payload: dict[str, Any] | None = Field(
        default=None,
        description="Structured answer payload when event_type is answer_submit.",
    )
    surface_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe runtime metadata that F1 is willing to expose to Teacher Core.",
    )
    recent_history: list[ConversationTurn] = Field(
        default_factory=list,
        description="Short recent transcript excerpt for continuity across turns.",
    )


class MountRequest(BaseModel):
    """One slot request emitted by Teacher Core during a non-final round."""

    slot_key: TeachingSlotKey = Field(description="Whitelist slot name that F1 may resolve.")
    detail_level: MountDetailLevel = Field(
        default=MountDetailLevel.STANDARD,
        description="Requested payload granularity. Higher detail is larger, not more trustworthy.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional slot parameters such as ref_id for knowledge.ref_content.",
    )
    reason: str = Field(
        description="Short rationale explaining why this slot is needed for the next teaching step."
    )


class MountResult(BaseModel):
    """Resolved slot payload (or failure) returned by F1 to Teacher Core."""

    slot_key: TeachingSlotKey = Field(description="Whitelist slot name that was resolved.")
    detail_level: MountDetailLevel = Field(description="Actual detail level used when producing the payload.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters used for this slot load, retained for deterministic replay.",
    )
    status: MountStatus = Field(description="Resolution status for the requested slot.")
    payload: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None,
        description="Loaded structured payload. Missing or rejected slots omit the payload.",
    )
    summary: str | None = Field(
        default=None,
        description="Short summary of what was loaded or why the slot could not be loaded.",
    )
    missing_reason: str | None = Field(
        default=None,
        description="Human-readable explanation when status is missing or rejected.",
    )


class TurnDiagnosis(BaseModel):
    """Teacher Core's interpretation of the current turn after context is sufficient."""

    detected_user_intent: str | None = Field(
        default=None,
        description="Teacher Core's interpretation of what the learner is actually asking for.",
    )
    pedagogical_intent: str | None = Field(
        default=None,
        description="Teaching stance chosen by Teacher Core, such as explain, probe, or encourage.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Short diagnostic notes that F1 or observability may record.",
    )


class TeachingTask(BaseModel):
    """Full task packet assembled after one or more slot loads."""

    envelope: TeachingEnvelope = Field(description="Original minimal turn envelope.")
    mounts: list[MountResult] = Field(
        default_factory=list,
        description="All slot results currently mounted for this turn.",
    )
    knowledge_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Grouped knowledge payloads derived from mounted knowledge.* slots.",
    )
    learner_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Grouped learner-state payloads derived from mounted state.* slots.",
    )
    plan_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Grouped plan payloads derived from mounted plan.* slots.",
    )
    policy_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Grouped policy payloads derived from mounted policy.* slots.",
    )


class TeacherTurnControl(BaseModel):
    """Structured control output returned by Teacher Core for a single call."""

    done: bool = Field(
        description="Whether Teacher Core is ready to stop requesting mounts and answer the learner now."
    )
    mount_requests: list[MountRequest] = Field(
        default_factory=list,
        description="Additional context slots requested before answering. Must be empty when done is true.",
    )
    final_response: str | None = Field(
        default=None,
        description="User-facing reply text. Required when done is true.",
    )
    diagnosis: TurnDiagnosis | None = Field(
        default=None,
        description="Structured interpretation of the turn. Only meaningful on the final round.",
    )
    proposed_state_updates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Final-round proposals for learner-state changes. F1 must validate before applying.",
    )
    proposed_plan_updates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Final-round proposals for plan changes. F1 must validate before applying.",
    )

    @model_validator(mode="after")
    def _validate_done_semantics(self) -> "TeacherTurnControl":
        if self.done:
            if not self.final_response:
                raise ValueError("final_response is required when done is true")
            if self.mount_requests:
                raise ValueError("mount_requests must be empty when done is true")
        else:
            if not self.mount_requests:
                raise ValueError("mount_requests are required when done is false")
            if self.proposed_state_updates or self.proposed_plan_updates:
                raise ValueError("mutation proposals are only allowed on the final round")
        return self


class LearningResponse(BaseModel):
    """Normalized reply emitted by F1 after the teaching loop settles."""

    text: str = Field(description="User-facing response text emitted on the current turn.")
    response_type: LearningResponseType = Field(
        default=LearningResponseType.ANSWER,
        description="High-level reply type used by F1 and observability.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured metadata about the teaching turn, safe for logging or downstream handling.",
    )
