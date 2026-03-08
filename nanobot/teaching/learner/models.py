"""Structured placeholder models for learner-state slots."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LearnerSnapshot(BaseModel):
    """Compact learner-state projection exposed to Teacher Core."""

    focus_area: str = Field(description="Current focus area inferred from the recent session.")
    confidence: str = Field(description="Coarse confidence label for the current learning trajectory.")
    fatigue_level: str = Field(description="Coarse fatigue label used for teaching style adjustments.")
    source: str = Field(description="Source label describing how this snapshot was produced.")


class RecentSignal(BaseModel):
    """Short recent signal entry exposed via state.recent_signals."""

    signal_type: str = Field(description="Signal category such as fatigue, confidence, or pacing.")
    value: str = Field(description="Human-readable signal value.")
    source: str = Field(description="Source label describing how this signal was derived.")
