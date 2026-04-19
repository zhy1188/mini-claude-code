"""Tool registry: manages tool discovery and routing."""

from __future__ import annotations

from nexusagent.tools.base import Tool


class ToolRegistry:
    """所有可用工具的中央注册表"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_all(self) -> list[Tool]:
        """获取所有已注册的工具"""
        return list(self._tools.values())

    def get_tool_definitions(self) -> list[dict]:
        """获取所有工具的 LLM API JSON Schema 定义"""
        return [tool.to_llm_schema() for tool in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
