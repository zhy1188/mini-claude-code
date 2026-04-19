"""Anthropic Claude API client with prompt caching and extended thinking support."""

from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from nexusagent.llm.base import LLMClient
from nexusagent.models import LLMResponse, ToolCall


class AnthropicClient(LLMClient):
    """
    Client for Anthropic's Claude API with streaming, prompt caching, and extended thinking.

    Prompt Caching:
        - System prompt sections with cache_control=True are sent as cached content blocks
        - Anthropic API caches the longest common prefix across consecutive requests
        - Expected cache hit rate: 60-80% in multi-turn conversations

    Extended Thinking:
        - When thinking_budget > 0, enables Claude's deep reasoning mode
        - thinking_budget controls max tokens for the internal reasoning trace
        - Only available on Claude 3.5 Sonnet and Opus models
    """

    def __init__(
        self,
        model: str = "qwen3.6-plus",
        api_key: str = "",
        max_tokens: int = 8192,
        temperature: float = 0.7,
        thinking_budget: int = 0,  # Extended thinking: 0 = disabled
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.thinking_budget = thinking_budget
        self.client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()

    def _build_system_prompt(self, system: str | list[dict]) -> list[dict]:
        """
        Convert system prompt to Anthropic's content blocks format with cache control.

        If system is already a list of blocks (from PromptBuilder), use as-is.
        If system is a string, wrap it in a single cacheable block.
        """
        if isinstance(system, list):
            # Already structured blocks from PromptBuilder
            # Clean up None cache_control values
            blocks = []
            for block in system:
                clean_block = {k: v for k, v in block.items() if v is not None}
                blocks.append(clean_block)
            return blocks
        # Plain string → single block
        return [{"type": "text", "text": system}]

    async def stream(
        self, messages: list[dict], tools: list[dict], system: str | list[dict]
    ) -> AsyncIterator[LLMResponse]:
        """Stream response from Claude with prompt caching support."""
        system_blocks = self._build_system_prompt(system)

        extra_params = {}
        if self.thinking_budget > 0:
            extra_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }
            # Thinking mode requires temperature=1.0
            temperature = 1.0
        else:
            temperature = self.temperature

        async with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_blocks,
            messages=messages,
            tools=tools if tools else None,
            temperature=temperature,
            **extra_params,
        ) as stream:
            content_parts = []
            tool_calls = []

            async for event in stream:
                # Handle text delta
                if event.type == "content_block_delta":
                    # Skip thinking deltas - they're internal
                    if hasattr(event.delta, "type") and event.delta.type == "thinking_delta":
                        continue
                    if hasattr(event.delta, "text") and event.delta.text:
                        yield LLMResponse(content=event.delta.text)

                # Handle tool use
                elif event.type == "content_block_start":
                    if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                id=event.content_block.id,
                                name=event.content_block.name,
                                input=event.content_block.input,
                            )
                        )

            # Build final response
            full_text = ""
            async for chunk in stream.text_stream:
                full_text += chunk

            # Get the final message to extract tool calls
            final = await stream.get_final_message()
            for block in final.content:
                if block.type == "tool_use":
                    tool_calls.append(
                        ToolCall(id=block.id, name=block.name, input=block.input)
                    )
                    full_text = ""  # Tool call response, no text content

            yield LLMResponse(
                content=full_text,
                tool_calls=tool_calls,
                stop_reason=final.stop_reason or "",
                usage={
                    "input_tokens": getattr(final.usage, "input_tokens", 0) if hasattr(final, "usage") else 0,
                    "output_tokens": getattr(final.usage, "output_tokens", 0) if hasattr(final, "usage") else 0,
                    "cache_read_input_tokens": getattr(final.usage, "cache_read_input_tokens", 0) if hasattr(final, "usage") else 0,
                    "cache_creation_input_tokens": getattr(final.usage, "cache_creation_input_tokens", 0) if hasattr(final, "usage") else 0,
                },
            )

    async def compress_messages(self, messages: list[dict]) -> str:
        """Compress messages into a summary for context compaction."""
        prompt = (
            "Please provide a concise summary of the following conversation. "
            "Preserve all important decisions, code changes, and findings. "
            "Format as a structured summary.\n\n"
        )
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = str(content)
            prompt += f"[{role}]: {content}\n\n"

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system="You are a context compression assistant. Summarize conversations concisely.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.content[0].text if response.content else ""
