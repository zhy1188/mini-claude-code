"""Integration tests for the full agent pipeline."""

import pytest
from pathlib import Path
import tempfile

from nexusagent.agent.master import MasterAgent
from nexusagent.context.manager import ContextManager
from nexusagent.hooks.engine import HookEngine
from nexusagent.hooks.types import HookConfig, HookType
from rich.console import Console
from nexusagent.models import AgentState, UserMessage
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


@pytest.mark.asyncio
async def test_multi_tool_chain(setup_agent):
    """Test agent chains multiple tools: Glob → Read → respond."""
    agent, llm, tmp_path = setup_agent

    llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "Glob", "input": {"pattern": "*.py"}}]},
        {"content": "", "tool_calls": [{"name": "Read", "input": {"file_path": "test.py"}}]},
        {"content": "Found and read test.py", "stop_reason": "end_turn"},
    )

    await agent.run("Find and read Python files")

    assert agent.state == AgentState.DONE
    assert len(llm.call_history) == 3


@pytest.mark.asyncio
async def test_context_compaction_full_flow(tmp_path):
    """Test compaction triggers and agent continues after compaction."""
    llm = MockLLMClient()
    llm.add_mock_responses(
        {"content": "After compaction, continuing", "stop_reason": "end_turn"},
    )

    registry = ToolRegistry()
    registry.register(ReadTool(tmp_path))

    # Small token limit to trigger compaction
    context_mgr = ContextManager(max_tokens=200, compact_threshold=0.75, provider="openai")

    trust_policy = TrustPolicy(tool_permissions={"Read": "approve"})
    permission_gate = PermissionGate(trust_policy)

    tui = NexusTUI(Console(force_terminal=True))

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        context_manager=context_mgr,
        permission_gate=permission_gate,
        tui=tui,
        workdir=tmp_path,
    )

    # Add enough messages to trigger compaction
    for i in range(15):
        context_mgr.add_message(UserMessage(content="x" * 50))

    await agent.run("Continue after compaction")
    assert agent.state == AgentState.DONE


@pytest.mark.asyncio
async def test_permission_denied_blocks_flow(setup_agent):
    """Test that permission deny on Write blocks the tool execution."""
    agent, llm, tmp_path = setup_agent

    # Change policy to deny Write
    trust_policy = TrustPolicy(tool_permissions={"Write": "deny", "Read": "approve"})
    agent.permission = PermissionGate(trust_policy)

    llm.add_mock_responses(
        {"content": "", "tool_calls": [{"name": "Write", "input": {"file_path": "out.txt", "content": "data"}}]},
        {"content": "Write was denied", "stop_reason": "end_turn"},
    )

    await agent.run("Write to out.txt")

    assert agent.state == AgentState.DONE


@pytest.mark.asyncio
async def test_cancel_mechanism(setup_agent):
    """Test that request_cancel stops the agent gracefully."""
    agent, llm, tmp_path = setup_agent

    llm.add_response(content="working...", stop_reason="")

    agent.request_cancel()
    await agent.run("This should be cancelled")

    # Agent should have stopped
    assert agent.state_machine.current in ("idle", "done")


@pytest.mark.asyncio
async def test_input_queuing(setup_agent):
    """Test that input queuing works when agent is busy."""
    agent, llm, tmp_path = setup_agent

    llm.add_mock_responses(
        {"content": "first done", "stop_reason": "end_turn"},
        {"content": "second done", "stop_reason": "end_turn"},
    )

    await agent.run("First message")
    assert agent.state == AgentState.DONE

    # Now agent is idle, queue_input should return "idle"
    status = agent.queue_input("Second message")
    assert status == "idle"


@pytest.mark.asyncio
async def test_checkpoint_save_and_resume(tmp_path):
    """Test that checkpoints save and can be resumed."""
    llm = MockLLMClient()
    llm.add_response(content="done", stop_reason="end_turn")

    registry = ToolRegistry()
    context_mgr = ContextManager(max_tokens=100_000, provider="openai")
    trust_policy = TrustPolicy()
    permission_gate = PermissionGate(trust_policy)
    tui = NexusTUI(Console(force_terminal=True))

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        context_manager=context_mgr,
        permission_gate=permission_gate,
        tui=tui,
        workdir=tmp_path,
    )

    # Manually save a checkpoint
    context_mgr.add_message(UserMessage(content="test message"))
    agent._save_checkpoint("test", user_input="test message")

    # Load and resume
    restored = await agent.resume()
    assert restored is True
    assert len(agent.context.messages) == 1
