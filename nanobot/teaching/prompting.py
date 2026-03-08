"""Prompt builders for the teaching runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.teaching.protocol import (
    MountDetailLevel,
    MountRequest,
    TeacherTurnControl,
    TeachingEventType,
    TeachingSlotKey,
)

_TEMPLATE_PATH = Path(__file__).with_name("prompts") / "teacher_core.md"


def render_teacher_core_prompt() -> str:
    """Render the full Teacher Core contract prompt from the external template."""

    return render_teaching_contract()


def render_prompt_component(name: str) -> str:
    """Render one named Teacher Core prompt component."""

    renderers = {
        "teacher_identity": render_teacher_identity,
        "teaching_contract": render_teaching_contract,
        "event_type_reference": render_event_type_reference,
        "slot_reference": render_slot_reference,
        "json_examples": render_json_examples,
        "invalid_patterns": render_invalid_patterns,
        "repair_rules": render_repair_rules,
    }
    try:
        return renderers[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown Teacher Core prompt component: {name}") from exc


def render_teacher_identity() -> str:
    """Render the lightweight teaching-only identity block."""

    return (
        "# Teacher Core\n\n"
        "You are the Teacher Core inside a controlled teaching runtime. "
        "You are not the general-purpose nanobot agent.\n\n"
        "Your only job is to request missing teaching context when needed and then return one strict JSON object that follows the teaching runtime contract."
    )


def render_teaching_contract() -> str:
    """Render the complete teaching runtime contract block."""

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{PROTOCOL_REFERENCE}}", _protocol_reference())
        .replace("{{NON_FINAL_EXAMPLE}}", _json_example(_non_final_example()))
        .replace("{{FINAL_EXAMPLE}}", _json_example(_final_example()))
        .replace("{{INVALID_PATTERNS}}", _invalid_patterns())
    )


def render_event_type_reference() -> str:
    """Render the event_type enum reference as a standalone component."""

    return "## Event Type Reference\n\n### Event Type Enum\n\n" + _enum_lines(TeachingEventType)


def render_slot_reference() -> str:
    """Render slot whitelist and request fields as standalone components."""

    sections = [
        "## Slot Reference",
        "### Slot Whitelist",
        _enum_lines(TeachingSlotKey),
        "### Mount Detail Level Enum",
        _enum_lines(MountDetailLevel),
        "### MountRequest Fields",
        _model_field_lines(MountRequest),
        "### TeacherTurnControl Fields",
        _model_field_lines(TeacherTurnControl),
    ]
    return "\n\n".join(sections)


def render_json_examples() -> str:
    """Render the valid JSON examples as a standalone component."""

    return "\n\n".join(
        [
            "## Valid JSON Example: Non-final Round",
            "```json\n" + _json_example(_non_final_example()) + "\n```",
            "## Valid JSON Example: Final Round",
            "```json\n" + _json_example(_final_example()) + "\n```",
        ]
    )


def render_invalid_patterns() -> str:
    """Render the invalid output patterns as a standalone component."""

    return "## Invalid Output Patterns\n\n" + _invalid_patterns()


def render_repair_rules() -> str:
    """Render repair-specific rules for retry scenarios."""

    lines = [
        "## Repair Rules",
        "- If the runtime reports a validation error, return one complete corrected JSON object only.",
        "- Do not explain the error, apologize, or provide analysis outside the JSON object.",
        "- Do not return a patch or partial diff; return the full corrected TeacherTurnControl object.",
        "- Keep field names identical to the contract, especially slot_key and proposed_* arrays.",
    ]
    return "\n".join(lines)


def render_teacher_core_repair_prompt(
    *,
    raw_content: str,
    repaired_content: str,
    validation_error: str,
) -> str:
    """Render the corrective prompt sent after strict schema validation fails."""

    payload = {
        "instruction": (
            "Your previous output failed strict schema validation. "
            "Do not explain or analyze. Return one complete corrected JSON object only."
        ),
        "requirements": [
            "Use the exact field names from the contract.",
            "Use slot_key, not slot.",
            "Include reason in every mount_requests item.",
            "proposed_state_updates and proposed_plan_updates must always be arrays.",
            "Return the full JSON object, not a patch.",
        ],
        "previous_raw_output": raw_content,
        "previous_repaired_output": repaired_content,
        "validation_error": validation_error,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _protocol_reference() -> str:
    sections = [
        "### Event Type Enum",
        _enum_lines(TeachingEventType),
        "### Mount Detail Level Enum",
        _enum_lines(MountDetailLevel),
        "### Slot Whitelist",
        _enum_lines(TeachingSlotKey),
        "### MountRequest Fields",
        _model_field_lines(MountRequest),
        "### TeacherTurnControl Fields",
        _model_field_lines(TeacherTurnControl),
    ]
    return "\n\n".join(sections)


def _enum_lines(enum_cls: type) -> str:
    return "\n".join(f"- `{item.value}`" for item in enum_cls)


def _model_field_lines(model_cls: type) -> str:
    lines: list[str] = []
    for name, field in model_cls.model_fields.items():
        description = field.description or ""
        required = field.is_required()
        suffix = "required" if required else "optional"
        lines.append(f"- `{name}`: {suffix}. {description}".rstrip())
    return "\n".join(lines)


def _json_example(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _non_final_example() -> dict[str, Any]:
    return {
        "done": False,
        "mount_requests": [
            {
                "slot_key": "knowledge.current_item",
                "detail_level": "standard",
                "params": {},
                "reason": "Need the current teaching object before answering.",
            }
        ],
        "final_response": None,
        "diagnosis": None,
        "proposed_state_updates": [],
        "proposed_plan_updates": [],
    }


def _final_example() -> dict[str, Any]:
    return {
        "done": True,
        "mount_requests": [],
        "final_response": "这里是面向用户的回复。",
        "diagnosis": {
            "detected_user_intent": "ask_explanation",
            "pedagogical_intent": "explain",
            "notes": [],
        },
        "proposed_state_updates": [],
        "proposed_plan_updates": [],
    }


def _invalid_patterns() -> str:
    return "\n".join(
        [
            "- Do not use `slot`; always use `slot_key`.",
            "- Do not omit `reason` in any `mount_requests` item.",
            "- Do not return `null` for `proposed_state_updates`; use `[]`.",
            "- Do not return `null` for `proposed_plan_updates`; use `[]`.",
            "- Do not return `mount_requests` when `done` is `true`.",
            "- Do not return anything except a single complete JSON object.",
        ]
    )
