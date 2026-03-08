from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.config.schema import Config
from nanobot.teaching.context import TeachingContextBuilder


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_teaching_context_builder_uses_default_components_and_selected_skills(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    skill_dir = workspace / "skills" / "test-mode"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: test-mode\n"
        "description: Test learning mode.\n"
        "---\n\n"
        "Always answer with a numbered structure.\n",
        encoding="utf-8",
    )

    builder = TeachingContextBuilder(workspace)
    prompt = builder.build_system_prompt(["test-mode"])

    assert "# Teacher Core" in prompt
    assert "# Current Learning Mode" in prompt
    assert "### Skill: test-mode" in prompt
    assert "# Teaching Runtime Contract" in prompt
    assert "# nanobot 🐈" not in prompt
    assert "## Workspace" not in prompt
    assert "## AGENTS.md" not in prompt


def test_teaching_context_builder_respects_component_order_and_removal(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = TeachingContextBuilder(
        workspace,
        teacher_core_prompt_components=["teaching_contract", "teacher_identity"],
    )

    prompt = builder.build_system_prompt(["test-mode"])

    assert prompt.index("# Teaching Runtime Contract") < prompt.index("# Teacher Core")
    assert "# Current Learning Mode" not in prompt


def test_teaching_context_builder_rejects_unknown_components(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)

    with pytest.raises(ValueError) as exc_info:
        TeachingContextBuilder(
            workspace,
            teacher_core_prompt_components=["teacher_identity", "unknown_component"],
        )

    assert "unknown_component" in str(exc_info.value)


def test_teaching_prompt_components_load_from_config() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "teaching": {
                    "teacherCorePromptComponents": [
                        "teacher_identity",
                        "teaching_contract",
                        "repair_rules",
                    ]
                }
            }
        }
    )

    assert config.agents.teaching.teacher_core_prompt_components == [
        "teacher_identity",
        "teaching_contract",
        "repair_rules",
    ]


def test_teaching_prompt_components_default_from_config() -> None:
    config = Config()

    assert config.agents.teaching.teacher_core_prompt_components == [
        "teacher_identity",
        "selected_skills",
        "teaching_contract",
    ]
