"""Tests for context management system."""

import pytest

from nexusagent.context.manager import ContextManager
from nexusagent.context.compaction import CompactionStrategy
from nexusagent.context.tokenizer import TokenCounter
from nexusagent.models import UserMessage, AssistantMessage, SystemMessage


def test_context_manager_add_message():
    cm = ContextManager(max_tokens=1000)
    cm.add_message(UserMessage(content="hello"))
    assert len(cm.messages) == 1
    assert cm.messages[0].content == "hello"
    assert cm.messages[0].token_count > 0


def test_context_manager_build_messages():
    cm = ContextManager()
    cm.add_message(UserMessage(content="hi"))
    cm.add_message(AssistantMessage(content="hello"))

    msgs = cm.build_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_context_manager_needs_compaction():
    cm = ContextManager(max_tokens=100, compact_threshold=0.75)
    # Each message: 20 chars → 5 tokens. 20 messages → 100 tokens > 75 threshold
    for i in range(20):
        cm.add_message(UserMessage(content="x" * 20))

    assert cm.needs_compaction() is True


def test_context_manager_no_compaction_when_small():
    cm = ContextManager(max_tokens=100_000)
    cm.add_message(UserMessage(content="hi"))
    assert cm.needs_compaction() is False


def test_token_counter():
    tc = TokenCounter()
    assert tc.count("") == 0
    assert tc.count("hello world") > 0
    # Rough estimate: ~1 token per 4 chars
    assert tc.count("hello world") >= 2


def test_compaction_truncate():
    strategy = CompactionStrategy("truncate_oldest")
    messages = [
        UserMessage(content=f"Message {i}") for i in range(10)
    ]
    result = strategy._truncate_summary(messages)
    assert "Compressed" in result


def test_compaction_sliding_window():
    strategy = CompactionStrategy("sliding_window")
    messages = [
        UserMessage(content=f"Message {i}") for i in range(5)
    ]
    result = strategy._sliding_window_summary(messages)
    assert "Compressed" in result


def test_context_manager_reset():
    cm = ContextManager()
    cm.add_message(UserMessage(content="test"))
    cm.reset()
    assert len(cm.messages) == 0
    assert cm.total_token_count == 0
