#!/usr/bin/env python3
"""Standalone query tool for teaching runtime trace JSONL files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nanobot.teaching.observation.reader import (
    TEACHER_BRANCH_SCOPE,
    attach_invalid_line_count,
    default_trace_path,
    filter_trace_records,
    format_trace_summary,
    load_trace_records,
    serialize_records,
    tail_trace_records,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the standalone trace-query argument parser."""

    parser = argparse.ArgumentParser(description="Query teaching trace JSONL records.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace directory.")
    parser.add_argument("--trace-file", type=Path, help="Explicit trace file path. Overrides --workspace.")
    parser.add_argument("--last", type=int, help="Show the most recent N valid trace records.")
    parser.add_argument("--trace-id", help="Show the exact trace with this trace_id.")
    parser.add_argument("--failed", action="store_true", help="Show only failed trace records.")
    parser.add_argument(
        "--teacher-branch-only",
        action="store_true",
        help="Show only records with log_scope=teacher-branch.",
    )
    parser.add_argument("--full", action="store_true", help="Expand rounds and teacher messages.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON records.")
    return parser


def resolve_trace_file(workspace: Path, trace_file: Path | None) -> Path:
    """Resolve the trace file path according to the CLI precedence rules."""

    if trace_file is not None:
        return trace_file
    return default_trace_path(workspace)


def main(argv: list[str] | None = None) -> int:
    """Run the trace query tool and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    trace_path = resolve_trace_file(args.workspace, args.trace_file)
    if not trace_path.exists():
        print(f"teaching trace file not found: {trace_path}")
        return 1

    load_result = load_trace_records(trace_path)
    records = filter_trace_records(
        load_result.records,
        trace_id=args.trace_id,
        failed_only=args.failed,
        log_scope=TEACHER_BRANCH_SCOPE if args.teacher_branch_only else None,
    )
    records = tail_trace_records(records, args.last)

    if args.trace_id and not records:
        print(f"trace_id not found: {args.trace_id}")
        return 1

    if not records:
        print("no matching trace records")
        return 0

    annotated = attach_invalid_line_count(records, load_result.invalid_line_count)
    if args.json:
        print(serialize_records(annotated))
        return 0

    print(format_trace_summary(annotated, full=args.full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
