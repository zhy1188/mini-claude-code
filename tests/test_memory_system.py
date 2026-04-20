"""Tests for the cross-session MemorySystem."""

import pytest
import tempfile
from pathlib import Path

from nexusagent.memory.memory import MemorySystem


@pytest.fixture
def memory_system():
    with tempfile.TemporaryDirectory() as d:
        mem_dir = Path(d) / ".nexus" / "memory"
        yield MemorySystem(memory_dir=mem_dir)


def test_init_creates_default_files(memory_system):
    for name in MemorySystem.MEMORY_TYPES:
        path = memory_system.memory_dir / f"{name}.md"
        assert path.exists()


def test_load_all_empty(memory_system):
    result = memory_system.load_all()
    # Default files have headers like "# User Memory"
    assert "User" in result or result == ""


def test_save_and_load(memory_system):
    memory_system.save("user_note", "This is a test note", "A test memory")
    # save uses name for filename: {name}.md
    content = memory_system.get("user_note")
    assert "This is a test note" in content


def test_save_updates_index(memory_system):
    memory_system.save("indexed_note", "Content here", "Indexed memory")
    entries = memory_system.index.list_entries("user")
    assert any(e.name == "indexed_note" for e in entries)


def test_append_to_memory(memory_system):
    memory_system.save("append_test", "First line", "append test")
    memory_system.append("append_test", "\nSecond line")
    content = memory_system.get("append_test")
    assert "First line" in content
    assert "Second line" in content


def test_build_system_prompt_section(memory_system):
    # load_all only reads standard type files (user.md, feedback.md, etc.)
    # Write directly to a standard type file
    user_file = memory_system.memory_dir / "user.md"
    user_file.write_text("System memory content", encoding="utf-8")
    section = memory_system.build_system_prompt_section()
    assert "Cross-Session Memory" in section
    assert "System memory content" in section


def test_get_nonexistent_memory(memory_system):
    content = memory_system.get("nonexistent_type")
    assert content == ""


def test_load_all_merges_all_types(memory_system):
    # Write to standard type files directly (load_all reads these)
    (memory_system.memory_dir / "user.md").write_text("User content", encoding="utf-8")
    (memory_system.memory_dir / "feedback.md").write_text("Feedback content", encoding="utf-8")
    result = memory_system.load_all()
    assert "User content" in result
    assert "Feedback content" in result
