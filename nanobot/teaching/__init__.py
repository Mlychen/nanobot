"""Teaching-runtime entrypoints and protocol helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.teaching.f1 import TeachingF1Orchestrator, TeachingRunResult

__all__ = [
    "TeachingF1Orchestrator",
    "TeachingRunResult",
    "create_teaching_orchestrator",
]


def __getattr__(name: str) -> Any:
    """Lazy-load runtime symbols so light-weight observation tools avoid heavy deps."""

    if name in {"TeachingF1Orchestrator", "TeachingRunResult"}:
        from nanobot.teaching.f1 import TeachingF1Orchestrator, TeachingRunResult

        exports = {
            "TeachingF1Orchestrator": TeachingF1Orchestrator,
            "TeachingRunResult": TeachingRunResult,
        }
        return exports[name]
    if name == "create_teaching_orchestrator":
        from nanobot.teaching.runtime import create_teaching_orchestrator

        return create_teaching_orchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
