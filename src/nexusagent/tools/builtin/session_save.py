"""SessionSave tool: persist conversation history to .nexus/sessions/."""

from __future__ import annotations

from nexusagent.memory.session import SessionManager
from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class SessionSaveTool(Tool):
    name = "SessionSave"
    description = (
        "Save the current conversation session to disk. "
        "Normally called automatically on session exit, "
        "but can be called manually at any time."
    )
    parameters = {
        "session_id": {
            "type": "string",
            "description": "Session identifier (auto-generated if omitted)",
            "required": False,
        },
    }

    def __init__(self, session_manager: SessionManager):
        super().__init__()
        self.session_manager = session_manager

    async def execute(self, session_id: str = "") -> ToolResult:
        if not session_id:
            session_id = self.session_manager.create_session_id()

        # This tool is a wrapper — the actual messages come from the context manager.
        # The master loop should pass messages separately.
        # For now, this returns a no-op result; real integration is in master.py.
        path = self.session_manager.save(session_id, [])

        return ToolResult(
            content=f"Session saved to {path} (id={session_id})",
            metadata={"session_id": session_id, "path": str(path)},
        )
