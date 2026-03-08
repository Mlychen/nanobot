"""Knowledge domain agent backed by LightRAG."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.agent.domain.base import BaseDomainAgent
from nanobot.agent.domain.types import DomainAgentRequest, DomainAgentResult, DomainRunStatus
from nanobot.agent.tools.lightrag import LightRAGIngestTool, LightRAGQueryTool
from nanobot.config.schema import LightRAGConfig


class KnowledgeAgent(BaseDomainAgent):
    """Domain agent for knowledge ingestion and retrieval."""

    name = "knowledge"
    allowed_tools = ("lightrag_query", "lightrag_ingest")

    def __init__(self, workspace: Path, config: LightRAGConfig, *, restrict_to_workspace: bool = False):
        allowed_dir = workspace if restrict_to_workspace else None
        self.query_tool = LightRAGQueryTool(config)
        self.ingest_tool = LightRAGIngestTool(config, workspace=workspace, allowed_dir=allowed_dir)

    async def handle_sync(self, request: DomainAgentRequest) -> DomainAgentResult:
        constraints = request.constraints or {}
        result_text = await self.query_tool.execute(
            query=str(constraints.get("query") or request.goal),
            mode=constraints.get("mode"),
            top_k=constraints.get("top_k"),
            only_need_context=constraints.get("only_need_context"),
            conversation_history=constraints.get("conversation_history"),
        )
        payload = _safe_json_loads(result_text)
        if "error" in payload:
            return DomainAgentResult(
                request_id=request.request_id,
                agent_name=self.name,
                status=DomainRunStatus.ERROR,
                summary=payload["error"],
                artifacts={"result": payload},
                error=payload["error"],
            )

        reply = payload.get("response") or json.dumps(payload, ensure_ascii=False)
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.OK,
            summary=f"Knowledge query completed in mode {payload.get('mode', 'unknown')}",
            artifacts={"result": payload},
            suggested_user_reply=reply,
        )

    async def handle_async(self, request: DomainAgentRequest) -> DomainAgentResult:
        constraints = request.constraints or {}
        artifacts = request.artifacts or {}
        result_text = await self.ingest_tool.execute(
            text=artifacts.get("text") or constraints.get("text"),
            file_path=artifacts.get("file_path") or constraints.get("file_path"),
            file_paths=artifacts.get("file_paths") or constraints.get("file_paths"),
            source_label=artifacts.get("source_label") or constraints.get("source_label"),
        )
        payload = _safe_json_loads(result_text)
        if "error" in payload:
            return DomainAgentResult(
                request_id=request.request_id,
                agent_name=self.name,
                status=DomainRunStatus.ERROR,
                summary=payload["error"],
                artifacts={"result": payload},
                error=payload["error"],
            )

        track_id = payload.get("track_id")
        target = payload.get("target", "documents")
        message = f"Knowledge ingest accepted for {target}."
        if track_id:
            message += f" Track ID: {track_id}"

        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.ACCEPTED,
            summary=message,
            artifacts={"result": payload},
            suggested_user_reply=message,
        )

    async def handle_event(self, request: DomainAgentRequest) -> DomainAgentResult:
        return DomainAgentResult(
            request_id=request.request_id,
            agent_name=self.name,
            status=DomainRunStatus.SKIPPED,
            summary="Knowledge agent does not handle event triggers yet.",
        )


def _safe_json_loads(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"response": value}
    return parsed if isinstance(parsed, dict) else {"response": value}


def create_knowledge_agent(
    workspace: Path,
    config: LightRAGConfig,
    *,
    restrict_to_workspace: bool = False,
) -> KnowledgeAgent:
    """Factory entrypoint used by runtime assembly."""

    return KnowledgeAgent(
        workspace,
        config,
        restrict_to_workspace=restrict_to_workspace,
    )
