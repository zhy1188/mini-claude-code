"""Read tool: read file contents with line range support."""

from __future__ import annotations

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class ReadTool(Tool):
    name = "Read"
    description = "Read the contents of a file. Supports line range limits."
    parameters = {
        "file_path": {
            "type": "string",
            "description": "Path to the file to read (relative or absolute)",
            "required": True,
        },
        "start_line": {
            "type": "integer",
            "description": "Start line number (1-indexed, default: 1)",
            "required": False,
        },
        "end_line": {
            "type": "integer",
            "description": "End line number (inclusive, default: last line)",
            "required": False,
        },
    }

    async def execute(
        self, file_path: str, start_line: int = None, end_line: int = None
    ) -> ToolResult:
        path = self._resolve_path(file_path)

        if not path.exists():
            return ToolResult(content=f"Error: File not found: {path}", is_error=True)

        if not path.is_file():
            return ToolResult(content=f"Error: Not a file: {path}", is_error=True)

        try:
            content = self._safe_read(path)
            lines = content.splitlines()

            # Apply line range
            start = (start_line or 1) - 1  # Convert to 0-indexed
            end = end_line if end_line is not None else len(lines)
            selected = lines[start:end]

            # Add line numbers
            numbered = []
            for i, line in enumerate(selected, start=start + 1):
                numbered.append(f"{i:6d}  {line}")

            result = "\n".join(numbered)
            if not result:
                result = "(empty file)"

            return ToolResult(content=result, metadata={"total_lines": len(lines)})
        except Exception as e:
            return ToolResult(content=f"Error reading file: {e}", is_error=True)
