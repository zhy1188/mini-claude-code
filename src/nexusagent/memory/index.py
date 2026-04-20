"""Memory index manager for .nexus/MEMORY.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MemoryEntry:
    name: str
    memory_type: str
    file_path: str
    description: str = ""


class MemoryIndex:
    """
    Manages the .nexus/MEMORY.md index file.

    Format:
        # NexusAgent Memory Index
        ## user
        - [Name](memory/user.md) -- description
    """

    VALID_TYPES = ["user", "feedback", "project", "reference"]
    _ENTRY_RE = re.compile(r"^-\s+\[([^\]]+)\]\(([^)]+)\)\s*(?:--\s+(.*))?$")

    def __init__(self, nexus_dir: Path, max_entries_per_type: int = 50):
        self.nexus_dir = nexus_dir
        self.index_file = nexus_dir / "MEMORY.md"
        self.max_entries_per_type = max_entries_per_type
        self.entries: list[MemoryEntry] = []
        self._load()

    def _load(self) -> None:
        """Parse existing MEMORY.md or create empty index."""
        if not self.index_file.exists():
            return

        content = self.index_file.read_text(encoding="utf-8")
        current_type = None

        for line in content.splitlines():
            stripped = line.strip()
            # Section header: ## type
            if stripped.startswith("## "):
                current_type = stripped[3:].strip()
                continue
            # Entry: - [name](path) -- description
            match = self._ENTRY_RE.match(stripped)
            if match and current_type:
                self.entries.append(MemoryEntry(
                    name=match.group(1),
                    file_path=match.group(2),
                    memory_type=current_type,
                    description=match.group(3) or "",
                ))

    def save(self) -> None:
        """Render and write MEMORY.md to disk."""
        lines = ["# NexusAgent Memory Index", ""]
        lines.append(
            "<!-- AUTO-GENERATED: Do not edit manually. "
            "Use memory tools to manage entries. -->"
        )
        lines.append("")

        for mem_type in self.VALID_TYPES:
            type_entries = [e for e in self.entries if e.memory_type == mem_type]
            if type_entries:
                lines.append(f"## {mem_type}")
                for entry in type_entries:
                    desc = f" -- {entry.description}" if entry.description else ""
                    lines.append(f"- [{entry.name}]({entry.file_path}){desc}")
                lines.append("")

        self.index_file.write_text("\n".join(lines), encoding="utf-8")

    def add_entry(self, entry: MemoryEntry) -> bool:
        """
        Add an entry. Returns True if added, False if duplicate updated.
        Duplicate = same name + memory_type.
        Trims oldest entries of the same type if count exceeds max_entries_per_type.
        """
        existing = self._find_entry(entry.name, entry.memory_type)
        if existing:
            existing.file_path = entry.file_path
            existing.description = entry.description
            return False
        self.entries.append(entry)
        self._enforce_limit(entry.memory_type)
        return True

    def _enforce_limit(self, memory_type: str) -> None:
        """Remove oldest entries of the given type if count exceeds max_entries_per_type."""
        type_entries = [e for e in self.entries if e.memory_type == memory_type]
        excess = len(type_entries) - self.max_entries_per_type
        if excess <= 0:
            return
        # Remove oldest entries (first in list = oldest)
        removed = 0
        for entry in list(self.entries):
            if entry.memory_type == memory_type:
                self.entries.remove(entry)
                removed += 1
                if removed >= excess:
                    break

    def update_entry(self, name: str, memory_type: str, **updates) -> bool:
        """Update an existing entry. Returns True if found and updated."""
        entry = self._find_entry(name, memory_type)
        if not entry:
            return False
        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        return True

    def remove_entry(self, name: str, memory_type: str) -> bool:
        """Remove an entry. Returns True if found and removed."""
        entry = self._find_entry(name, memory_type)
        if not entry:
            return False
        self.entries.remove(entry)
        return True

    def list_entries(self, memory_type: str | None = None) -> list[MemoryEntry]:
        """List all entries, optionally filtered by type."""
        if memory_type:
            return [e for e in self.entries if e.memory_type == memory_type]
        return list(self.entries)

    def _find_entry(self, name: str, memory_type: str) -> MemoryEntry | None:
        """Find entry by name and type."""
        for entry in self.entries:
            if entry.name == name and entry.memory_type == memory_type:
                return entry
        return None
