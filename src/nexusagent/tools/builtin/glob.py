"""Glob tool: file pattern matching search."""

from __future__ import annotations

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class GlobTool(Tool):
    name = "Glob"
    description = "Find files matching a glob pattern."
    parameters = {
        "pattern": {
            "type": "string",
            "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts')",
            "required": True,
        },
    }

    async def execute(self, pattern: str) -> ToolResult:
        try:
            matches = sorted(self.workdir.glob(pattern))
            if not matches:
                return ToolResult(content=f"No files matched pattern: {pattern}")

            paths = [str(p.relative_to(self.workdir)) for p in matches if p.is_file()]
            limit = 100
            if len(paths) > limit:
                result = "\n".join(paths[:limit])
                result += f"\n... and {len(paths) - limit} more files"
            else:
                result = "\n".join(paths)

            return ToolResult(
                content=result,
                metadata={"count": len(paths), "pattern": pattern},
            )
        except Exception as e:
            return ToolResult(content=f"Error in glob: {e}", is_error=True)
