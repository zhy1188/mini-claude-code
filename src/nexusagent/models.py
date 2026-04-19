"""Core data models for NexusAgent."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Agent State ───────────────────────────────────────────────────────────

class AgentState(Enum):
    IDLE = "idle"
    GATHERING = "gathering"
    THINKING = "thinking"
    ACTING = "acting"
    VERIFYING = "verifying"
    COMPACTING = "compacting"
    DONE = "done"
    ERROR = "error"


# ─── Messages ──────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str
    token_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_api_format(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class UserMessage(Message):
    role: str = "user"


class AssistantMessage(Message):
    role: str = "assistant"


class SystemMessage(Message):
    role: str = "system"


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class ToolResultMessage(Message):
    role: str = "user"
    tool_call_id: str = ""
    tool_name: str = ""

    def to_api_format(self) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": self.tool_call_id,
                    "content": self.content,
                }
            ],
        }


# ─── Tool ──────────────────────────────────────────────────────────────────

class ToolResult(BaseModel):
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── LLM Response ──────────────────────────────────────────────────────────

class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = ""
    usage: dict[str, int] = Field(default_factory=dict)


# ─── Sub-Agent ─────────────────────────────────────────────────────────────

class AgentResult(BaseModel):
    task: str
    status: str = "success"
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    tool_calls_made: int = 0
    token_usage: int = 0


# ─── Permission ────────────────────────────────────────────────────────────

class PermissionDecision(Enum):
    APPROVE = "approve"
    DENY = "deny"
    WAITING = "waiting"
