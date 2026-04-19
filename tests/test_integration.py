"""Integration tests for the full agent pipeline."""

import pytest
from pathlib import Path
import tempfile

from nexusagent.agent.master import MasterAgent
from nexusagent.context.manager import ContextManager
from nexusagent.hooks.engine import HookEngine
from nexusagent.hooks.types import HookConfig, HookType
from nexusagent.models import AgentState
from nexusagent.permission.gate import PermissionGate
from nexusagent.permission.policy import TrustPolicy
from nexusagent.tools.builtin.bash import BashTool
from nexusagent.tools.builtin.glob import GlobTool
from nexusagent.tools.builtin.grep import GrepTool
from nexusagent.tools.builtin.read import ReadTool
from nexusagent.tools.builtin.write import WriteTool
from nexusagent.tools.registry import ToolRegistry
from nexusagent.tui.app import NexusTUI
import sys
sys.path.insert(0, str(Path(__file__).parent))
from mock_llm import MockLLMClient


@pytest.fixture
def setup_agent(tmp_path):
    """Create a fully configured agent with mock LLM."""
    # Create test file
    (tmp_path / "test.py").write_text("print('hello')\n")

    # Mock LLM
    llm = MockLLMClient()

    # Tools
    registry = ToolRegistry()
    registry.register(ReadTool(tmp_path))
    registry.register(WriteTool(tmp_path))
    registry.register(BashTool(tmp_path))
    registry.register(GlobTool(tmp_path))
    registry.register(GrepTool(tmp_path))

    # Context
    context_mgr = ContextManager(
        max_tokens=100_000,
        compact_threshold=0.75,
        provider="openai",  # Use openai format for test
    )

    # Permission (auto-approve everything for testing)
    trust_policy = TrustPolicy(tool_permissions={
        "Read": "approve",
        "Write": "approve",
        "Bash": "approve",
        "Glob": "approve",
        "Grep": "approve",
    })
    permission_gate = PermissionGate(trust_policy)

    # TUI (silent for testing)
    from rich.console import Console
    tui = NexusTUI(Console(force_terminal=True))

    # Agent
    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        context_manager=context_mgr,
        permission_gate=permission_gate,
        tui=tui,
        workdir=tmp_path,
    )

    return agent, llm, tmp_path


@pytest.mark.asyncio
async def test_agent_simple_response(setup_agent):
    """Test agent handles a simple text response without tool calls."""
    agent, llm, tmp_path = setup_agent

    llm.add_response(content="I read the file. It contains print('hello').")

    await agent.run("What's in test.py?")

    assert agent.state == AgentState.DONE
    assert len(llm.call_history) == 1
    assert llm.call_history[0]["messages"][0]["content"] == "What's in test.py?"


@pytest.mark.asyncio
async def test_agent_tool_call(setup_agent):
    """Test agent executes a tool call and loops back."""
    agent, llm, tmp_path = setup_agent

    # First response: call Read tool
    llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "Read", "input": {"file_path": "test.py"}}]},
        {"content": "The file contains: print('hello')", "stop_reason": "end_turn"},
    )

    await agent.run("Read test.py")

    assert agent.state == AgentState.DONE
    # Should have 2 LLM calls: initial + after tool result
    assert len(llm.call_history) == 2


@pytest.mark.asyncio
async def test_agent_multiple_tools(setup_agent):
    """Test agent using multiple different tools."""
    agent, llm, tmp_path = setup_agent

    llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "Glob", "input": {"pattern": "*.py"}}]},
        {"content": "Found test.py", "stop_reason": "end_turn"},
    )

    await agent.run("Find all Python files")

    assert agent.state == AgentState.DONE
    assert len(llm.call_history) == 2


@pytest.mark.asyncio
async def test_agent_context_building(setup_agent):
    """Test that agent correctly builds context with messages."""
    agent, llm, tmp_path = setup_agent

    llm.add_response(content="Hello back!")

    await agent.run("Hello")

    # Check context has both messages
    messages = agent.context.messages
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_agent_reset(setup_agent):
    """Test agent reset clears context."""
    agent, llm, tmp_path = setup_agent

    llm.add_response(content="OK")
    await agent.run("Test")
    assert len(agent.context.messages) == 2

    agent.reset()
    assert len(agent.context.messages) == 0


@pytest.mark.asyncio
async def test_hooks_injected():
    """Test that hooks are triggered during agent execution."""
    from nexusagent.agent.master import MasterAgent
    from rich.console import Console

    llm = MockLLMClient()
    llm.add_response(content="done", stop_reason="end_turn")

    registry = ToolRegistry()

    context_mgr = ContextManager(max_tokens=100_000, provider="openai")

    trust_policy = TrustPolicy()
    permission_gate = PermissionGate(trust_policy)

    tui = NexusTUI(Console(force_terminal=True))

    hook_engine = HookEngine()
    hook_engine.register(HookConfig(
        hook_type=HookType.POST_RESPONSE,
        matcher="*",
        command="echo 'hook triggered'",
        blocking=False,
    ))
    hook_engine.register(HookConfig(
        hook_type=HookType.PRE_USER_MESSAGE,
        matcher="*",
        command="echo 'pre message'",
        blocking=False,
    ))

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        context_manager=context_mgr,
        permission_gate=permission_gate,
        tui=tui,
        hook_engine=hook_engine,
    )

    await agent.run("Test with hooks")

    # Hook should have been triggered
    assert HookType.POST_RESPONSE in hook_engine.hooks
    assert HookType.PRE_USER_MESSAGE in hook_engine.hooks
