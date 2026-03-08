from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from nanobot.teaching.observation.reader import (
    TEACHER_BRANCH_SCOPE,
    attach_invalid_line_count,
    default_trace_path,
    filter_trace_records,
    format_trace_summary,
    load_trace_records,
    tail_trace_records,
)


def _trace_record(
    trace_id: str,
    *,
    failed: bool = False,
    response_type: str = "answer",
    log_scope: str = TEACHER_BRANCH_SCOPE,
) -> dict:
    record = {
        "logged_at": f"2026-03-08T12:00:0{trace_id[-1]}",
        "log_scope": log_scope,
        "trace_version": 1,
        "trace_id": trace_id,
        "event_type": "chat",
        "learning_mode": "shenlun",
        "rounds": [
            {
                "round_index": 0,
                "done": True,
                "teacher_messages": [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": '{"mount_round_index": 0}'},
                ],
                "mount_requests": [{"slot_key": "knowledge.refs"}],
                "mount_results": [{"slot_key": "knowledge.refs", "status": "loaded"}],
            }
        ],
        "final": {
            "response": {
                "text": f"response for {trace_id}",
                "response_type": response_type,
            },
            "diagnosis": {"pedagogical_intent": "explain"},
            "proposed_state_updates": [],
            "proposed_plan_updates": [],
        },
    }
    if failed:
        record["failure"] = {"kind": "mount_round_limit", "message": "too many rounds"}
    return record


def _write_trace_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(_trace_record("trace-1"), ensure_ascii=False),
        "not-json",
        json.dumps(_trace_record("trace-2", failed=True, response_type="error"), ensure_ascii=False),
        json.dumps(_trace_record("trace-9", log_scope="other-branch"), ensure_ascii=False),
        json.dumps({"trace_id": "trace-3"}, ensure_ascii=False),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_trace_records_skips_invalid_lines(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)

    result = load_trace_records(trace_path)

    assert len(result.records) == 4
    assert result.invalid_line_count == 1


def test_trace_filters_and_tail(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)
    result = load_trace_records(trace_path)

    failed = filter_trace_records(result.records, failed_only=True)
    selected = filter_trace_records(result.records, trace_id="trace-1")
    teacher_branch_only = filter_trace_records(result.records, log_scope=TEACHER_BRANCH_SCOPE)
    tailed = tail_trace_records(result.records, 2)

    assert [record["trace_id"] for record in failed] == ["trace-2"]
    assert [record["trace_id"] for record in selected] == ["trace-1"]
    assert [record["trace_id"] for record in teacher_branch_only] == ["trace-1", "trace-2"]
    assert [record.get("trace_id") for record in tailed] == ["trace-9", "trace-3"]


def test_format_trace_summary_handles_missing_fields(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)
    result = load_trace_records(trace_path)

    summary = format_trace_summary(attach_invalid_line_count(result.records, result.invalid_line_count))
    full_summary = format_trace_summary(result.records, full=True)

    assert "log_scope: teacher-branch" in summary
    assert "trace_id: trace-3" in summary
    assert "response_type: unknown" in summary
    assert "invalid_line_count: 1" in summary
    assert "teacher_messages:" in full_summary
    assert "mount_results:" in full_summary


def test_script_json_mode_outputs_parseable_json(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "teaching_trace.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--workspace", str(tmp_path), "--failed", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert [record["trace_id"] for record in payload] == ["trace-2"]


def test_script_teacher_branch_only_filters_other_scopes(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "teaching_trace.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--workspace", str(tmp_path), "--teacher-branch-only", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert [record["trace_id"] for record in payload] == ["trace-1", "trace-2"]


def test_script_full_mode_prints_detailed_sections(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "teaching_trace.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--workspace", str(tmp_path), "--trace-id", "trace-1", "--full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "teacher_messages:" in result.stdout
    assert "mount_results:" in result.stdout


def test_script_reports_missing_trace_file(tmp_path: Path) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "teaching_trace.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--workspace", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "teaching trace file not found" in result.stdout


def test_script_reports_missing_trace_id(tmp_path: Path) -> None:
    trace_path = default_trace_path(tmp_path)
    _write_trace_file(trace_path)
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "teaching_trace.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--workspace", str(tmp_path), "--trace-id", "missing-trace"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "trace_id not found: missing-trace" in result.stdout
