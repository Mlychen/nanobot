"""Structured placeholder models for knowledge slots."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeReference(BaseModel):
    """Indexed evidence reference returned by knowledge.refs."""

    ref_id: str = Field(description="Stable reference identifier used for follow-up ref_content loads.")
    ref_type: str = Field(description="Reference category such as explanation, policy_text, or similar_item.")
    title: str = Field(description="Human-readable title for the reference.")
    summary: str = Field(description="Short index summary; this is not the full source content.")
    source: str = Field(description="Data source label used for traceability.")
    relevance: float = Field(description="Relative relevance score within the returned reference set.")


class KnowledgeCurrentItem(BaseModel):
    """Current teaching object. In the first version this is usually the active question."""

    item_id: str = Field(description="Stable item identifier or placeholder fallback id.")
    item_type: str = Field(description="Teaching-object type such as question or essay_prompt.")
    title: str = Field(description="Short title shown to the teacher core.")
    stem: str = Field(description="The main prompt, stem, or body of the current object.")
    options: list[str] = Field(default_factory=list, description="Optional answer options for multiple-choice items.")
    answer: str | None = Field(default=None, description="Reference answer if known.")
    tags: list[str] = Field(default_factory=list, description="Tags or labels associated with the item.")
    source: str = Field(description="Source label describing where the item came from.")


class KnowledgeExplanation(BaseModel):
    """Explanation payload returned by knowledge.explanation."""

    summary: str = Field(description="Short explanation summary for the current teaching object.")
    steps: list[str] = Field(default_factory=list, description="Optional explanation steps.")
    source: str = Field(description="Source label describing the explanation origin.")


class KnowledgeRubric(BaseModel):
    """Feedback or evaluation rubric returned by knowledge.rubric."""

    rubric_type: str = Field(description="Rubric category such as scoring, feedback, or elimination_rules.")
    criteria: list[str] = Field(default_factory=list, description="Ordered evaluation criteria or feedback dimensions.")
    notes: list[str] = Field(default_factory=list, description="Short rubric notes for teaching use.")
    source: str = Field(description="Source label describing the rubric origin.")


class KnowledgeRefContent(BaseModel):
    """Expanded payload for a specific ref selected from knowledge.refs."""

    ref_id: str = Field(description="Reference identifier originally returned by knowledge.refs.")
    content: str = Field(description="Expanded content for the selected reference.")
    source: str = Field(description="Source label describing the expanded content origin.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional structured fields for the ref content.")
