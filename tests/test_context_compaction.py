"""Tests for context compaction strategies."""

import pytest
from nexusagent.context.manager import ContextManager
from nexusagent.context.compaction import CompactionStrategy, CompactionCache
from nexusagent.models import UserMessage, AssistantMessage, ToolResultMessage


def test_soft_compaction_removes_old_messages():
    """Phase 1: remove old non-critical text messages."""
    cm = ContextManager(max_tokens=100, compact_threshold=0.5)
    # Add many messages to trigger phase 1
    for i in range(8):
        cm.add_message(UserMessage(content=f"old message {i}"))
    cm.add_message(UserMessage(content="recent message"))

    cm._soft_compact()
    # Should have removed some old messages
    assert len(cm.messages) < 8 + 1


def test_soft_compaction_preserves_tool_results():
    """Phase 1 should not remove tool result messages."""
    cm = ContextManager(max_tokens=100, compact_threshold=0.5)
    for i in range(8):
        cm.add_message(UserMessage(content=f"old {i}"))
    cm.add_message(ToolResultMessage(content="result", tool_call_id="1", tool_name="Read"))

    cm._soft_compact()
    # Tool result message should still be there
    tool_results = [m for m in cm.messages if isinstance(m, ToolResultMessage)]
    assert len(tool_results) == 1


def test_llm_summary_compact(mock_llm_for_compaction):
    """Phase 2: LLM summarizes old messages."""

    class FakeLLM:
        async def compress_messages(self, messages):
            return "[Summary of old messages]"

    cm = ContextManager(max_tokens=100, compact_threshold=0.5)
    for i in range(15):
        cm.add_message(UserMessage(content=f"Message {i}"))

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        cm._summarize_compact(FakeLLM())
    )
    # Should have a summary message + critical messages
    assert len(cm.messages) > 0


@pytest.mark.asyncio
async def test_extreme_compact():
    """Phase 3: extreme compaction keeps only summary + last 2."""

    class FakeLLM:
        async def compress_messages(self, messages):
            return "[Extreme summary]"

    cm = ContextManager(max_tokens=100, compact_threshold=0.5)
    for i in range(20):
        cm.add_message(UserMessage(content=f"Msg {i}"))

    await cm._extreme_compact(FakeLLM())
    # Should be very short: summary + up to 2 recent
    assert len(cm.messages) <= 3


@pytest.mark.asyncio
async def test_api_calibration():
    """Calibrate token count from API response."""
    cm = ContextManager()
    cm.add_message(UserMessage(content="hello world"))
    assert cm.total_token_count > 0

    # Calibrate with API
    cm.calibrate_from_api_response({"input_tokens": 42})
    assert cm.total_token_count == 42


def test_build_messages_openai_format():
    """ToolResultMessage should become tool role in OpenAI format."""
    cm = ContextManager(provider="openai")
    cm.add_message(UserMessage(content="read file"))
    cm.add_message(ToolResultMessage(content="file contents", tool_call_id="tc1", tool_name="Read"))

    msgs = cm.build_messages()
    assert len(msgs) == 2
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["tool_call_id"] == "tc1"


def test_build_messages_anthropic_format():
    """ToolResultMessage stays as-is in Anthropic format."""
    cm = ContextManager(provider="anthropic")
    cm.add_message(UserMessage(content="read file"))
    cm.add_message(ToolResultMessage(content="file contents", tool_call_id="tc1", tool_name="Read"))

    msgs = cm.build_messages()
    assert len(msgs) == 2
    assert msgs[1]["role"] != "tool"  # Anthropic uses different format


def test_build_system_prompt_anthropic():
    """Anthropic provider should get blocks array."""
    cm = ContextManager(provider="anthropic")
    result = cm.build_system_prompt()
    assert isinstance(result, list)
    assert all("type" in b for b in result)


def test_build_system_prompt_openai():
    """OpenAI provider should get text string."""
    cm = ContextManager(provider="openai")
    result = cm.build_system_prompt()
    assert isinstance(result, str)
    assert "ROLE" in result


@pytest.fixture
def mock_llm_for_compaction():
    class FakeLLM:
        async def compress_messages(self, messages):
            return "[Summary]"
    return FakeLLM()


@pytest.mark.asyncio
async def test_compaction_strategy_llm_summary():
    cs = CompactionStrategy("llm_summary")

    class FakeLLM:
        async def compress_messages(self, messages):
            return "LLM summary here"

    messages = [UserMessage(content=f"msg {i}") for i in range(5)]
    result = await cs.compress(FakeLLM(), messages)
    assert "summary" in result.lower()


@pytest.mark.asyncio
async def test_compaction_strategy_truncate():
    cs = CompactionStrategy("truncate_oldest")
    messages = [UserMessage(content=f"msg {i}") for i in range(5)]
    result = await cs.compress(None, messages)
    assert "Compressed" in result


@pytest.mark.asyncio
async def test_compaction_strategy_sliding_window():
    cs = CompactionStrategy("sliding_window")
    messages = [
        ToolResultMessage(content=f"result {i}", tool_call_id=str(i), tool_name="Read")
        for i in range(5)
    ]
    result = await cs.compress(None, messages)
    assert "Compressed" in result
    assert "Tool" in result


def test_compaction_cache():
    """Cache should return stored summary."""
    cache = CompactionCache()
    messages = [UserMessage(content=f"msg {i}") for i in range(5)]
    cache.put(messages, "cached summary")
    assert cache.get(messages) == "cached summary"


def test_compaction_cache_eviction():
    """Cache should evict oldest entries when full."""
    cache = CompactionCache(max_entries=2)
    msgs1 = [UserMessage(content="batch1")]
    msgs2 = [UserMessage(content="batch2")]
    msgs3 = [UserMessage(content="batch3")]

    cache.put(msgs1, "summary1")
    cache.put(msgs2, "summary2")
    cache.put(msgs3, "summary3")

    # msgs1 should have been evicted
    assert cache.get(msgs1) is None
    assert cache.get(msgs3) == "summary3"


def test_is_critical_write_message():
    cs = CompactionStrategy()
    msg = ToolResultMessage(content="wrote file", tool_call_id="1", tool_name="Write")
    assert cs.is_critical(msg) is True


def test_is_critical_bash_message():
    cs = CompactionStrategy()
    msg = ToolResultMessage(content="test passed", tool_call_id="1", tool_name="Bash")
    assert cs.is_critical(msg) is True


def test_is_critical_file_reference():
    cs = CompactionStrategy()
    msg = UserMessage(content="Check the logic in app.py")
    assert cs.is_critical(msg) is True


def test_is_critical_normal_message():
    cs = CompactionStrategy()
    msg = UserMessage(content="Hello, how are you?")
    assert cs.is_critical(msg) is False
