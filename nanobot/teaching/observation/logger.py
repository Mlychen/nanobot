"""JSONL trace logger for the teaching-first runtime."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir


class TeachingTraceLogger:
    """Persist one structured JSONL trace record for each teaching turn."""

    def __init__(self, workspace: Path, relative_path: str = "logs/teaching_trace.jsonl") -> None:
        self.workspace = workspace
        self.path = workspace / relative_path
        ensure_dir(self.path.parent)

    def log_turn(self, record: dict[str, Any]) -> None:
        """Append one structured trace record to the teaching trace file."""

        payload = {
            "logged_at": datetime.now().isoformat(),
            **record,
        }
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
