import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import lightrag as lightrag_module
from nanobot.agent.tools.lightrag import LightRAGIngestTool, LightRAGQueryTool
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import LightRAGConfig


class _StubProvider:
    def get_default_model(self) -> str:
        return "test-model"


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("POST", "http://test")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    calls: list[dict] = []
    response: _FakeResponse | None = None
    exception: Exception | None = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.__class__.calls.append({"url": url, **kwargs})
        if self.__class__.exception is not None:
            raise self.__class__.exception
        assert self.__class__.response is not None
        return self.__class__.response


@pytest.fixture
def lightrag_config() -> LightRAGConfig:
    return LightRAGConfig(enabled=True, base_url="http://localhost:9621")


@pytest.fixture(autouse=True)
def reset_fake_client(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = None
    _FakeAsyncClient.exception = None
    monkeypatch.setattr(lightrag_module.httpx, "AsyncClient", _FakeAsyncClient)


def _make_loop(tmp_path: Path, lightrag_config: LightRAGConfig) -> AgentLoop:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        lightrag_config=lightrag_config,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_query_tool_uses_defaults_and_returns_response_json(lightrag_config: LightRAGConfig) -> None:
    _FakeAsyncClient.response = _FakeResponse(
        200,
        {
            "response": "answer",
            "query": "what is this",
            "mode": "hybrid",
            "execution_time": 0.12,
        },
    )
    tool = LightRAGQueryTool(lightrag_config)

    result = json.loads(await tool.execute("what is this"))

    assert result["response"] == "answer"
    assert result["mode"] == "hybrid"
    assert _FakeAsyncClient.calls[0]["url"] == "http://localhost:9621/query"
    assert _FakeAsyncClient.calls[0]["json"]["only_need_context"] is False
    assert _FakeAsyncClient.calls[0]["json"]["top_k"] == 10


@pytest.mark.asyncio
async def test_query_tool_forwards_context_only_flag(lightrag_config: LightRAGConfig) -> None:
    _FakeAsyncClient.response = _FakeResponse(
        200,
        {"response": "ctx", "mode": "local", "execution_time": 0.2},
    )
    tool = LightRAGQueryTool(lightrag_config)

    await tool.execute(
        "find context",
        mode="local",
        only_need_context=True,
        conversation_history=[{"role": "user", "content": "earlier"}],
    )

    payload = _FakeAsyncClient.calls[0]["json"]
    assert payload["mode"] == "local"
    assert payload["only_need_context"] is True
    assert payload["conversation_history"][0]["content"] == "earlier"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 500])
async def test_query_tool_reports_http_errors(lightrag_config: LightRAGConfig, status_code: int) -> None:
    _FakeAsyncClient.response = _FakeResponse(status_code, {"detail": "bad"})
    tool = LightRAGQueryTool(lightrag_config)

    result = json.loads(await tool.execute("broken"))

    assert "error" in result
    assert str(status_code) in result["error"]


@pytest.mark.asyncio
async def test_query_tool_reports_timeout(lightrag_config: LightRAGConfig) -> None:
    _FakeAsyncClient.exception = httpx.ReadTimeout("timeout")
    tool = LightRAGQueryTool(lightrag_config)

    result = json.loads(await tool.execute("slow request"))

    assert result["error"] == "LightRAG query timed out"


@pytest.mark.asyncio
async def test_ingest_tool_accepts_single_text(lightrag_config: LightRAGConfig, tmp_path: Path) -> None:
    _FakeAsyncClient.response = _FakeResponse(200, {"status": "accepted", "track_id": "trk-1"})
    tool = LightRAGIngestTool(lightrag_config, workspace=tmp_path)

    result = json.loads(await tool.execute(text="hello world", source_label="notes"))

    assert result["status"] == "accepted"
    assert result["track_id"] == "trk-1"
    assert _FakeAsyncClient.calls[0]["url"] == "http://localhost:9621/documents/text"


@pytest.mark.asyncio
async def test_ingest_tool_uploads_single_file(lightrag_config: LightRAGConfig, tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")
    _FakeAsyncClient.response = _FakeResponse(200, {"status": "accepted", "track_id": "trk-file"})
    tool = LightRAGIngestTool(lightrag_config, workspace=tmp_path)

    result = json.loads(await tool.execute(file_path="sample.txt"))

    assert result["target"] == "file"
    files = _FakeAsyncClient.calls[0]["files"]
    assert files[0][1][0] == "sample.txt"


@pytest.mark.asyncio
async def test_ingest_tool_uploads_multiple_files(lightrag_config: LightRAGConfig, tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    _FakeAsyncClient.response = _FakeResponse(200, {"status": "accepted", "track_id": "trk-files"})
    tool = LightRAGIngestTool(lightrag_config, workspace=tmp_path)

    result = json.loads(await tool.execute(file_paths=["a.txt", "b.txt"]))

    assert result["target"] == "files"
    assert len(_FakeAsyncClient.calls[0]["files"]) == 2


@pytest.mark.asyncio
async def test_ingest_tool_rejects_conflicting_inputs(lightrag_config: LightRAGConfig, tmp_path: Path) -> None:
    tool = LightRAGIngestTool(lightrag_config, workspace=tmp_path)

    result = json.loads(await tool.execute(text="x", file_paths=["a.txt"]))

    assert result["error"] == "Provide exactly one source: text, file_path, or file_paths."


def test_agent_loop_registers_lightrag_tools_only_when_enabled(tmp_path: Path) -> None:
    disabled = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        lightrag_config=LightRAGConfig(enabled=False),
    )
    enabled = _make_loop(tmp_path, LightRAGConfig(enabled=True))

    assert disabled.tools.get("lightrag_query") is None
    assert disabled.tools.get("lightrag_ingest") is None
    assert enabled.tools.get("lightrag_query") is not None
    assert enabled.tools.get("lightrag_ingest") is not None
