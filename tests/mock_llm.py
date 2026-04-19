"""Mock LLM client for testing without API calls."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from nexusagent.llm.base import LLMClient
from nexusagent.models import LLMResponse, ToolCall


class MockLLMClient(LLMClient):
    """
    Mock LLM client that responds with pre-programmed behaviors.
    Useful for testing the agent loop without making real API calls.
    """

    def __init__(self):
        self.responses: list[dict] = []
        self.call_history: list[dict] = []
        self._response_index = 0

    def add_response(self, content: str = "", tool_calls: list[dict] | None = None, stop_reason: str = ""):
        """Add a canned response. tool_calls is a list of {"name": str, "input": dict}."""
        self.responses.append({
            "content": content,
            "tool_calls": tool_calls or [],
            "stop_reason": stop_reason,
        })

    def add_mock_responses(self, *responses):
        """Add multiple responses at once."""
        for r in responses:
            self.add_response(**r)

    async def stream(
        self, messages: list[dict], tools: list[dict], system: str
    ) -> AsyncIterator[LLMResponse]:
        """Return pre-programmed responses with streaming simulation."""
        self.call_history.append({
            "messages": messages,
            "tools": tools,
            "system": system,
        })

        if self._response_index < len(self.responses):
            resp = self.responses[self._response_index]
            self._response_index += 1

            # Stream content character by character (simulated)
            if resp["content"]:
                # Yield the full content in one chunk for simplicity
                yield LLMResponse(content=resp["content"])

            # Yield tool calls
            tool_calls = []
            for i, tc in enumerate(resp["tool_calls"]):
                tool_calls.append(
                    ToolCall(
                        id=f"mock_tc_{i}",
                        name=tc["name"],
                        input=tc.get("input", {}),
                    )
                )
            if tool_calls:
                yield LLMResponse(
                    content="",
                    tool_calls=tool_calls,
                    stop_reason=resp["stop_reason"],
                    usage={"input_tokens": 100, "output_tokens": 50},
                )
        else:
            # Default: return empty response
            yield LLMResponse(
                content="I have completed the task.",
                stop_reason="end_turn",
            )

    async def compress_messages(self, messages: list[dict]) -> str:
        """Return a fake compression summary."""
        return f"[Compressed {len(messages)} messages into summary]"

    def reset(self):
        """Reset state for a new test."""
        self.responses = []
        self.call_history = []
        self._response_index = 0
