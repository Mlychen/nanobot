"""Learning mode registry and session-scoped command handling."""

from __future__ import annotations

from dataclasses import dataclass

from nanobot.session.manager import Session

LEARNING_MODE_METADATA_KEY = "learning_mode"


@dataclass(frozen=True)
class LearningModeSpec:
    """Static definition for a supported learning mode."""

    name: str
    display_name: str
    enter_commands: tuple[str, ...]
    skill_names: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class ActiveLearningMode:
    """Normalized learning-mode state restored from session metadata."""

    name: str
    display_name: str
    skill_names: tuple[str, ...]


@dataclass(frozen=True)
class ModeCommandResult:
    """Result of handling a learning-mode command."""

    response: str
    state_changed: bool = False


SHENLUN_MODE = LearningModeSpec(
    name="shenlun-mode",
    display_name="申论模式",
    enter_commands=("/shenlun",),
    skill_names=("shenlun-mode",),
    summary="用于提纲生成、提纲批改和正式表达纠偏。",
)

XINGCE_DRILL_MODE = LearningModeSpec(
    name="xingce-drill",
    display_name="行测训练模式",
    enter_commands=("/xingce",),
    skill_names=("xingce-drill",),
    summary="用于快节奏题目拆解、选项判断和错因复盘。",
)


class LearningModeManager:
    """Manage learning-mode definitions and session-scoped state."""

    def __init__(self, specs: tuple[LearningModeSpec, ...] | None = None):
        self._specs = specs or (SHENLUN_MODE, XINGCE_DRILL_MODE)
        self._specs_by_name = {spec.name: spec for spec in self._specs}
        self._command_map = {
            command: spec
            for spec in self._specs
            for command in spec.enter_commands
        }

    def handle_command(self, session: Session, content: str) -> ModeCommandResult | None:
        """Handle a learning-mode command, if present."""

        command = self._normalize_command(content)
        if not command:
            return None

        if command in self._command_map:
            spec = self._command_map[command]
            self.activate_mode(session, spec)
            return ModeCommandResult(
                response=(
                    f"Entered {spec.display_name} (`{spec.name}`). "
                    "Use `/mode status` to check the current mode or `/mode exit` to return to normal mode."
                ),
                state_changed=True,
            )

        if command == "/mode status":
            return ModeCommandResult(response=self._format_status(self.get_active_mode(session)))

        if command == "/mode exit":
            active = self.clear_mode(session)
            if active is None:
                return ModeCommandResult(response="Current learning mode: normal mode. Nothing to exit.")
            return ModeCommandResult(
                response=f"Exited {active.display_name}. You're back in normal mode.",
                state_changed=True,
            )

        return None

    def get_active_mode(self, session: Session) -> ActiveLearningMode | None:
        """Return the active learning mode for a session, if any."""

        raw = session.metadata.get(LEARNING_MODE_METADATA_KEY)
        if not isinstance(raw, dict):
            return None

        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return None

        if spec := self._specs_by_name.get(name):
            return ActiveLearningMode(
                name=spec.name,
                display_name=spec.display_name,
                skill_names=spec.skill_names,
            )

        display_name = raw.get("display_name")
        skill_names = raw.get("skill_names")
        if not isinstance(display_name, str) or not display_name:
            return None
        if not isinstance(skill_names, list) or not all(isinstance(item, str) and item for item in skill_names):
            return None

        return ActiveLearningMode(
            name=name,
            display_name=display_name,
            skill_names=tuple(skill_names),
        )

    def activate_mode(self, session: Session, spec: LearningModeSpec) -> None:
        """Persist the given learning mode into session metadata."""

        session.metadata[LEARNING_MODE_METADATA_KEY] = {
            "name": spec.name,
            "display_name": spec.display_name,
            "skill_names": list(spec.skill_names),
        }

    def clear_mode(self, session: Session) -> ActiveLearningMode | None:
        """Remove the active learning mode from session metadata."""

        active = self.get_active_mode(session)
        session.metadata.pop(LEARNING_MODE_METADATA_KEY, None)
        return active

    @staticmethod
    def _normalize_command(content: str) -> str:
        return " ".join(content.strip().lower().split())

    @staticmethod
    def _format_status(active: ActiveLearningMode | None) -> str:
        if active is None:
            return "Current learning mode: normal mode."
        return f"Current learning mode: {active.display_name} (`{active.name}`)."
