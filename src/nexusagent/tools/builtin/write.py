"""Write tool: create/overwrite files, with precise string replacement."""

from __future__ import annotations

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class WriteTool(Tool):
    name = "Write"
    description = (
        "Create or overwrite a file. Also supports 'str_replace' mode for precise edits."
    )
    parameters = {
        "file_path": {
            "type": "string",
            "description": "Path to the file (relative or absolute)",
            "required": True,
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file",
            "required": False,
        },
        "mode": {
            "type": "string",
            "description": "Write mode: 'overwrite' (default), 'append', or 'str_replace'",
            "required": False,
        },
        "old_str": {
            "type": "string",
            "description": "String to replace (only for 'str_replace' mode)",
            "required": False,
        },
        "new_str": {
            "type": "string",
            "description": "Replacement string (only for 'str_replace' mode)",
            "required": False,
        },
    }

    async def execute(
        self,
        file_path: str,
        content: str = "",
        mode: str = "overwrite",
        old_str: str = "",
        new_str: str = "",
    ) -> ToolResult:
        path = self._resolve_path(file_path)

        try:
            if mode == "str_replace":
                if not path.exists():
                    return ToolResult(
                        content=f"Error: File not found for str_replace: {path}",
                        is_error=True,
                    )
                original = path.read_text(errors="replace")
                if old_str not in original:
                    return ToolResult(
                        content=f"Error: 'old_str' not found in file. "
                        f"Cannot perform str_replace.",
                        is_error=True,
                    )
                updated = original.replace(old_str, new_str, 1)
                path.write_text(updated, encoding="utf-8")
                return ToolResult(content=f"Successfully replaced text in {path}")

            elif mode == "append":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return ToolResult(content=f"Successfully appended to {path}")

            else:  # overwrite
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return ToolResult(content=f"Successfully wrote {path} ({len(content)} bytes)")

        except Exception as e:
            return ToolResult(content=f"Error writing file: {e}", is_error=True)
