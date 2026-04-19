"""Tests for core tool system."""

import pytest
from pathlib import Path
import tempfile

from nexusagent.tools.builtin.read import ReadTool
from nexusagent.tools.builtin.write import WriteTool
from nexusagent.tools.builtin.glob import GlobTool
from nexusagent.tools.builtin.grep import GrepTool
from nexusagent.tools.registry import ToolRegistry


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.mark.asyncio
async def test_write_and_read(tmp_dir):
    write_tool = WriteTool(tmp_dir)
    read_tool = ReadTool(tmp_dir)

    # Write a file
    result = await write_tool.execute(file_path="test.txt", content="hello world")
    assert not result.is_error
    assert "Successfully wrote" in result.content

    # Read it back
    result = await read_tool.execute(file_path="test.txt")
    assert not result.is_error
    assert "hello world" in result.content


@pytest.mark.asyncio
async def test_write_str_replace(tmp_dir):
    write_tool = WriteTool(tmp_dir)

    await write_tool.execute(file_path="test.py", content="x = 1\ny = 2\n")

    result = await write_tool.execute(
        file_path="test.py",
        mode="str_replace",
        old_str="y = 2",
        new_str="y = 3",
    )
    assert not result.is_error

    content = (tmp_dir / "test.py").read_text()
    assert "y = 3" in content
    assert "y = 2" not in content


@pytest.mark.asyncio
async def test_glob(tmp_dir):
    # Create some files
    (tmp_dir / "a.py").write_text("")
    (tmp_dir / "b.py").write_text("")
    (tmp_dir / "c.js").write_text("")

    glob_tool = GlobTool(tmp_dir)
    result = await glob_tool.execute(pattern="**/*.py")
    assert not result.is_error
    assert "a.py" in result.content
    assert "b.py" in result.content
    assert "c.js" not in result.content


@pytest.mark.asyncio
async def test_grep(tmp_dir):
    (tmp_dir / "test.py").write_text("import os\nimport sys\n")

    grep_tool = GrepTool(tmp_dir)
    result = await grep_tool.execute(pattern="import os", path=".")
    assert not result.is_error
    assert "test.py" in result.content


@pytest.mark.asyncio
async def test_read_nonexistent(tmp_dir):
    read_tool = ReadTool(tmp_dir)
    result = await read_tool.execute(file_path="does_not_exist.txt")
    assert result.is_error
    assert "not found" in result.content.lower()


def test_tool_registry():
    registry = ToolRegistry()
    assert len(registry) == 0

    registry.register(ReadTool(Path(".")))
    assert len(registry) == 1
    assert "Read" in registry

    defs = registry.get_tool_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "Read"
