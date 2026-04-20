"""Tests for SubAgent."""

import pytest
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from mock_llm import MockLLMClient

from nexusagent.agent.sub_agent import SubAgent
from nexusagent.tools.builtin.read import ReadTool
from nexusagent.tools.builtin.write import WriteTool


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.mark.asyncio
async def test_simple_text_response(tmp_dir, mock_llm):
    mock_llm.add_response(content="Task completed successfully", stop_reason="end_turn")

    agent = SubAgent(
        task="Do something",
        tools=[],
        llm=mock_llm,
    )
    result = await agent.run()

    assert result.status == "success"
    assert "completed" in result.summary.lower()


@pytest.mark.asyncio
async def test_tool_call(tmp_dir, mock_llm):
    (tmp_dir / "test.txt").write_text("hello")

    mock_llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "Read", "input": {"file_path": "test.txt"}}]},
        {"content": "Done", "stop_reason": "end_turn"},
    )

    agent = SubAgent(
        task="Read the file",
        tools=[ReadTool(tmp_dir)],
        llm=mock_llm,
        max_tokens=50_000,
    )
    result = await agent.run()

    assert result.status == "success"
    assert result.tool_calls_made >= 1


@pytest.mark.asyncio
async def test_write_artifact_tracking(tmp_dir, mock_llm):
    mock_llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "Write", "input": {"file_path": "output.txt", "content": "data"}}]},
        {"content": "Wrote file", "stop_reason": "end_turn"},
    )

    agent = SubAgent(
        task="Write a file",
        tools=[WriteTool(tmp_dir)],
        llm=mock_llm,
    )
    result = await agent.run()

    assert result.status == "success"
    assert "output.txt" in result.artifacts


@pytest.mark.asyncio
async def test_exceed_max_iterations(tmp_dir, mock_llm):
    # Keep returning tool calls so agent loops forever
    # MockLLM falls back to default response when responses run out,
    # so we need to add enough responses to fill all iterations
    mock_llm.add_response(
        content="",
        tool_calls=[{"name": "Read", "input": {"file_path": "test.txt"}}],
    )
    mock_llm.add_response(
        content="",
        tool_calls=[{"name": "Read", "input": {"file_path": "test.txt"}}],
    )
    mock_llm.add_response(
        content="",
        tool_calls=[{"name": "Read", "input": {"file_path": "test.txt"}}],
    )
    mock_llm.add_response(
        content="",
        tool_calls=[{"name": "Read", "input": {"file_path": "test.txt"}}],
    )

    agent = SubAgent(
        task="Loop test",
        tools=[ReadTool(tmp_dir)],
        llm=mock_llm,
        max_iterations=3,
    )
    result = await agent.run()

    assert result.status == "error"
    assert "exceeded" in result.summary.lower()


@pytest.mark.asyncio
async def test_unknown_tool(tmp_dir, mock_llm):
    mock_llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "NonExistent", "input": {}}]},
        {"content": "Done", "stop_reason": "end_turn"},
    )

    agent = SubAgent(
        task="Use bad tool",
        tools=[],
        llm=mock_llm,
    )
    result = await agent.run()

    # Should still complete (unknown tool returns error but doesn't crash)
    assert "NonExistent" in result.summary or result.status == "success"


@pytest.mark.asyncio
async def test_token_usage_tracking(tmp_dir, mock_llm):
    # MockLLM only includes usage in tool_call responses, not content-only
    # So token_usage from a pure text response is 0
    mock_llm.add_mock_responses(
        {"content": "hello", "tool_calls": [], "stop_reason": "end_turn"},
    )

    agent = SubAgent(
        task="Track tokens",
        tools=[],
        llm=mock_llm,
    )
    result = await agent.run()

    # Text-only response has no usage data from MockLLM
    assert result.status == "success"
    assert result.token_usage == 0


@pytest.mark.asyncio
async def test_system_prompt_custom(tmp_dir, mock_llm):
    mock_llm.add_response(content="responded", stop_reason="end_turn")

    agent = SubAgent(
        task="test",
        tools=[],
        llm=mock_llm,
        system_prompt="Custom system prompt",
    )
    result = await agent.run()
    assert result.status == "success"
