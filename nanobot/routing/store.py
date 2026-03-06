"""Workspace-backed configuration for session routing policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


class SessionPolicyStore:
    """Load session policy settings from the workspace."""

    _DEFAULT_DATA: dict[str, Any] = {
        "version": 1,
        "trusted_direct": {
            "enabled": False,
            "channels": ["feishu", "cli"],
        },
    }

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.path = self.workspace / "routing" / "session_policy.json"

    def load(self) -> dict[str, Any]:
        """Load policy data, falling back to defaults on missing or invalid files."""

        if not self.path.exists():
            return self._copy_defaults()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load session policy store {}: {}", self.path, exc)
            return self._copy_defaults()

        trusted_direct = data.get("trusted_direct", {})
        channels = trusted_direct.get("channels")
        normalized_channels = [
            str(channel)
            for channel in channels
            if isinstance(channels, list) and channel
        ]

        return {
            "version": int(data.get("version", 1)),
            "trusted_direct": {
                "enabled": bool(trusted_direct.get("enabled", False)),
                "channels": normalized_channels or list(self._DEFAULT_DATA["trusted_direct"]["channels"]),
            },
        }

    def trusted_direct_enabled(self) -> bool:
        """Return whether trusted direct sharing is enabled."""

        return bool(self.load()["trusted_direct"]["enabled"])

    def trusted_direct_channels(self) -> list[str]:
        """Return channels eligible for trusted direct session sharing."""

        channels = self.load()["trusted_direct"]["channels"]
        return [str(channel) for channel in channels]

    @classmethod
    def _copy_defaults(cls) -> dict[str, Any]:
        return {
            "version": cls._DEFAULT_DATA["version"],
            "trusted_direct": {
                "enabled": cls._DEFAULT_DATA["trusted_direct"]["enabled"],
                "channels": list(cls._DEFAULT_DATA["trusted_direct"]["channels"]),
            },
        }
