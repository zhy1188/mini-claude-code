"""Task tool: spawns sub-agents for parallel task execution."""

from __future__ import annotations

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class TaskTool(Tool):
    name = "Task"
    description = (
        "Launch a sub-agent to handle a complex, self-contained task in parallel. "
        "Use this for tasks that can run independently (e.g., analyzing different files, "
        "running tests, searching codebases)."
    )
    parameters = {
        "description": {
            "type": "string",
            "description": "A short description of what the sub-agent should do",
            "required": True,
        },
        "subagent_type": {
            "type": "string",
            "description": "Type of sub-agent: 'general' (default), 'research', 'code'",
            "required": False,
        },
        "prompt": {
            "type": "string",
            "description": "Detailed instructions for the sub-agent",
            "required": False,
        },
    }

    def __init__(self, workdir, orchestrator=None, all_tools=None):
        super().__init__(workdir)
        self._orchestrator = orchestrator
        self._all_tools = all_tools

    def set_orchestrator(self, orchestrator, all_tools):
        """Set the orchestrator reference after it's created (avoids circular deps)."""
        self._orchestrator = orchestrator
        self._all_tools = all_tools

    async def execute(
        self,
        description: str,
        subagent_type: str = "general",
        prompt: str = "",
    ) -> ToolResult:
        if not self._orchestrator:
            return ToolResult(
                content="Error: Task tool requires orchestrator to be set.",
                is_error=True,
            )

        if not self._all_tools:
            return ToolResult(
                content="Error: Task tool requires tool registry reference.",
                is_error=True,
            )

        # Select tools based on subagent_type
        from nexusagent.agent.orchestrator import SubTask

        task = SubTask(description=description, prompt=prompt)

        # Spawn and run via orchestrator
        results = await self._orchestrator.spawn([task])

        if not results:
            return ToolResult(content="No results from sub-agent", is_error=True)

        result = results[0]
        if result.status == "success":
            return ToolResult(
                content=f"Sub-agent completed:\n{result.summary}",
                metadata={
                    "tool_calls_made": result.tool_calls_made,
                    "token_usage": result.token_usage,
                    "artifacts": result.artifacts,
                },
            )
        else:
            return ToolResult(
                content=f"Sub-agent failed:\n{result.summary}", is_error=True
            )
