"""Project context loader: .nexus.md files (like CLAUDE.md)."""

from __future__ import annotations

from pathlib import Path

# Sentinel file that tells NexusAgent a project context exists.
CONTEXT_FILE = ".nexus.md"


def load_project_context(workdir: Path) -> str:
    """
    Load .nexus.md from the project root.
    Similar to CLAUDE.md in Claude Code.

    The content is automatically prepended to the system prompt
    and is never removed during context compaction.
    """
    nexus_md = workdir / CONTEXT_FILE
    if nexus_md.exists():
        return nexus_md.read_text(encoding="utf-8")
    return ""


def load_hierarchy_context(workdir: Path, current_dir: Path) -> str:
    """
    Walk up from current_dir to workdir, loading .nexus.md files.
    Files closer to the current directory take precedence (appended last).

    This allows subdirectories to have their own context instructions.
    e.g.:
        /project/.nexus.md          — project-wide rules
        /project/src/.nexus.md      — src-specific rules
    """
    parts = []
    # Collect all .nexus.md files from workdir down to current_dir
    path = current_dir
    chain = []
    while path != workdir:
        ctx = path / CONTEXT_FILE
        if ctx.exists():
            chain.append(ctx)
        path = path.parent
    # Also include workdir's own file
    root_ctx = workdir / CONTEXT_FILE
    if root_ctx.exists():
        chain.append(root_ctx)

    # Reverse so root is first, deepest subdir is last
    for ctx in reversed(chain):
        parts.append(f"## Context from `{ctx.relative_to(workdir)}`\n{ctx.read_text(encoding='utf-8')}")

    return "\n\n".join(parts)
