"""Teaching-first F1 orchestrator with controlled multi-round slot loading."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.bus.events import InboundMessage
from nanobot.session.manager import Session
from nanobot.teaching.knowledge.service import TeachingKnowledgeService
from nanobot.teaching.learner.service import TeachingLearnerService
from nanobot.teaching.observation.logger import TeachingTraceLogger
from nanobot.teaching.planning.service import TeachingPlanningService
from nanobot.teaching.protocol import (
    ConversationTurn,
    LearningResponse,
    LearningResponseType,
    MountRequest,
    MountResult,
    MountStatus,
    TeacherTurnControl,
    TeachingEnvelope,
    TeachingEventType,
    TeachingSlotKey,
    TeachingTask,
)
from nanobot.teaching.teacher_core import TeacherCoreClient, TeacherCoreParseError


@dataclass
class TeachingRunResult:
    """Final teaching-runtime output returned to AgentLoop."""

    response: LearningResponse
    task: TeachingTask
    diagnosis: dict[str, Any] = field(default_factory=dict)
    proposed_state_updates: list[dict[str, Any]] = field(default_factory=list)
    proposed_plan_updates: list[dict[str, Any]] = field(default_factory=list)
    trace_record: dict[str, Any] = field(default_factory=dict)


class TeachingF1Orchestrator:
    """F1 host controller for the first teaching-runtime slice."""

    def __init__(
        self,
        teacher_core: TeacherCoreClient,
        context_builder: ContextBuilder,
        *,
        knowledge_service: TeachingKnowledgeService | None = None,
        learner_service: TeachingLearnerService | None = None,
        planning_service: TeachingPlanningService | None = None,
        trace_logger: TeachingTraceLogger | None = None,
        max_mount_rounds: int = 2,
    ) -> None:
        # max_mount_rounds counts how many times Teacher Core may ask for more mounts
        # before it must answer or the runtime fails the turn.
        self.teacher_core = teacher_core
        self.context_builder = context_builder
        self.knowledge_service = knowledge_service or TeachingKnowledgeService()
        self.learner_service = learner_service or TeachingLearnerService()
        self.planning_service = planning_service or TeachingPlanningService()
        self.trace_logger = trace_logger
        self.max_mount_rounds = max_mount_rounds

    async def handle_inbound(
        self,
        msg: InboundMessage,
        session: Session,
        *,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        skill_names: list[str] | None = None,
    ) -> TeachingRunResult | None:
        """Handle a normal user turn through the teaching-first runtime."""

        if msg.channel == "system":
            return None

        envelope = self._build_envelope(msg, session)
        task = TeachingTask(envelope=envelope)
        mount_cache: dict[str, MountResult] = {}
        trace_record = self._start_trace_record(envelope)
        logger.debug(
            "[teacher-branch] Teaching trace {} started: event_type={}, session_key={}, learning_mode={}",
            envelope.trace_id,
            envelope.event_type.value,
            envelope.session_key,
            envelope.learning_mode or "none",
        )

        try:
            for mount_round_index in range(self.max_mount_rounds + 1):
                try:
                    control, teacher_messages, llm_attempts = await self.teacher_core.run_turn(
                        task,
                        mount_round_index=mount_round_index,
                        max_mount_rounds=self.max_mount_rounds,
                        skill_names=skill_names,
                    )
                except TeacherCoreParseError as exc:
                    trace_record["rounds"].append(
                        self._failed_round_trace(
                            mount_round_index,
                            exc.teacher_messages,
                            [attempt.to_trace_dict() for attempt in exc.attempts],
                        )
                    )
                    trace_record["failure"] = {
                        "kind": "teacher_core_parse_error",
                        "message": str(exc),
                        "attempt_count": exc.attempt_count,
                        "validation_error": exc.last_validation_error,
                    }
                    logger.error(
                        "[teacher-branch] Teaching trace {} repair failed after retry limit",
                        envelope.trace_id,
                    )
                    raise
                round_trace = self._round_trace(control, mount_round_index, teacher_messages, llm_attempts)
                trace_record["rounds"].append(round_trace)
                logger.debug(
                    "[teacher-branch] Teaching trace {} round {}: done={}, mount_requests={}",
                    envelope.trace_id,
                    mount_round_index,
                    control.done,
                    [request.slot_key.value for request in control.mount_requests],
                )
                if control.done:
                    result = self._finalize_result(control, task, mount_round_index, trace_record)
                    logger.info(
                        "[teacher-branch] Teaching trace {} finalized: response_type={}, mount_rounds_used={}",
                        envelope.trace_id,
                        result.response.response_type.value,
                        mount_round_index,
                    )
                    self._write_trace(result.trace_record)
                    return result

                if mount_round_index >= self.max_mount_rounds:
                    break

                if on_progress:
                    requested = ", ".join(request.slot_key.value for request in control.mount_requests)
                    await on_progress(f"Teaching F1 is mounting: {requested}")

                mount_results = self._resolve_mount_requests(
                    control.mount_requests,
                    envelope=envelope,
                    message=msg,
                    session=session,
                    cache=mount_cache,
                )
                round_trace["mount_results"] = [mount.model_dump(mode="json") for mount in mount_results]
                logger.debug(
                    "[teacher-branch] Teaching trace {} round {} mount results: {}",
                    envelope.trace_id,
                    mount_round_index,
                    [
                        {
                            "slot_key": mount.slot_key.value,
                            "status": mount.status.value,
                            "detail_level": mount.detail_level.value,
                        }
                        for mount in mount_results
                    ],
                )
                task = self._with_mounts(task, mount_results)
        except Exception as exc:
            if "failure" not in trace_record:
                trace_record["failure"] = {
                    "kind": "exception",
                    "message": str(exc),
                }
            logger.exception("[teacher-branch] Teaching trace {} failed with exception", envelope.trace_id)
            self._write_trace(trace_record)
            raise

        result = self._runtime_error(
            task,
            "I ran out of mount rounds before the teaching runtime produced a final answer.",
            trace_record,
        )
        logger.warning(
            "[teacher-branch] Teaching trace {} exhausted mount rounds: max_mount_rounds={}",
            envelope.trace_id,
            self.max_mount_rounds,
        )
        self._write_trace(result.trace_record)
        return result

    def _build_envelope(self, msg: InboundMessage, session: Session) -> TeachingEnvelope:
        safe_metadata = self._safe_surface_metadata(msg.metadata)
        active_mode = session.metadata.get("learning_mode") if isinstance(session.metadata, dict) else {}
        learning_mode = active_mode.get("name") if isinstance(active_mode, dict) else None
        command_name = self._command_name(msg.content)
        return TeachingEnvelope(
            trace_id=uuid.uuid4().hex[:12],
            request_id=uuid.uuid4().hex[:8],
            event_type=self._resolve_event_type(msg, command_name),
            raw_message=msg.content,
            person_id=self._person_id(msg.metadata),
            surface_id=self._surface_id(msg),
            session_key=msg.session_key,
            learning_mode=str(learning_mode) if learning_mode else None,
            command_name=command_name,
            explicit_item_id=self._explicit_item_id(msg.metadata),
            answer_payload=self._answer_payload(msg.metadata),
            surface_metadata=safe_metadata,
            recent_history=self._recent_history(session),
        )

    def _resolve_mount_requests(
        self,
        requests: list[MountRequest],
        *,
        envelope: TeachingEnvelope,
        message: InboundMessage,
        session: Session,
        cache: dict[str, MountResult],
    ) -> list[MountResult]:
        results: list[MountResult] = []
        for request in requests:
            cache_key = self._mount_cache_key(request)
            if cache_key in cache:
                results.append(cache[cache_key])
                continue

            result = self._load_slot(request, envelope=envelope, message=message, session=session)
            cache[cache_key] = result
            results.append(result)
        return results

    def _load_slot(
        self,
        request: MountRequest,
        *,
        envelope: TeachingEnvelope,
        message: InboundMessage,
        session: Session,
    ) -> MountResult:
        if request.slot_key.value.startswith("knowledge."):
            return self.knowledge_service.load_slot(request, envelope=envelope, message=message, session=session)
        if request.slot_key.value.startswith("state."):
            return self.learner_service.load_slot(request, envelope=envelope, session=session)
        if request.slot_key.value.startswith("plan.") or request.slot_key is TeachingSlotKey.POLICY_CONSTRAINTS:
            return self.planning_service.load_slot(request, envelope=envelope, message=message, session=session)
        return MountResult(
            slot_key=request.slot_key,
            detail_level=request.detail_level,
            params=request.params,
            status=MountStatus.REJECTED,
            summary="The requested slot namespace is not supported by F1.",
            missing_reason="Unsupported slot namespace.",
        )

    def _with_mounts(self, task: TeachingTask, new_mounts: list[MountResult]) -> TeachingTask:
        mounts = [*task.mounts, *new_mounts]
        knowledge_context: dict[str, Any] = {}
        learner_snapshot: dict[str, Any] = {}
        plan_context: dict[str, Any] = {}
        policy_constraints: dict[str, Any] = {}

        for mount in mounts:
            grouped_key = mount.slot_key.value.split(".", 1)[1]
            if mount.slot_key.value.startswith("knowledge."):
                self._merge_context_bucket(knowledge_context, grouped_key, mount)
            elif mount.slot_key.value.startswith("state."):
                self._merge_context_bucket(learner_snapshot, grouped_key, mount)
            elif mount.slot_key.value.startswith("plan."):
                self._merge_context_bucket(plan_context, grouped_key, mount)
            elif mount.slot_key is TeachingSlotKey.POLICY_CONSTRAINTS:
                self._merge_context_bucket(policy_constraints, grouped_key, mount)

        return TeachingTask(
            envelope=task.envelope,
            mounts=mounts,
            knowledge_context=knowledge_context,
            learner_snapshot=learner_snapshot,
            plan_context=plan_context,
            policy_constraints=policy_constraints,
        )

    @staticmethod
    def _merge_context_bucket(bucket: dict[str, Any], grouped_key: str, mount: MountResult) -> None:
        entry = {
            "status": mount.status.value,
            "detail_level": mount.detail_level.value,
            "params": mount.params,
            "payload": mount.payload,
            "summary": mount.summary,
            "missing_reason": mount.missing_reason,
        }
        if grouped_key == "ref_content":
            existing = bucket.get(grouped_key)
            if not isinstance(existing, list):
                existing = []
            existing.append(entry)
            bucket[grouped_key] = existing
            return
        bucket[grouped_key] = entry

    def _finalize_result(
        self,
        control: TeacherTurnControl,
        task: TeachingTask,
        mount_round_index: int,
        trace_record: dict[str, Any],
    ) -> TeachingRunResult:
        has_missing_mount = any(mount.status is MountStatus.MISSING for mount in task.mounts)
        pedagogical_intent = control.diagnosis.pedagogical_intent if control.diagnosis else None
        response_type = (
            LearningResponseType.CLARIFY
            if has_missing_mount and pedagogical_intent == "clarify"
            else LearningResponseType.ANSWER
        )
        response = LearningResponse(
            text=control.final_response or "I need a bit more information to continue.",
            response_type=response_type,
            metadata={
                "trace_id": task.envelope.trace_id,
                "event_type": task.envelope.event_type.value,
                "mount_rounds_used": mount_round_index,
            },
        )
        trace_record["final"] = {
            "response": response.model_dump(mode="json"),
            "diagnosis": control.diagnosis.model_dump(mode="json") if control.diagnosis else {},
            "proposed_state_updates": control.proposed_state_updates,
            "proposed_plan_updates": control.proposed_plan_updates,
        }
        return TeachingRunResult(
            response=response,
            task=task,
            diagnosis=control.diagnosis.model_dump(mode="json") if control.diagnosis else {},
            proposed_state_updates=control.proposed_state_updates,
            proposed_plan_updates=control.proposed_plan_updates,
            trace_record=trace_record,
        )

    def _runtime_error(
        self,
        task: TeachingTask,
        message: str,
        trace_record: dict[str, Any],
    ) -> TeachingRunResult:
        response = LearningResponse(
            text=message,
            response_type=LearningResponseType.ERROR,
            metadata={
                "trace_id": task.envelope.trace_id,
                "event_type": task.envelope.event_type.value,
            },
        )
        trace_record["failure"] = {
            "kind": "mount_round_limit",
            "message": message,
            "max_mount_rounds": self.max_mount_rounds,
        }
        trace_record["final"] = {
            "response": response.model_dump(mode="json"),
            "diagnosis": {},
            "proposed_state_updates": [],
            "proposed_plan_updates": [],
        }
        return TeachingRunResult(response=response, task=task, trace_record=trace_record)

    @staticmethod
    def _recent_history(session: Session, limit: int = 6) -> list[ConversationTurn]:
        turns: list[ConversationTurn] = []
        for item in session.get_history(max_messages=limit * 2):
            role = str(item.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if isinstance(content, str):
                turns.append(ConversationTurn(role=role, content=content))
        return turns[-limit:]

    @staticmethod
    def _command_name(content: str) -> str | None:
        text = content.strip()
        if not text.startswith("/"):
            return None
        return text.split(None, 1)[0][1:] or None

    def _resolve_event_type(self, msg: InboundMessage, command_name: str | None) -> TeachingEventType:
        if explicit := self._explicit_event_type(msg.metadata):
            return explicit
        if self._answer_payload(msg.metadata):
            return TeachingEventType.ANSWER_SUBMIT
        if command_name == "review":
            return TeachingEventType.REVIEW_REQUEST
        if command_name == "plan":
            return TeachingEventType.PLAN_REQUEST
        if command_name == "checkin":
            return TeachingEventType.DAILY_CHECKIN
        return TeachingEventType.CHAT

    @staticmethod
    def _explicit_event_type(metadata: dict[str, Any] | None) -> TeachingEventType | None:
        if not isinstance(metadata, dict):
            return None
        teaching_meta = metadata.get("teaching")
        candidates = []
        if isinstance(teaching_meta, dict):
            candidates.append(teaching_meta.get("event_type"))
        candidates.append(metadata.get("event_type"))
        for value in candidates:
            if value is None:
                continue
            try:
                return TeachingEventType(str(value))
            except ValueError:
                continue
        return None

    @staticmethod
    def _answer_payload(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(metadata, dict):
            return None
        teaching_meta = metadata.get("teaching")
        if isinstance(teaching_meta, dict) and isinstance(teaching_meta.get("answer_payload"), dict):
            return dict(teaching_meta["answer_payload"])
        if isinstance(metadata.get("answer_payload"), dict):
            return dict(metadata["answer_payload"])
        return None

    @staticmethod
    def _explicit_item_id(metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        teaching_meta = metadata.get("teaching")
        if isinstance(teaching_meta, dict):
            item_id = str(teaching_meta.get("current_item_id") or "").strip()
            if item_id:
                return item_id
        value = str(metadata.get("current_item_id") or "").strip()
        return value or None

    @staticmethod
    def _person_id(metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("person_id")
        return str(value) if value else None

    @staticmethod
    def _surface_id(msg: InboundMessage) -> str:
        session_meta = (msg.metadata or {}).get("session")
        if isinstance(session_meta, dict):
            surface_id = session_meta.get("surface_id")
            if isinstance(surface_id, str) and surface_id:
                return surface_id
        return f"{msg.channel}:{msg.chat_id}"

    @staticmethod
    def _safe_surface_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return {}
        safe_keys = {"channel", "chat_type", "message_id", "surface_kind"}
        safe: dict[str, Any] = {}
        for key in safe_keys:
            if key in metadata:
                safe[key] = metadata[key]
        teaching_meta = metadata.get("teaching")
        if isinstance(teaching_meta, dict):
            safe["teaching"] = {
                key: value
                for key, value in teaching_meta.items()
                if key in {"event_type", "current_item_id", "active_plan_id"}
            }
        return safe

    @staticmethod
    def _mount_cache_key(request: MountRequest) -> str:
        params_json = json.dumps(request.params, ensure_ascii=False, sort_keys=True)
        return f"{request.slot_key.value}|{request.detail_level.value}|{params_json}"

    @staticmethod
    def _start_trace_record(envelope: TeachingEnvelope) -> dict[str, Any]:
        return {
            "log_scope": "teacher-branch",
            "trace_version": 1,
            "trace_id": envelope.trace_id,
            "request_id": envelope.request_id,
            "event_type": envelope.event_type.value,
            "session_key": envelope.session_key,
            "surface_id": envelope.surface_id,
            "person_id": envelope.person_id,
            "learning_mode": envelope.learning_mode,
            "raw_message": envelope.raw_message,
            "rounds": [],
        }

    @staticmethod
    def _round_trace(
        control: TeacherTurnControl,
        mount_round_index: int,
        teacher_messages: list[dict[str, Any]],
        llm_attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "round_index": mount_round_index,
            "done": control.done,
            # teacher_messages stores the exact system/user payload sent to Teacher Core
            # for this round so the JSONL trace can be replayed or audited later.
            "teacher_messages": teacher_messages,
            # llm_attempts captures the raw and repaired JSON emitted by Teacher Core,
            # including repair retries, so strict-parser failures stay debuggable.
            "llm_attempts": llm_attempts,
            "mount_requests": [request.model_dump(mode="json") for request in control.mount_requests],
            "mount_results": [],
        }

    @staticmethod
    def _failed_round_trace(
        mount_round_index: int,
        teacher_messages: list[dict[str, Any]],
        llm_attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "round_index": mount_round_index,
            "done": False,
            "teacher_messages": teacher_messages,
            "llm_attempts": llm_attempts,
            "mount_requests": [],
            "mount_results": [],
        }

    def _write_trace(self, trace_record: dict[str, Any]) -> None:
        if self.trace_logger is not None:
            self.trace_logger.log_turn(trace_record)


