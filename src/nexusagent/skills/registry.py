"""Skill registry: discovers and loads skill files from configured directories."""

from __future__ import annotations

from pathlib import Path

from nexusagent.skills.models import Skill


class SkillRegistry:
    """
    Skill discovery and management.

    - Scans configured directories on init/reload
    - Maintains name -> Skill index
    - Project-level skills override global ones with the same name
    """

    def __init__(self):
        self.skills: dict[str, Skill] = {}
        self.directories: list[tuple[Path, str]] = []

    def add_directory(self, path: Path, scope: str = "project") -> None:
        """Register a skill search directory.

        'scope' determines priority — project skills override global ones.
        """
        self.directories.append((path, scope))

    def scan(self) -> None:
        """Scan all registered directories, loading .md files as skills."""
        self.skills.clear()
        # Project-level directories processed last so they override global
        for directory, scope in sorted(self.directories, key=lambda x: x[1]):
            if not directory.exists():
                continue
            for md_file in directory.glob("*.md"):
                try:
                    skill = Skill.from_file(md_file, scope=scope)
                    self.skills[skill.name] = skill
                except Exception as e:
                    print(f"Warning: Failed to load skill from {md_file}: {e}")

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self.skills.get(name)

    def list_skills(self) -> list[Skill]:
        """List all loaded skills."""
        return list(self.skills.values())

    def reload(self) -> None:
        """Hot-reload: re-scan all directories."""
        self.scan()
