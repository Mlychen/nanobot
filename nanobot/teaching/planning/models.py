"""Structured placeholder models for plan and policy slots."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ActivePlan(BaseModel):
    """Current active plan payload exposed via plan.active_plan."""

    plan_id: str = Field(description="Stable active-plan identifier.")
    title: str = Field(description="Short active-plan title.")
    status: str = Field(description="Plan execution status label.")
    source: str = Field(description="Source label describing the plan origin.")


class PlanSummary(BaseModel):
    """High-level plan summary exposed via plan.plan_summary."""

    active_count: int = Field(description="How many active plans are visible to the current runtime.")
    note: str = Field(description="Short planning summary note.")
    source: str = Field(description="Source label describing how the summary was produced.")


class PolicyConstraints(BaseModel):
    """Teaching-policy constraints exposed via policy.constraints."""

    answer_style: str = Field(description="Preferred answer-style guidance for the current turn.")
    allow_direct_answer: bool = Field(description="Whether direct answers are allowed under current policy.")
    note: str = Field(description="Short explanation of the current policy stance.")
    source: str = Field(description="Source label describing the policy origin.")
