"""Placeholder knowledge service used by the first teaching-runtime slice."""

from __future__ import annotations

from nanobot.bus.events import InboundMessage
from nanobot.session.manager import Session
from nanobot.teaching.knowledge.models import (
    KnowledgeCurrentItem,
    KnowledgeExplanation,
    KnowledgeRefContent,
    KnowledgeReference,
    KnowledgeRubric,
)
from nanobot.teaching.protocol import (
    MountRequest,
    MountResult,
    MountStatus,
    TeachingEnvelope,
    TeachingSlotKey,
)


class TeachingKnowledgeService:
    """Resolve knowledge.* slots with stable placeholder payloads."""

    def load_slot(
        self,
        request: MountRequest,
        *,
        envelope: TeachingEnvelope,
        message: InboundMessage,
        session: Session,
    ) -> MountResult:
        """Load a single knowledge slot requested by Teacher Core."""

        slot_key = request.slot_key
        if slot_key is TeachingSlotKey.KNOWLEDGE_CURRENT_ITEM:
            current_item = self._current_item(envelope, message)
            if current_item is None:
                return self._missing(request, "No explicit current item is available for this turn.")
            return MountResult(
                slot_key=slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=current_item.model_dump(),
                summary="Loaded the current teaching object for this turn.",
            )

        if slot_key is TeachingSlotKey.KNOWLEDGE_EXPLANATION:
            current_item = self._current_item(envelope, message)
            if current_item is None:
                return self._missing(request, "An explanation needs a current item before it can be loaded.")
            explanation = KnowledgeExplanation(
                summary=f"Placeholder explanation for {current_item.item_id}.",
                steps=[
                    "Identify the core teaching object.",
                    "Explain the key reasoning or answer path.",
                    "Bridge the explanation back to the learner's question.",
                ],
                source="placeholder",
            )
            return MountResult(
                slot_key=slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=explanation.model_dump(),
                summary="Loaded placeholder explanation content.",
            )

        if slot_key is TeachingSlotKey.KNOWLEDGE_RUBRIC:
            rubric = KnowledgeRubric(
                rubric_type="feedback_framework",
                criteria=[
                    "Clarify the target concept or question first.",
                    "Explain why the conclusion is correct.",
                    "Point out the learner's likely confusion or next step.",
                ],
                notes=["This is placeholder rubric content for the first teaching-runtime slice."],
                source="placeholder",
            )
            return MountResult(
                slot_key=slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=rubric.model_dump(),
                summary="Loaded placeholder rubric content.",
            )

        if slot_key is TeachingSlotKey.KNOWLEDGE_REFS:
            refs = self._refs(envelope, session)
            return MountResult(
                slot_key=slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=[ref.model_dump() for ref in refs],
                summary="Loaded reference index entries for follow-up expansion.",
            )

        if slot_key is TeachingSlotKey.KNOWLEDGE_REF_CONTENT:
            ref_id = str(request.params.get("ref_id") or "").strip()
            if not ref_id:
                return self._missing(request, "knowledge.ref_content requires params.ref_id.")
            content = KnowledgeRefContent(
                ref_id=ref_id,
                content=f"Expanded placeholder content for {ref_id}.",
                source="placeholder",
                metadata={"detail_level": request.detail_level.value},
            )
            return MountResult(
                slot_key=slot_key,
                detail_level=request.detail_level,
                params=request.params,
                status=MountStatus.LOADED,
                payload=content.model_dump(),
                summary=f"Expanded knowledge reference {ref_id}.",
            )

        return self._rejected(request, "The requested knowledge slot is not supported by the placeholder service.")

    def _current_item(
        self,
        envelope: TeachingEnvelope,
        message: InboundMessage,
    ) -> KnowledgeCurrentItem | None:
        answer_item_id = str(envelope.answer_payload.get("item_id") or "").strip() if envelope.answer_payload else None
        item_id = envelope.explicit_item_id or answer_item_id
        if not item_id:
            teaching_meta = message.metadata.get("teaching") if isinstance(message.metadata, dict) else {}
            if isinstance(teaching_meta, dict):
                item_id = str(teaching_meta.get("current_item_id") or "").strip() or None
        if not item_id:
            return None

        return KnowledgeCurrentItem(
            item_id=item_id,
            item_type="question",
            title=f"Teaching item {item_id}",
            stem=f"Placeholder stem for item {item_id}.",
            options=["Option A", "Option B", "Option C", "Option D"],
            answer="Option B",
            tags=["placeholder", envelope.event_type.value],
            source="placeholder",
        )

    @staticmethod
    def _refs(
        envelope: TeachingEnvelope,
        session: Session,
    ) -> list[KnowledgeReference]:
        base_title = envelope.explicit_item_id or envelope.raw_message[:24] or "current-turn"
        history_count = sum(1 for turn in session.messages if turn.get("role") == "user")
        return [
            KnowledgeReference(
                ref_id=f"ref:{base_title}:overview",
                ref_type="reference_note",
                title=f"{base_title} overview",
                summary="Short reference summary for the current teaching context.",
                source="placeholder",
                relevance=1.0,
            ),
            KnowledgeReference(
                ref_id=f"ref:{base_title}:history:{history_count}",
                ref_type="history_note",
                title="Recent history cue",
                summary="Reference tied to the learner's recent session trajectory.",
                source="placeholder",
                relevance=0.6,
            ),
        ]

    @staticmethod
    def _missing(request: MountRequest, reason: str) -> MountResult:
        return MountResult(
            slot_key=request.slot_key,
            detail_level=request.detail_level,
            params=request.params,
            status=MountStatus.MISSING,
            summary=reason,
            missing_reason=reason,
        )

    @staticmethod
    def _rejected(request: MountRequest, reason: str) -> MountResult:
        return MountResult(
            slot_key=request.slot_key,
            detail_level=request.detail_level,
            params=request.params,
            status=MountStatus.REJECTED,
            summary=reason,
            missing_reason=reason,
        )
