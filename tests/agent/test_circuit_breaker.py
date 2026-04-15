"""Tests for the circuit breaker (repeated tool call failure protection)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.providers.base import LLMResponse, ToolCallRequest


# ---------------------------------------------------------------------------
# _tool_call_signature
# ---------------------------------------------------------------------------

class TestToolCallSignature:
    def test_same_args_different_order_same_sig(self):
        sig1 = AgentRunner._tool_call_signature("exec", {"b": 2, "a": 1})
        sig2 = AgentRunner._tool_call_signature("exec", {"a": 1, "b": 2})
        assert sig1 == sig2

    def test_different_args_different_sig(self):
        sig1 = AgentRunner._tool_call_signature("exec", {"command": "ls"})
        sig2 = AgentRunner._tool_call_signature("exec", {"command": "pwd"})
        assert sig1 != sig2

    def test_different_tool_name_different_sig(self):
        sig1 = AgentRunner._tool_call_signature("exec", {"command": "ls"})
        sig2 = AgentRunner._tool_call_signature("grep", {"command": "ls"})
        assert sig1 != sig2

    def test_extra_space_produces_different_sig(self):
        """Literal-level check: extra space means different signature."""
        sig1 = AgentRunner._tool_call_signature("exec", {"command": "git clone x"})
        sig2 = AgentRunner._tool_call_signature("exec", {"command": "git clone  x"})
        assert sig1 != sig2

    def test_empty_args(self):
        sig = AgentRunner._tool_call_signature("list_dir", {})
        assert sig == "list_dir:{}"


# ---------------------------------------------------------------------------
# _tool_call_succeeded
# ---------------------------------------------------------------------------

class TestToolCallSucceeded:
    def test_normal_string_success(self):
        assert AgentRunner._tool_call_succeeded("hello world") is True

    def test_error_string_failure(self):
        assert AgentRunner._tool_call_succeeded("Error: timeout") is False

    def test_none_failure(self):
        assert AgentRunner._tool_call_succeeded(None) is False

    def test_exec_failure_with_exit_code(self):
        result = "Exit code: 128\nstderr: fatal: ...\n"
        # exec failures include "Error:" prefix from _run_tool
        # but raw exit code strings without "Error" are still success
        # (they don't start with "Error")
        assert AgentRunner._tool_call_succeeded(result) is True

    def test_run_tool_wrapped_error(self):
        result = "Error: RuntimeError: something went wrong\n\n[Analyze the error above and try a different approach.]"
        assert AgentRunner._tool_call_succeeded(result) is False

    def test_non_string_truthy(self):
        assert AgentRunner._tool_call_succeeded([]) is True
        assert AgentRunner._tool_call_succeeded(0) is True
        assert AgentRunner._tool_call_succeeded({}) is True


# ---------------------------------------------------------------------------
# _check_repeated_tool_failure
# ---------------------------------------------------------------------------

class TestCheckRepeatedToolFailure:
    def _entry(self, sig: str, iteration: int = 0, tool_name: str = "exec", success: bool = True, blocked: bool = False) -> dict:
        return {"sig": sig, "iteration": iteration, "tool_name": tool_name, "success": success, "blocked": blocked}

    def test_no_history_no_trigger(self):
        result = AgentRunner._check_repeated_tool_failure("exec:{}", [])
        assert result is None

    def test_one_failure_no_trigger(self):
        history = [self._entry("exec:{\"command\":\"git clone x\"}", success=False)]
        result = AgentRunner._check_repeated_tool_failure("exec:{\"command\":\"git clone x\"}", history)
        assert result is None

    def test_two_failures_triggers_on_third(self):
        """With 2 consecutive failures in history, the 3rd attempt is blocked."""
        sig = "exec:{\"command\":\"git clone x\"}"
        history = [
            self._entry(sig, success=False),
            self._entry(sig, success=False),
        ]
        result = AgentRunner._check_repeated_tool_failure(sig, history)
        assert result is not None
        assert "attempted 3 times" in result

    def test_three_failures_triggers(self):
        sig = "exec:{\"command\":\"git clone x\"}"
        history = [
            self._entry(sig, iteration=0, success=False),
            self._entry(sig, iteration=1, success=False),
        ]
        result = AgentRunner._check_repeated_tool_failure(sig, history)
        assert result is not None
        assert "attempted 3 times" in result
        assert "DO NOT repeat this command" in result

    def test_previous_success_breaks_chain(self):
        """Same signature but previous call succeeded → no trigger."""
        sig = "exec:{\"command\":\"git clone x\"}"
        history = [
            self._entry(sig, iteration=0, success=True),
            self._entry(sig, iteration=1, success=False),
        ]
        result = AgentRunner._check_repeated_tool_failure(sig, history)
        assert result is None

    def test_interleaved_different_signature_reset(self):
        """Two failures, then a different command, then the original → no trigger."""
        sig_a = "exec:{\"command\":\"git clone x\"}"
        sig_b = "exec:{\"command\":\"ls\"}"
        history = [
            self._entry(sig_a, iteration=0, success=False),
            self._entry(sig_b, iteration=1, success=False),
            self._entry(sig_a, iteration=2, success=False),
        ]
        result = AgentRunner._check_repeated_tool_failure(sig_a, history)
        assert result is None

    def test_blocked_calls_count_as_failure(self):
        """Previously blocked calls still count as failures for the chain."""
        sig = "exec:{\"command\":\"git clone x\"}"
        history = [
            self._entry(sig, iteration=0, success=False, blocked=True),
            self._entry(sig, iteration=1, success=False),
        ]
        result = AgentRunner._check_repeated_tool_failure(sig, history)
        assert result is not None

    def test_max_consecutive_parameter(self):
        """Custom max_consecutive=2 should trigger after 2 failures."""
        sig = "exec:{\"command\":\"git clone x\"}"
        history = [self._entry(sig, iteration=0, success=False)]
        result = AgentRunner._check_repeated_tool_failure(sig, history, max_consecutive=2)
        assert result is not None
        assert "attempted 2 times" in result


# ---------------------------------------------------------------------------
# Integration: full runner loop with circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:
    def _make_registry(self, execute_result=None, fail=False):
        registry = MagicMock()
        registry.get_definitions.return_value = []
        if fail:
            registry.execute = AsyncMock(return_value="Error: Command failed with exit code 128")
        else:
            registry.execute = AsyncMock(return_value=execute_result or "ok")
        return registry

    @pytest.mark.asyncio
    async def test_third_identical_failure_blocked(self):
        """When provider returns the same failing tool call 3 times,
        the 3rd call must NOT be executed (blocked by circuit breaker)."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        call_count = {"n": 0}

        async def chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 3:
                # Always returns the same tool call
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(
                        id=f"call_{call_count['n']}",
                        name="exec",
                        arguments={"command": "git clone https://example.com/x"},
                    )],
                    usage={},
                )
            return LLMResponse(content="I give up", tool_calls=[], usage={})

        provider.chat_with_retry = chat_with_retry
        tools = self._make_registry(fail=True)
        execute_spy = tools.execute

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "clone this"}],
            tools=tools,
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=8000,
        ))

        # The tool should only have been called 2 times (iterations 0 and 1)
        # On iteration 2, the circuit breaker blocks the call
        assert execute_spy.call_count == 2

        # The blocked third call now records a guard event for observability.
        assert len(result.tool_events) == 3
        assert result.tool_events[-1]["status"] == "error"
        assert result.tool_events[-1]["detail"] == "tool loop guard blocked"

    @pytest.mark.asyncio
    async def test_different_command_after_block_resumes(self):
        """After the 3rd identical call is blocked, if the LLM sends a
        different tool call on the next iteration, it should execute normally."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        call_count = {"n": 0}

        async def chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(
                        id=f"call_{call_count['n']}",
                        name="exec",
                        arguments={"command": "git clone https://example.com/x"},
                    )],
                    usage={},
                )
            if call_count["n"] == 3:
                # Circuit breaker blocked this iteration, LLM gets error
                # Next call: LLM tries a different command
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(
                        id="call_3",
                        name="exec",
                        arguments={"command": "ls"},
                    )],
                    usage={},
                )
            return LLMResponse(content="done", tool_calls=[], usage={})

        provider.chat_with_retry = chat_with_retry
        tools = self._make_registry(fail=True)
        execute_spy = tools.execute

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "clone this"}],
            tools=tools,
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=8000,
        ))

        # Calls: iteration 0 (git clone), iteration 1 (git clone),
        # iteration 2 blocked, iteration 3 (ls - different, should execute)
        assert execute_spy.call_count == 3
        # Verify "ls" was actually called
        call_args = [str(c) for c in execute_spy.call_args_list]
        assert any("ls" in c for c in call_args)
        assert result.final_content == "done"

    @pytest.mark.asyncio
    async def test_same_call_with_success_does_not_trigger(self):
        """If the same tool call succeeds, circuit breaker should not trigger."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        call_count = {"n": 0}

        async def chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 3:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(
                        id=f"call_{call_count['n']}",
                        name="exec",
                        arguments={"command": "ls"},
                    )],
                    usage={},
                )
            return LLMResponse(content="done", tool_calls=[], usage={})

        provider.chat_with_retry = chat_with_retry
        tools = self._make_registry(execute_result="file1\nfile2\n")

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "list files"}],
            tools=tools,
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=8000,
        ))

        # All 3 calls should execute (all succeed)
        assert tools.execute.call_count == 3
        assert result.final_content == "done"

    @pytest.mark.asyncio
    async def test_circuit_breaker_message_in_tool_result(self):
        """The synthetic result sent to the LLM should be a structured error."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        call_count = {"n": 0}

        async def chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 3:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(
                        id=f"call_{call_count['n']}",
                        name="exec",
                        arguments={"command": "git clone x"},
                    )],
                    usage={},
                )
            # After the block, return final
            return LLMResponse(content="finished", tool_calls=[], usage={})

        provider.chat_with_retry = chat_with_retry
        tools = self._make_registry(fail=True)

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "clone"}],
            tools=tools,
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=8000,
        ))

        # Only 2 actual executions (iteration 2 was blocked by circuit breaker)
        assert tools.execute.call_count == 2

        # The blocked third call now records a guard event for observability.
        assert len(result.tool_events) == 3
        assert result.tool_events[-1]["status"] == "error"
        assert result.tool_events[-1]["detail"] == "tool loop guard blocked"

    @pytest.mark.asyncio
    async def test_concurrent_mixed_blocked_and_allowed(self):
        """When a single LLM response contains multiple tool calls, some
        blocked (repeated failure) and some allowed, all execute correctly
        and results are merged in the original order."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        call_count = {"n": 0}

        async def chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First iteration: two different failing tool calls
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_1a",
                            name="exec",
                            arguments={"command": "git clone x"},
                        ),
                        ToolCallRequest(
                            id="call_1b",
                            name="exec",
                            arguments={"command": "git clone y"},
                        ),
                    ],
                    usage={},
                )
            if call_count["n"] == 2:
                # Second iteration: both fail again
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_2a",
                            name="exec",
                            arguments={"command": "git clone x"},
                        ),
                        ToolCallRequest(
                            id="call_2b",
                            name="exec",
                            arguments={"command": "git clone y"},
                        ),
                    ],
                    usage={},
                )
            if call_count["n"] == 3:
                # Third iteration: git clone x is blocked, git clone y is blocked,
                # but a new 'ls' call should execute
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            id="call_3a",
                            name="exec",
                            arguments={"command": "git clone x"},
                        ),
                        ToolCallRequest(
                            id="call_3b",
                            name="exec",
                            arguments={"command": "ls"},
                        ),
                    ],
                    usage={},
                )
            return LLMResponse(content="done", tool_calls=[], usage={})

        provider.chat_with_retry = chat_with_retry
        tools = self._make_registry(fail=True)
        execute_spy = tools.execute

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "clone repos"}],
            tools=tools,
            model="test-model",
            max_iterations=5,
            max_tool_result_chars=8000,
            concurrent_tools=True,
        ))

        # Iteration 0: git clone x + git clone y = 2 executions
        # Iteration 1: git clone x + git clone y = 2 more (total 4)
        #   history alternates [x_fail, y_fail, x_fail, y_fail] — different
        #   signatures dilute the consecutive check, so neither is blocked yet
        # Iteration 2: git clone x + ls = 2 more (total 6)
        # Iteration 3: LLM returns final response, no tool calls
        assert execute_spy.call_count == 6
        # Verify "ls" was called
        call_args = [str(c) for c in execute_spy.call_args_list]
        assert any("ls" in c for c in call_args)
        assert result.final_content == "done"

    @pytest.mark.asyncio
    async def test_concurrent_same_response_duplicates(self):
        """When a single response contains two identical tool calls (same
        signature), both are allowed on first attempt but would be blocked
        on subsequent iterations if they keep failing."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        call_count = {"n": 0}

        async def chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Two identical calls in one response — both allowed first time
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(id="call_dup1", name="exec", arguments={"command": "git clone x"}),
                        ToolCallRequest(id="call_dup2", name="exec", arguments={"command": "git clone x"}),
                    ],
                    usage={},
                )
            if call_count["n"] == 2:
                # Both failed in iteration 0, so iteration 1 has 2 failures
                # in history for this signature → circuit breaker triggers
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(id="call_dup3", name="exec", arguments={"command": "git clone x"}),
                    ],
                    usage={},
                )
            return LLMResponse(content="gave up", tool_calls=[], usage={})

        provider.chat_with_retry = chat_with_retry
        tools = self._make_registry(fail=True)
        execute_spy = tools.execute

        runner = AgentRunner(provider)
        result = await runner.run(AgentRunSpec(
            initial_messages=[{"role": "user", "content": "clone twice"}],
            tools=tools,
            model="test-model",
            max_iterations=4,
            max_tool_result_chars=8000,
            concurrent_tools=True,
        ))

        # Iteration 0: 2 executions (both identical, both allowed)
        # Iteration 1: blocked (2 failures in history → 3rd attempt blocked)
        # Iteration 2: LLM returns "gave up" with no tool calls, loop exits
        assert execute_spy.call_count == 2
