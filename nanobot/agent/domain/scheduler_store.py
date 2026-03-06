"""Workspace-local persistence for scheduler agent state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir


class SchedulerStateStore:
    """Persist per-person scheduler state in a dedicated workspace file."""

    _DEFAULT_STATE: dict[str, Any] = {
        "current_plan": None,
        "pending_reminders": [],
        "review_nodes": [],
        "last_recovery_protocol": None,
        "last_generated_at": None,
    }

    def __init__(self, workspace: Path):
        self.state_dir = ensure_dir(Path(workspace) / "domain_agents" / "scheduler")
        self.path = self.state_dir / "state.json"

    def load(self) -> dict[str, Any]:
        """Load raw scheduler data, falling back to an empty store."""

        if not self.path.exists():
            return {"version": 1, "people": {}}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load scheduler state {}: {}", self.path, exc)
            return {"version": 1, "people": {}}

        people = data.get("people")
        normalized_people: dict[str, Any] = {}
        if isinstance(people, dict):
            for key, value in people.items():
                if not key or not isinstance(value, dict):
                    continue
                normalized_people[str(key)] = self._normalize_state(value)

        return {
            "version": int(data.get("version", 1)),
            "people": normalized_people,
        }

    def save(self, data: dict[str, Any]) -> None:
        """Persist the full scheduler state payload."""

        people = data.get("people")
        normalized_people: dict[str, Any] = {}
        if isinstance(people, dict):
            for key, value in people.items():
                if not key or not isinstance(value, dict):
                    continue
                normalized_people[str(key)] = self._normalize_state(value)

        payload = {
            "version": int(data.get("version", 1)),
            "people": normalized_people,
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_person_state(self, context_key: str) -> dict[str, Any]:
        """Load scheduler state for a single person-scoped context."""

        people = self.load()["people"]
        state = people.get(context_key)
        if not isinstance(state, dict):
            return self._copy_default_state()
        return self._normalize_state(state)

    def save_person_state(self, context_key: str, state: dict[str, Any]) -> None:
        """Persist scheduler state for a single person-scoped context."""

        data = self.load()
        people = data.setdefault("people", {})
        if not isinstance(people, dict):
            people = {}
            data["people"] = people
        people[context_key] = self._normalize_state(state)
        self.save(data)

    @classmethod
    def _copy_default_state(cls) -> dict[str, Any]:
        return {
            "current_plan": None,
            "pending_reminders": [],
            "review_nodes": [],
            "last_recovery_protocol": None,
            "last_generated_at": None,
        }

    @classmethod
    def _normalize_state(cls, state: dict[str, Any]) -> dict[str, Any]:
        normalized = cls._copy_default_state()
        current_plan = state.get("current_plan")
        if isinstance(current_plan, dict):
            normalized["current_plan"] = dict(current_plan)

        for key in ("pending_reminders", "review_nodes"):
            items = state.get(key)
            if isinstance(items, list):
                normalized[key] = [dict(item) for item in items if isinstance(item, dict)]

        recovery = state.get("last_recovery_protocol")
        if isinstance(recovery, dict):
            normalized["last_recovery_protocol"] = dict(recovery)

        generated_at = state.get("last_generated_at")
        if generated_at is not None:
            normalized["last_generated_at"] = str(generated_at)

        return normalized
