"""Teaching-specific ContextBuilder used to hijack Teacher Core prompt assembly."""

from __future__ import annotations

from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.teaching.prompting import render_prompt_component


class TeachingContextBuilder(ContextBuilder):
    """Build a teaching-only system prompt while keeping the original function signature."""

    ALLOWED_COMPONENTS = {
        "teacher_identity",
        "selected_skills",
        "teaching_contract",
        "event_type_reference",
        "slot_reference",
        "json_examples",
        "invalid_patterns",
        "repair_rules",
    }
    DEFAULT_COMPONENTS = [
        "teacher_identity",
        "selected_skills",
        "teaching_contract",
    ]

    def __init__(self, workspace: Path, *, teacher_core_prompt_components: list[str] | None = None):
        super().__init__(workspace)
        self.teacher_core_prompt_components = list(
            teacher_core_prompt_components or self.DEFAULT_COMPONENTS
        )
        unknown = [
            component
            for component in self.teacher_core_prompt_components
            if component not in self.ALLOWED_COMPONENTS
        ]
        if unknown:
            raise ValueError(
                "Unknown Teacher Core prompt components: " + ", ".join(sorted(unknown))
            )

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the Teacher Core system prompt with the same signature as ContextBuilder."""

        parts: list[str] = []
        for component in self.teacher_core_prompt_components:
            section = self._render_component(component, skill_names)
            if section:
                parts.append(section)
        return "\n\n---\n\n".join(parts)

    def _render_component(self, component: str, skill_names: list[str] | None) -> str:
        """Render one configured Teacher Core prompt component."""

        if component == "selected_skills":
            return self.build_selected_skills_section(skill_names)
        return render_prompt_component(component)
