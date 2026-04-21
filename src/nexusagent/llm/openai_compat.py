"""OpenAI-compatible API client (vLLM, Ollama, DeepSeek, etc.)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from nexusagent.llm.base import LLMClient
from nexusagent.models import LLMResponse, ToolCall


class OpenAICompatibleClient(LLMClient):
    """Client for any OpenAI-compatible API."""

    def __init__(
        self,
        model: str = "qwen3.6-plus",
        api_key: str = "",
        base_url: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.7,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        kwargs = {"api_key": api_key} if api_key else {}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)

    async def stream(
        self, messages: list[dict], tools: list[dict], system: str
    ) -> AsyncIterator[LLMResponse]:
        """Stream response from OpenAI-compatible API."""
        full_messages = []
        if system:
            full_messages.insert(0, {"role": "system", "content": system})
        full_messages.extend(messages)

        tool_defs = None
        if tools:
            tool_defs = [{"type": "function", "function": t} for t in tools]

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            tools=tool_defs,
            stream=True,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        full_content = ""
        # Accumulate tool call arguments across streaming chunks
        tool_call_chunks: dict[int, dict] = {}
        tool_calls = []

        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            if delta.content:
                full_content += delta.content
                yield LLMResponse(content=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_call_chunks:
                        tool_call_chunks[idx] = {
                            "id": tc.id,
                            "name": tc.function.name if tc.function else "",
                            "args": "",
                        }
                    if tc.function:
                        if tc.function.name:
                            tool_call_chunks[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_call_chunks[idx]["args"] += tc.function.arguments

        # Parse accumulated tool calls
        for idx in sorted(tool_call_chunks.keys()):
            tc_data = tool_call_chunks[idx]
            name = tc_data["name"]
            args_str = tc_data["args"]
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}
            if name:
                tool_calls.append(
                    ToolCall(id=tc_data["id"], name=name, input=args)
                )

        # Emit final response with metadata only (no content duplication)
        yield LLMResponse(
            content="",
            tool_calls=tool_calls,
            stop_reason=chunk.choices[0].finish_reason if chunk.choices else "",
            usage={
                "input_tokens": chunk.usage.prompt_tokens if chunk.usage else 0,
                "output_tokens": chunk.usage.completion_tokens if chunk.usage else 0,
            },
        )

    async def compress_messages(self, messages: list[dict]) -> str:
        """Compress messages into a summary."""
        full_messages = [
            {"role": "system", "content": "Summarize this conversation concisely."},
            *messages,
        ]
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            max_tokens=2048,
            temperature=0,
        )
        return response.choices[0].message.content or ""
