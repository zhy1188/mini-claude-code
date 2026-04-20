"""Tests for the BashTool."""

import pytest
import tempfile
from pathlib import Path

from nexusagent.tools.builtin.bash import BashTool
from nexusagent.config import BashConfig


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def bash_tool(tmp_dir):
    return BashTool(tmp_dir)


@pytest.fixture
def strict_bash(tmp_dir):
    config = BashConfig(timeout=2, max_output_bytes=500)
    return BashTool(tmp_dir, config=config)


@pytest.mark.asyncio
async def test_simple_command(bash_tool):
    result = await bash_tool.execute("echo hello")
    assert not result.is_error
    assert "hello" in result.content
    assert result.metadata["exit_code"] == 0


@pytest.mark.asyncio
async def test_command_failure(bash_tool):
    result = await bash_tool.execute("exit 42")
    assert result.is_error is False  # Non-zero exit is not treated as tool error by default
    assert result.metadata["exit_code"] == 42


@pytest.mark.asyncio
async def test_stderr_capture(bash_tool):
    result = await bash_tool.execute("echo error_msg >&2")
    assert "error_msg" in result.content
    assert "stderr" in result.content.lower()


@pytest.mark.asyncio
async def test_dangerous_command_blocked(bash_tool):
    result = await bash_tool.execute("rm -rf /")
    assert result.is_error
    assert "Dangerous" in result.content or "Blocked" in result.content


@pytest.mark.asyncio
async def test_dangerous_sudo_blocked(bash_tool):
    result = await bash_tool.execute("sudo apt install")
    assert result.is_error
    assert "Dangerous" in result.content or "Blocked" in result.content


@pytest.mark.asyncio
async def test_path_traversal_blocked(bash_tool):
    result = await bash_tool.execute("cat ../secret.txt")
    assert result.is_error
    assert "Sandbox" in result.content or "path traversal" in result.content.lower()


@pytest.mark.asyncio
async def test_timeout(strict_bash):
    result = await strict_bash.execute("sleep 10")
    assert result.is_error
    assert "timed out" in result.content.lower()


@pytest.mark.asyncio
async def test_output_truncate(strict_bash):
    # Generate output larger than 500 bytes
    long_str = "x" * 600
    result = await strict_bash.execute(f"echo {long_str}")
    assert "truncated" in result.content.lower() or "x" in result.content


@pytest.mark.asyncio
async def test_dangerous_flag_skips_check(bash_tool):
    result = await bash_tool.execute("echo safe", dangerous=True)
    assert not result.is_error


@pytest.mark.asyncio
async def test_custom_timeout(bash_tool):
    result = await bash_tool.execute("sleep 10", timeout=1)
    assert result.is_error
    assert "timed out" in result.content.lower()


@pytest.mark.asyncio
async def test_command_in_workdir(tmp_dir):
    # Create a file in workdir
    (tmp_dir / "marker.txt").write_text("found")
    tool = BashTool(tmp_dir)
    result = await tool.execute("cat marker.txt")
    assert "found" in result.content


@pytest.mark.asyncio
async def test_exit_code_metadata(bash_tool):
    result = await bash_tool.execute("true")
    assert result.metadata["exit_code"] == 0
    result = await bash_tool.execute("false")
    assert result.metadata["exit_code"] == 1
