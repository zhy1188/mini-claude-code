"""Lightweight YAML frontmatter parser (no external dependencies)."""

from __future__ import annotations

import re


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter from text.

    Returns:
        (metadata_dict, body_string)
    """
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, text, re.DOTALL)
    if not match:
        return {}, text.strip()

    raw_meta = match.group(1)
    body = match.group(2).strip()

    metadata = {}
    for line in raw_meta.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip("\"'")
            metadata[key] = value

    return metadata, body


def format_frontmatter(metadata: dict, content: str) -> str:
    """
    Format metadata and content into frontmatter string.

    Args:
        metadata: Key-value pairs for YAML frontmatter
        content: Body text content
    """
    lines = ["---"]
    for key, value in metadata.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)
