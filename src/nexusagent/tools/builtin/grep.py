"""Grep tool: file content regex search."""

from __future__ import annotations

import re

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class GrepTool(Tool):
    name = "Grep"
    description = "Search for a pattern in files. Supports regex."
    parameters = {
        "pattern": {
            "type": "string",
            "description": "Regex pattern to search for",
            "required": True,
        },
        "path": {
            "type": "string",
            "description": "File or directory to search in (default: current directory)",
            "required": False,
        },
        "file_pattern": {
            "type": "string",
            "description": "Glob pattern to filter files (e.g., '*.py')",
            "required": False,
        },
    }

    async def execute(
        self, pattern: str, path: str = ".", file_pattern: str | None = None
    ) -> ToolResult:
        try:
            search_path = self._resolve_path(path) if path else self.workdir
            if not search_path.exists():
                return ToolResult(content=f"Path not found: {search_path}", is_error=True)

            # Collect files to search
            if search_path.is_file():
                files = [search_path]
            else:
                glob_pat = file_pattern or "**/*"
                files = [p for p in search_path.glob(glob_pat) if p.is_file()]

            regex = re.compile(pattern)
            results = []

            for file in files:
                try:
                    content = self._safe_read(file, max_bytes=100_000)
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            rel = file.relative_to(self.workdir)
                            results.append(f"{rel}:{i}: {line.strip()}")
                except Exception:
                    continue

            if not results:
                return ToolResult(content=f"No matches for pattern: {pattern}")

            limit = 100
            if len(results) > limit:
                output = "\n".join(results[:limit])
                output += f"\n... and {len(results) - limit} more matches"
            else:
                output = "\n".join(results)

            return ToolResult(
                content=output,
                metadata={"count": len(results), "pattern": pattern},
            )
        except Exception as e:
            return ToolResult(content=f"Error in grep: {e}", is_error=True)
