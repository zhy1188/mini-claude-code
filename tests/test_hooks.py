"""Tests for the HookEngine."""

import pytest
import tempfile
import os
import sys
from pathlib import Path

from nexusagent.hooks.engine import HookEngine, HookResult
from nexusagent.hooks.types import HookConfig, HookType


@pytest.fixture
def engine():
    return HookEngine()


@pytest.mark.asyncio
async def test_register_and_trigger(engine):
    marker = Path(tempfile.gettempdir()) / "hook_test_marker.txt"
    if marker.exists():
        marker.unlink()

    engine.register(HookConfig(
        hook_type=HookType.POST_RESPONSE,
        matcher="*",
        command=f"echo done > {marker}",
        blocking=True,
    ))

    await engine.trigger(HookType.POST_RESPONSE, {})
    assert marker.exists()
    marker.unlink()


@pytest.mark.asyncio
async def test_wildcard_matcher(engine):
    engine.register(HookConfig(
        hook_type=HookType.PRE_TOOL_USE,
        matcher="*",
        command="echo wildcard",
        blocking=False,
    ))
    result = await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Read"})
    assert not result.blocked


@pytest.mark.asyncio
async def test_exact_matcher(engine):
    engine.register(HookConfig(
        hook_type=HookType.PRE_TOOL_USE,
        matcher="Bash",
        command="echo exact",
        blocking=False,
    ))
    # Should match
    result = await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Bash"})
    assert not result.blocked
    # Should not match different tool
    result = await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Read"})
    assert not result.blocked  # No hooks match, so not blocked


@pytest.mark.asyncio
async def test_blocking_hook_failure(engine):
    engine.register(HookConfig(
        hook_type=HookType.PRE_TOOL_USE,
        matcher="*",
        command="exit 1",
        blocking=True,
    ))
    result = await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Bash"})
    assert result.blocked


@pytest.mark.asyncio
async def test_non_blocking_hook(engine):
    engine.register(HookConfig(
        hook_type=HookType.POST_RESPONSE,
        matcher="*",
        command="sleep 1",
        blocking=False,
    ))
    result = await engine.trigger(HookType.POST_RESPONSE, {})
    assert not result.blocked


@pytest.mark.asyncio
async def test_variable_interpolation(engine):
    marker = Path(tempfile.gettempdir()) / "hook_interp.txt"
    if marker.exists():
        marker.unlink()

    engine.register(HookConfig(
        hook_type=HookType.PRE_TOOL_USE,
        matcher="*",
        command=f"echo $tool_name > {marker}",
        blocking=True,
    ))

    await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Bash"})
    assert marker.exists()
    content = marker.read_text().strip()
    assert "Bash" in content
    marker.unlink()


@pytest.mark.asyncio
async def test_multiple_hooks_same_type(engine):
    marker = Path(tempfile.gettempdir()) / "hook_multi.txt"
    if marker.exists():
        marker.unlink()

    engine.register(HookConfig(
        hook_type=HookType.POST_RESPONSE,
        matcher="*",
        command=f"echo first >> {marker}",
        blocking=True,
    ))
    engine.register(HookConfig(
        hook_type=HookType.POST_RESPONSE,
        matcher="*",
        command=f"echo second >> {marker}",
        blocking=True,
    ))

    await engine.trigger(HookType.POST_RESPONSE, {})
    content = marker.read_text()
    assert "first" in content
    assert "second" in content
    marker.unlink()


@pytest.mark.asyncio
async def test_no_matching_hook(engine):
    engine.register(HookConfig(
        hook_type=HookType.PRE_TOOL_USE,
        matcher="Bash",
        command="echo bash_only",
        blocking=True,
    ))
    result = await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Read"})
    assert not result.blocked


@pytest.mark.asyncio
async def test_hook_execution_error(engine):
    engine.register(HookConfig(
        hook_type=HookType.PRE_TOOL_USE,
        matcher="*",
        command="nonexistent_command_that_fails_xyz",
        blocking=True,
    ))
    result = await engine.trigger(HookType.PRE_TOOL_USE, {"tool_name": "Bash"})
    # Should be blocked due to execution error
    assert result.blocked
