"""Skill data model and Markdown file parser."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Skill(BaseModel):
    """A single skill loaded from a Markdown file."""

    name: str
    description: str = ""
    version: str = "1.0"
    content: str
    source: str = ""
    scope: str = "project"

    @classmethod
    def from_file(cls, path: Path, scope: str = "project") -> "Skill":
        """Parse a Markdown file, separating frontmatter and body."""
        content = path.read_text(encoding="utf-8")
        name = path.stem
        description = ""
        version = "1.0"

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1].strip()
                body = parts[2].strip()

                for line in frontmatter.splitlines():
                    if ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip().lower()
                        val = val.strip().strip('"').strip("'")
                        if key == "description":
                            description = val
                        elif key == "version":
                            version = val

                content = body
            else:
                content = content.strip()
        else:
            content = content.strip()

        return cls(
            name=name,
            description=description,
            version=version,
            content=content,
            source=str(path),
            scope=scope,
        )
