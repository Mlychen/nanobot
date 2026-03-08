"""LightRAG tools for indexing and retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.filesystem import _resolve_path
from nanobot.config.schema import LightRAGConfig


class LightRAGClient:
    """Thin HTTP client for the LightRAG server API."""

    def __init__(
        self,
        config: LightRAGConfig,
        *,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
    ):
        self._config = config
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/")

    @property
    def timeout(self) -> float:
        return float(max(1, self._config.timeout))

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    async def query(
        self,
        *,
        query: str,
        mode: str,
        top_k: int,
        only_need_context: bool,
        conversation_history: list[dict[str, str]] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "top_k": top_k,
            "only_need_context": only_need_context,
        }
        if conversation_history:
            payload["conversation_history"] = conversation_history

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/query",
                json=payload,
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()

    async def insert_text(self, *, text: str, source_label: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if source_label:
            payload["description"] = source_label

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/documents/text",
                json=payload,
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()

    async def insert_texts(
        self,
        *,
        texts: list[str],
        source_label: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"texts": texts}
        if source_label:
            payload["description"] = source_label

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/documents/texts",
                json=payload,
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()

    async def upload_files(self, file_paths: list[str], *, source_label: str | None = None) -> dict[str, Any]:
        resolved_paths = [self._resolve_file_path(path) for path in file_paths]
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for resolved in resolved_paths:
            files.append(
                (
                    "files",
                    (resolved.name, resolved.read_bytes(), "application/octet-stream"),
                )
            )

        data = {"description": source_label} if source_label else None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/documents/upload",
                files=files,
                data=data,
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()

    def _resolve_file_path(self, path: str) -> Path:
        resolved = _resolve_path(path, self._workspace, self._allowed_dir)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not resolved.is_file():
            raise FileNotFoundError(f"Not a file: {path}")
        return resolved


class LightRAGQueryTool(Tool):
    """Query indexed knowledge from a LightRAG server."""

    def __init__(self, config: LightRAGConfig):
        self._config = config
        self._client = LightRAGClient(config)

    @property
    def name(self) -> str:
        return "lightrag_query"

    @property
    def description(self) -> str:
        return "Query a LightRAG knowledge base and return the response and execution metadata."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The user question to send to LightRAG."},
                "mode": {
                    "type": "string",
                    "description": "Retrieval mode such as naive, local, global, hybrid, or mix.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum retrieval candidates to consider.",
                    "minimum": 1,
                    "maximum": 100,
                },
                "only_need_context": {
                    "type": "boolean",
                    "description": "When true, ask LightRAG to return retrieval context without final answer synthesis.",
                },
                "conversation_history": {
                    "type": "array",
                    "description": "Optional prior turns forwarded to LightRAG.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        mode: str | None = None,
        top_k: int | None = None,
        only_need_context: bool | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        del kwargs
        try:
            payload = await self._client.query(
                query=query,
                mode=mode or self._config.default_query_mode,
                top_k=top_k or self._config.default_top_k,
                only_need_context=(
                    self._config.default_only_need_context
                    if only_need_context is None
                    else only_need_context
                ),
                conversation_history=conversation_history,
            )
            result = {
                "response": payload.get("response", ""),
                "query": payload.get("query", query),
                "mode": payload.get("mode", mode or self._config.default_query_mode),
                "execution_time": payload.get("execution_time"),
                "conversation_history": payload.get("conversation_history", conversation_history or []),
                "raw": payload,
            }
            return json.dumps(result, ensure_ascii=False)
        except httpx.HTTPStatusError as exc:
            return self._error_response(f"LightRAG query failed with HTTP {exc.response.status_code}", exc)
        except httpx.TimeoutException as exc:
            return self._error_response("LightRAG query timed out", exc)
        except Exception as exc:
            return self._error_response("LightRAG query failed", exc)

    @staticmethod
    def _error_response(message: str, exc: Exception) -> str:
        return json.dumps({"error": message, "details": str(exc)}, ensure_ascii=False)


class LightRAGIngestTool(Tool):
    """Send documents or ad-hoc text to a LightRAG server for indexing."""

    def __init__(self, config: LightRAGConfig, *, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._config = config
        self._client = LightRAGClient(config, workspace=workspace, allowed_dir=allowed_dir)

    @property
    def name(self) -> str:
        return "lightrag_ingest"

    @property
    def description(self) -> str:
        return "Ingest text or files into a LightRAG knowledge base. Returns indexing task metadata."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Single text payload to index."},
                "file_path": {"type": "string", "description": "Single file to upload."},
                "file_paths": {
                    "type": "array",
                    "description": "Multiple files to upload.",
                    "items": {"type": "string"},
                },
                "source_label": {
                    "type": "string",
                    "description": "Optional label recorded with the ingestion task.",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        text: str | None = None,
        file_path: str | None = None,
        file_paths: list[str] | None = None,
        source_label: str | None = None,
        **kwargs: Any,
    ) -> str:
        del kwargs
        try:
            normalized_paths = [path for path in (file_paths or []) if isinstance(path, str) and path.strip()]
            source_count = int(bool(text and text.strip())) + int(bool(file_path and file_path.strip())) + int(bool(normalized_paths))
            if source_count != 1:
                return json.dumps(
                    {
                        "error": "Provide exactly one source: text, file_path, or file_paths.",
                    },
                    ensure_ascii=False,
                )

            if text and text.strip():
                payload = await self._client.insert_text(text=text, source_label=source_label)
                target = "text"
            elif file_path and file_path.strip():
                payload = await self._client.upload_files([file_path], source_label=source_label)
                target = "file"
            else:
                payload = await self._client.upload_files(normalized_paths, source_label=source_label)
                target = "files"

            result = {
                "status": payload.get("status", "accepted"),
                "track_id": payload.get("track_id"),
                "document_ids": payload.get("document_ids", []),
                "message": payload.get("message"),
                "target": target,
                "raw": payload,
            }
            return json.dumps(result, ensure_ascii=False)
        except httpx.HTTPStatusError as exc:
            return self._error_response(f"LightRAG ingest failed with HTTP {exc.response.status_code}", exc)
        except httpx.TimeoutException as exc:
            return self._error_response("LightRAG ingest timed out", exc)
        except Exception as exc:
            return self._error_response("LightRAG ingest failed", exc)

    @staticmethod
    def _error_response(message: str, exc: Exception) -> str:
        return json.dumps({"error": message, "details": str(exc)}, ensure_ascii=False)
