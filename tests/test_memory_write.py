"""Tests for the MemoryWrite tool."""

import pytest
import tempfile
from pathlib import Path

from nexusagent.tools.builtin.memory_write import MemoryWriteTool


@pytest.fixture
def memory_tool():
    with tempfile.TemporaryDirectory() as d:
        nexus = Path(d) / ".nexus"
        nexus.mkdir()
        (nexus / "memory").mkdir()
        yield MemoryWriteTool(nexus)


@pytest.mark.asyncio
async def test_save_new_memory(memory_tool):
    result = await memory_tool.execute(
        operation="save", name="test_pref", memory_type="user", content="prefers dark mode"
    )
    assert not result.is_error
    assert "saved" in result.content.lower()


@pytest.mark.asyncio
async def test_save_existing_memory_updates(memory_tool):
    await memory_tool.execute(
        operation="save", name="test", memory_type="user", content="original"
    )
    result = await memory_tool.execute(
        operation="save", name="test", memory_type="user", content="updated"
    )
    assert not result.is_error
    assert "updated" in result.content.lower()


@pytest.mark.asyncio
async def test_update_existing_memory(memory_tool):
    await memory_tool.execute(
        operation="save", name="test", memory_type="feedback", content="original"
    )
    result = await memory_tool.execute(
        operation="update", name="test", memory_type="feedback", content="revised content",
        description="updated desc"
    )
    assert not result.is_error


@pytest.mark.asyncio
async def test_update_nonexistent_memory(memory_tool):
    result = await memory_tool.execute(
        operation="update", name="nope", memory_type="user", content="whatever"
    )
    assert result.is_error
    assert "not found" in result.content.lower()


@pytest.mark.asyncio
async def test_forget_memory(memory_tool):
    await memory_tool.execute(
        operation="save", name="temp", memory_type="project", content="temporary"
    )
    result = await memory_tool.execute(
        operation="forget", name="temp", memory_type="project"
    )
    assert not result.is_error
    assert "forgotten" in result.content.lower()


@pytest.mark.asyncio
async def test_forget_standard_file_clears_not_deletes(memory_tool):
    await memory_tool.execute(
        operation="save", name="temp_note", memory_type="user", content="note"
    )
    await memory_tool.execute(
        operation="forget", name="temp_note", memory_type="user"
    )
    # Standard file should still exist but be cleared
    assert (memory_tool.memory_dir / "user.md").exists()


@pytest.mark.asyncio
async def test_list_all_memories(memory_tool):
    await memory_tool.execute(
        operation="save", name="mem1", memory_type="user", content="user mem"
    )
    await memory_tool.execute(
        operation="save", name="mem2", memory_type="feedback", content="feedback mem"
    )
    result = await memory_tool.execute(operation="list")
    assert not result.is_error
    assert "mem1" in result.content
    assert "mem2" in result.content


@pytest.mark.asyncio
async def test_list_by_type(memory_tool):
    await memory_tool.execute(
        operation="save", name="u1", memory_type="user", content="user"
    )
    await memory_tool.execute(
        operation="save", name="f1", memory_type="feedback", content="feedback"
    )
    result = await memory_tool.execute(operation="list", memory_type="user")
    assert "u1" in result.content
    assert "f1" not in result.content


@pytest.mark.asyncio
async def test_save_missing_name(memory_tool):
    result = await memory_tool.execute(
        operation="save", memory_type="user", content="no name"
    )
    assert result.is_error
    assert "name" in result.content.lower()


@pytest.mark.asyncio
async def test_save_missing_type(memory_tool):
    result = await memory_tool.execute(
        operation="save", name="test", content="no type"
    )
    assert result.is_error
    assert "memory_type" in result.content.lower() or "type" in result.content.lower()


@pytest.mark.asyncio
async def test_save_invalid_type(memory_tool):
    result = await memory_tool.execute(
        operation="save", name="test", memory_type="invalid_type", content="bad type"
    )
    assert result.is_error
    assert "invalid" in result.content.lower()


@pytest.mark.asyncio
async def test_save_content_too_long(memory_tool):
    long_content = "x" * 10001
    result = await memory_tool.execute(
        operation="save", name="long", memory_type="user", content=long_content
    )
    assert result.is_error
    assert "too long" in result.content.lower()


@pytest.mark.asyncio
async def test_unknown_operation(memory_tool):
    result = await memory_tool.execute(operation="unknown")
    assert result.is_error
    assert "unknown" in result.content.lower()
