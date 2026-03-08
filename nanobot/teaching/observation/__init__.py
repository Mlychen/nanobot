"""Observation helpers for the teaching runtime."""

from nanobot.teaching.observation.logger import TeachingTraceLogger
from nanobot.teaching.observation.reader import (
    TRACE_RELATIVE_PATH,
    TraceLoadResult,
    attach_invalid_line_count,
    default_trace_path,
    filter_trace_records,
    format_trace_record,
    format_trace_summary,
    load_trace_records,
    serialize_records,
    tail_trace_records,
)

__all__ = [
    "TRACE_RELATIVE_PATH",
    "TeachingTraceLogger",
    "TraceLoadResult",
    "attach_invalid_line_count",
    "default_trace_path",
    "filter_trace_records",
    "format_trace_record",
    "format_trace_summary",
    "load_trace_records",
    "serialize_records",
    "tail_trace_records",
]
