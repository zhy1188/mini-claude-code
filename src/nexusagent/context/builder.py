"""Structured system prompt builder with section management and caching support."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptSection:
    """系统提示的一个片段"""
    name: str
    content: str
    cacheable: bool = True  # 该片段是否可以缓存（很少变化的部分）
    enabled: bool = True    # 是否包含该片段

    def build(self) -> dict:
        """构建 LLM API 格式的内容块"""
        return {
            "type": "text",
            "text": self.content,
            "cache_control": {"type": "ephemeral"} if self.cacheable else None,
        }


class PromptBuilder:
    """
    用可组合的片段构建结构化系统提示。

    替代旧的字符串拼接方式，使用显式片段，
    每个片段有自己的缓存策略。这使得 Anthropic 提示缓存
    能大幅降低多轮对话的成本和延迟。

    片段顺序（锁定）:
        1. ROLE       - Agent 身份和能力（始终缓存）
        2. RULES      - 行为规则（始终缓存）
        3. PROJECT    - 来自 .nexus.md 的项目上下文（缓存）
        4. MEMORY     - 跨会话记忆（缓存）
        5. SKILLS     - 可用技能列表（缓存）
    """

    SECTION_ORDER = ["role", "rules", "project", "memory", "skills"]

    def __init__(self):
        self._sections: dict[str, PromptSection] = {}
        self._init_default_sections()

    def _init_default_sections(self):
        """创建默认角色和规则片段"""
        self.add_section(
            "role",
            (
                "你是 NexusAgent，一个运行在终端环境中的 AI 编程助手。\n"
                "你通过读取文件、搜索代码、执行命令和修改文件来帮助用户完成任务。\n"
                "你有丰富的工具集，可以派生子 Agent 并行处理独立任务。"
            ),
        )
        self.add_section(
            "rules",
            (
                "工作方式：\n"
                "- 先读文件再修改，确保理解上下文\n"
                "- 使用 Bash 工具验证代码（运行测试等）\n"
                "- 不确定时先询问用户\n"
                "- 修改代码时保持原有风格\n"
                "- 优先修复问题而非重构无关代码"
            ),
        )

    def add_section(self, name: str, content: str, cacheable: bool = True) -> None:
        """添加或更新一个提示片段"""
        self._sections[name] = PromptSection(
            name=name,
            content=content,
            cacheable=cacheable,
        )

    def update_section(self, name: str, content: str) -> bool:
        """更新提示片段，不存在则创建"""
        if name in self._sections:
            self._sections[name].content = content
            return True
        # 自动创建未知片段
        self._sections[name] = PromptSection(
            name=name,
            content=content,
            cacheable=True,
        )
        return False

    def set_enabled(self, name: str, enabled: bool) -> None:
        """启用或禁用一个片段"""
        if name in self._sections:
            self._sections[name].enabled = enabled

    def get_section(self, name: str) -> str | None:
        """获取片段的原始内容"""
        section = self._sections.get(name)
        if section:
            return section.content
        return None

    def build(self) -> list[dict]:
        """
        构建完整的系统提示，返回内容块列表。

        按锁定顺序返回启用的片段，跳过禁用的。
        每个块包含 Anthropic API 的 cache_control 元数据。
        同时返回扁平化字符串作为非 Anthropic 提供商的备选方案。
        """
        blocks = []
        parts = []

        for name in self.SECTION_ORDER:
            section = self._sections.get(name)
            if not section or not section.enabled:
                continue
            if not section.content.strip():
                continue

            blocks.append(section.build())
            parts.append(f"## {name.upper()}\n\n{section.content}")

        # 同时返回两种格式：blocks 给 Anthropic，string 给其他提供商
        return {
            "blocks": blocks,
            "text": "\n\n".join(parts),
        }

    def get_cacheable_token_count(self, tokenizer) -> int:
        """估算可缓存片段的 token 数量"""
        total = 0
        for section in self._sections.values():
            if section.cacheable and section.enabled and section.content:
                total += tokenizer.count(section.content)
        return total
