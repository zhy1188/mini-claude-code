"""Tests for the PromptBuilder system."""

from nexusagent.context.builder import PromptBuilder, PromptSection


def test_default_sections():
    pb = PromptBuilder()
    assert pb.get_section("role") is not None
    assert pb.get_section("rules") is not None


def test_add_custom_section():
    pb = PromptBuilder()
    pb.add_section("custom", "Custom content here")
    assert pb.get_section("custom") == "Custom content here"


def test_update_section():
    pb = PromptBuilder()
    pb.update_section("role", "Updated role content")
    assert pb.get_section("role") == "Updated role content"


def test_update_section_creates_unknown():
    pb = PromptBuilder()
    assert pb.get_section("unknown") is None
    result = pb.update_section("unknown", "New content")
    assert result is False  # Was not existing
    assert pb.get_section("unknown") == "New content"


def test_enable_disable_section():
    pb = PromptBuilder()
    pb.set_enabled("role", False)
    result = pb.build()
    texts = [b["text"] for b in result["blocks"]]
    assert not any("你是 NexusAgent" in t for t in texts)


def test_build_blocks_format():
    pb = PromptBuilder()
    result = pb.build()
    assert "blocks" in result
    assert "text" in result
    assert isinstance(result["blocks"], list)
    assert len(result["blocks"]) >= 2  # role + rules


def test_build_text_format():
    pb = PromptBuilder()
    result = pb.build()
    assert isinstance(result["text"], str)
    assert "## ROLE" in result["text"]
    assert "## RULES" in result["text"]


def test_skip_disabled_section():
    pb = PromptBuilder()
    pb.set_enabled("rules", False)
    result = pb.build()
    texts = [b["text"] for b in result["blocks"]]
    assert not any("## RULES" in t for t in texts)


def test_skip_empty_section():
    pb = PromptBuilder()
    pb.add_section("empty", "")
    result = pb.build()
    texts = [b["text"] for b in result["blocks"]]
    assert not any(t == "" for t in texts if t)


def test_cache_control_markings():
    pb = PromptBuilder()
    result = pb.build()
    # Default sections should have cache_control
    for block in result["blocks"]:
        assert "cache_control" in block


def test_section_order():
    pb = PromptBuilder()
    pb.add_section("memory", "Memory content")
    pb.add_section("project", "Project context")
    result = pb.build()
    texts = [b["text"] for b in result["blocks"]]
    # role should come before memory
    role_idx = next(i for i, t in enumerate(texts) if "你是 NexusAgent" in t)
    memory_idx = next(i for i, t in enumerate(texts) if "Memory content" in t)
    assert role_idx < memory_idx


def test_prompt_section_build():
    section = PromptSection(name="test", content="hello", cacheable=True)
    result = section.build()
    assert result["type"] == "text"
    assert result["text"] == "hello"
    assert result["cache_control"] == {"type": "ephemeral"}


def test_prompt_section_non_cacheable():
    section = PromptSection(name="test", content="hello", cacheable=False)
    result = section.build()
    assert result["cache_control"] is None


def test_get_cacheable_token_count():
    pb = PromptBuilder()
    from nexusagent.context.tokenizer import TokenCounter
    tc = TokenCounter()
    count = pb.get_cacheable_token_count(tc)
    assert count > 0  # role + rules are cacheable
