"""Read and format teaching trace JSONL records without mutating runtime state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TRACE_RELATIVE_PATH = Path("logs") / "teaching_trace.jsonl"
TEACHER_BRANCH_SCOPE = "teacher-branch"


@dataclass(frozen=True)
class TraceLoadResult:
    """Parsed trace records plus non-fatal read errors."""

    records: list[dict[str, Any]]
    invalid_line_count: int = 0


def default_trace_path(workspace: Path) -> Path:
    """Resolve the default teaching trace file under a workspace."""

    return workspace / TRACE_RELATIVE_PATH


def load_trace_records(trace_file: Path) -> TraceLoadResult:
    """Load JSONL trace records and skip malformed lines without failing the read."""

    records: list[dict[str, Any]] = []
    invalid_line_count = 0

    with trace_file.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                invalid_line_count += 1
                continue
            if not isinstance(payload, dict):
                invalid_line_count += 1
                continue
            records.append(payload)

    return TraceLoadResult(records=records, invalid_line_count=invalid_line_count)


def filter_trace_records(
    records: list[dict[str, Any]],
    *,
    trace_id: str | None = None,
    failed_only: bool = False,
    log_scope: str | None = None,
) -> list[dict[str, Any]]:
    """Apply the supported trace filters in a deterministic order."""

    filtered = list(records)
    if trace_id is not None:
        filtered = [record for record in filtered if str(record.get("trace_id") or "") == trace_id]
    if failed_only:
        filtered = [record for record in filtered if isinstance(record.get("failure"), dict)]
    if log_scope is not None:
        filtered = [record for record in filtered if str(record.get("log_scope") or "") == log_scope]
    return filtered


def tail_trace_records(records: list[dict[str, Any]], last: int | None = None) -> list[dict[str, Any]]:
    """Return the most recent N records while preserving original order."""

    if last is None:
        return list(records)
    if last <= 0:
        return []
    return list(records[-last:])


def format_trace_summary(records: list[dict[str, Any]], *, full: bool = False) -> str:
    """Render human-readable summaries for one or more trace records."""

    if not records:
        return "no matching trace records"
    return "\n\n".join(format_trace_record(record, full=full) for record in records)


def format_trace_record(record: dict[str, Any], *, full: bool = False) -> str:
    """Render one trace record as a readable multi-line block."""

    rounds = _as_list(record.get("rounds"))
    final = _as_dict(record.get("final"))
    response = _as_dict(final.get("response"))
    failure = _as_dict(record.get("failure"))
    lines = [
        f"logged_at: {_value(record, 'logged_at')}",
        f"log_scope: {_value(record, 'log_scope', default='unknown')}",
        f"trace_id: {_value(record, 'trace_id')}",
        f"event_type: {_value(record, 'event_type')}",
        f"learning_mode: {_value(record, 'learning_mode', default='none')}",
        f"round_count: {len(rounds)}",
        f"response_type: {_value(response, 'response_type', default='unknown')}",
        f"failed: {'yes' if failure else 'no'}",
    ]

    if failure:
        lines.append(f"failure_kind: {_value(failure, 'kind', default='unknown')}")
        lines.append(f"failure_message: {_preview(_value(failure, 'message', default=''))}")
    else:
        lines.append(f"response_preview: {_preview(_value(response, 'text', default=''))}")

    invalid_line_count = record.get("_invalid_line_count")
    if isinstance(invalid_line_count, int) and invalid_line_count > 0:
        lines.append(f"invalid_line_count: {invalid_line_count}")

    if full:
        lines.extend(_format_full_sections(rounds, final))
    return "\n".join(lines)


def serialize_records(records: list[dict[str, Any]]) -> str:
    """Serialize records for machine-oriented consumption without reshaping fields."""

    return json.dumps(records, ensure_ascii=False, indent=2)


def attach_invalid_line_count(records: list[dict[str, Any]], invalid_line_count: int) -> list[dict[str, Any]]:
    """Annotate displayed records with skipped-line counts for operator awareness."""

    if invalid_line_count <= 0:
        return list(records)
    annotated: list[dict[str, Any]] = []
    for record in records:
        copy = dict(record)
        copy["_invalid_line_count"] = invalid_line_count
        annotated.append(copy)
    return annotated


def _format_full_sections(rounds: list[dict[str, Any]], final: dict[str, Any]) -> list[str]:
    lines = ["rounds:"]
    for round_record in rounds:
        round_index = round_record.get("round_index", "unknown")
        lines.append(f"  - round_index: {round_index}")
        lines.append(f"    done: {round_record.get('done', 'unknown')}")
        lines.append(
            f"    mount_requests: {json.dumps(_as_list(round_record.get('mount_requests')), ensure_ascii=False)}"
        )
        lines.append(
            f"    mount_results: {json.dumps(_as_list(round_record.get('mount_results')), ensure_ascii=False)}"
        )
        lines.append(
            f"    teacher_messages: {json.dumps(_as_list(round_record.get('teacher_messages')), ensure_ascii=False)}"
        )
        lines.append(
            f"    llm_attempts: {json.dumps(_as_list(round_record.get('llm_attempts')), ensure_ascii=False)}"
        )

    lines.append(f"diagnosis: {json.dumps(_as_dict(final.get('diagnosis')), ensure_ascii=False)}")
    lines.append(
        "proposed_state_updates: "
        + json.dumps(_as_list(final.get('proposed_state_updates')), ensure_ascii=False)
    )
    lines.append(
        "proposed_plan_updates: "
        + json.dumps(_as_list(final.get('proposed_plan_updates')), ensure_ascii=False)
    )
    return lines


def _preview(value: str, limit: int = 120) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _value(payload: dict[str, Any], key: str, *, default: str = "unknown") -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if value in (None, ""):
        return default
    return str(value)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
