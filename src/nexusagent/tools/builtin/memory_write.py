"""MemoryWrite tool: save, update, forget, and list cross-session memories."""

from __future__ import annotations

from pathlib import Path

from nexusagent.memory.frontmatter import format_frontmatter
from nexusagent.memory.index import MemoryEntry, MemoryIndex
from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool

VALID_TYPES = ["user", "feedback", "project", "reference"]
MAX_CONTENT_LENGTH = 10000

# Standard memory files that should be cleared rather than deleted
STANDARD_FILES = {"user.md", "feedback.md", "project.md", "reference.md"}


class MemoryWriteTool(Tool):
    name = "MemoryWrite"
    description = (
        "Save, update, forget, or list cross-session memories. "
        "Use 'save' to create new memories (or update existing ones), "
        "'forget' to remove memories, 'update' to modify content, "
        "and 'list' to see all stored memories."
    )
    parameters = {
        "operation": {
            "type": "string",
            "description": (
                "Operation to perform: 'save' (create/update), "
                "'forget' (delete), 'update' (modify), 'list' (show all)"
            ),
            "required": True,
        },
        "name": {
            "type": "string",
            "description": "Short, unique identifier for the memory",
            "required": False,
        },
        "memory_type": {
            "type": "string",
            "description": f"Type: one of {VALID_TYPES}",
            "required": False,
        },
        "content": {
            "type": "string",
            "description": "Memory content (required for save/update)",
            "required": False,
        },
        "description": {
            "type": "string",
            "description": "Brief description of what this memory captures",
            "required": False,
        },
    }

    def __init__(self, nexus_dir: Path):
        super().__init__(nexus_dir)
        self.nexus_dir = nexus_dir
        self.memory_dir = nexus_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.index = MemoryIndex(nexus_dir)

    async def execute(
        self,
        operation: str,
        name: str = "",
        memory_type: str = "",
        content: str = "",
        description: str = "",
    ) -> ToolResult:
        operation = operation.lower()

        if operation == "save":
            return self._save(name, memory_type, content, description)
        elif operation == "update":
            return self._update(name, memory_type, content, description)
        elif operation == "forget":
            return self._forget(name, memory_type)
        elif operation == "list":
            return self._list(memory_type)
        else:
            return ToolResult(
                content=f"Unknown operation: '{operation}'. Valid: save, update, forget, list",
                is_error=True,
            )

    def _save(
        self, name: str, memory_type: str, content: str, description: str
    ) -> ToolResult:
        errors = self._validate_common(name, memory_type)
        if errors:
            return ToolResult(content=errors, is_error=True)
        if not content:
            return ToolResult(
                content="Error: 'content' is required for save operation",
                is_error=True,
            )
        if len(content) > MAX_CONTENT_LENGTH:
            return ToolResult(
                content=(
                    f"Error: content too long ({len(content)} chars, max {MAX_CONTENT_LENGTH}). "
                    "Split into multiple shorter memories."
                ),
                is_error=True,
            )

        file_name = f"{memory_type}.md"
        file_path = self.memory_dir / file_name

        # Check if this name+type already exists in index
        existing = self.index._find_entry(name, memory_type)
        if existing:
            # Update existing
            self.index.update_entry(
                name, memory_type, file_path=f"memory/{file_name}", description=description
            )
            action = "updated"
        else:
            # New entry
            entry = MemoryEntry(
                name=name,
                memory_type=memory_type,
                file_path=f"memory/{file_name}",
                description=description,
            )
            self.index.add_entry(entry)
            action = "saved"

        # Write file with frontmatter
        from datetime import datetime

        meta = {
            "name": name,
            "type": memory_type,
            "description": description,
            "created": datetime.now().isoformat(),
        }
        formatted = format_frontmatter(meta, content)
        file_path.write_text(formatted, encoding="utf-8")

        # Save index
        self.index.save()

        return ToolResult(
            content=f"Memory '{name}' {action} successfully (type={memory_type})"
        )

    def _update(
        self, name: str, memory_type: str, content: str, description: str
    ) -> ToolResult:
        errors = self._validate_common(name, memory_type)
        if errors:
            return ToolResult(content=errors, is_error=True)

        existing = self.index._find_entry(name, memory_type)
        if not existing:
            return ToolResult(
                content=f"Error: Memory '{name}' (type={memory_type}) not found. "
                "Use operation=save to create a new memory.",
                is_error=True,
            )

        updates = {}
        if description:
            updates["description"] = description
        if updates:
            self.index.update_entry(name, memory_type, **updates)
            self.index.save()

        if content:
            if len(content) > MAX_CONTENT_LENGTH:
                return ToolResult(
                    content=(
                        f"Error: content too long ({len(content)} chars, max {MAX_CONTENT_LENGTH})"
                    ),
                    is_error=True,
                )
            file_path = self.memory_dir / existing.file_path.replace("memory/", "")
            from datetime import datetime

            meta = {
                "name": name,
                "type": memory_type,
                "description": description or existing.description,
                "created": datetime.now().isoformat(),
            }
            formatted = format_frontmatter(meta, content)
            file_path.write_text(formatted, encoding="utf-8")

        return ToolResult(content=f"Memory '{name}' updated successfully")

    def _forget(self, name: str, memory_type: str) -> ToolResult:
        errors = self._validate_common(name, memory_type)
        if errors:
            return ToolResult(content=errors, is_error=True)

        existing = self.index._find_entry(name, memory_type)
        if not existing:
            return ToolResult(
                content=f"Error: Memory '{name}' (type={memory_type}) not found",
                is_error=True,
            )

        # Remove from index
        self.index.remove_entry(name, memory_type)
        self.index.save()

        # Delete or clear file
        file_name = existing.file_path.replace("memory/", "")
        file_path = self.memory_dir / file_name

        if file_name in STANDARD_FILES:
            # Standard file: clear content rather than delete
            if file_path.exists():
                file_path.write_text("", encoding="utf-8")
        else:
            # Dynamic file: delete
            if file_path.exists():
                file_path.unlink()

        return ToolResult(content=f"Memory '{name}' forgotten (type={memory_type})")

    def _list(self, memory_type: str) -> ToolResult:
        if memory_type and memory_type not in VALID_TYPES:
            return ToolResult(
                content=f"Invalid type: '{memory_type}'. Valid: {VALID_TYPES}",
                is_error=True,
            )

        entries = self.index.list_entries(memory_type if memory_type else None)
        if not entries:
            return ToolResult(content="No memories stored")

        lines = []
        current_type = None
        for entry in entries:
            if entry.memory_type != current_type:
                current_type = entry.memory_type
                lines.append(f"\n## {current_type}")
            desc = f" — {entry.description}" if entry.description else ""
            lines.append(f"- {entry.name}{desc}")

        return ToolResult(content="\n".join(lines))

    def _validate_common(self, name: str, memory_type: str) -> str | None:
        if not name:
            return "Error: 'name' is required"
        if not memory_type:
            return f"Error: 'memory_type' is required. Valid: {VALID_TYPES}"
        if memory_type not in VALID_TYPES:
            return f"Error: invalid memory_type '{memory_type}'. Valid: {VALID_TYPES}"
        return None
