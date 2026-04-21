"""MCP Wrapped Tool: adapts a remote MCP tool to the local Tool interface."""

from __future__ import annotations

import asyncio

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool
from nexusagent.tools.mcp.transport import MCPTransport


class MCPWrappedTool(Tool):
    """
    包装远程 MCP 服务器暴露的工具。
    将 MCP 工具定义转换为本地 Tool 格式，通过 transport 执行。
    """

    _EXEC_TIMEOUT = 30  # MCP 工具执行超时（秒）

    def __init__(self, transport: MCPTransport, server_name: str, tool_def: dict, on_active_change=None):
        self.transport = transport
        self.server_name = server_name
        self._tool_def = tool_def
        self._on_active_change = on_active_change  # callback(name, delta) for ref counting

        # 从 MCP 定义中获取名称和描述
        self.name = f"mcp__{server_name}__{tool_def['name']}"
        self.description = tool_def.get("description", "")

        # 将 JSON Schema input 转换为我们的参数格式
        input_schema = tool_def.get("inputSchema", {})
        properties = input_schema.get("properties", {})
        required_fields = set(input_schema.get("required", []))

        self.parameters = {}
        for prop_name, prop_spec in properties.items():
            self.parameters[prop_name] = {
                "type": prop_spec.get("type", "string"),
                "description": prop_spec.get("description", ""),
                "required": prop_name in required_fields,
            }

    async def execute(self, **kwargs) -> ToolResult:
        """通过 transport 执行远程 MCP 工具"""
        if self._on_active_change:
            self._on_active_change(self.server_name, +1)
        try:
            result = await asyncio.wait_for(
                self._call(kwargs), timeout=self._EXEC_TIMEOUT
            )

            content = result.get("content", [])
            # MCP content 可以是 text 或 image
            text_parts = []
            for item in content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    text_parts.append("[image data]")

            return ToolResult(content="\n".join(text_parts))

        except asyncio.TimeoutError:
            return ToolResult(content=f"MCP tool timed out after {self._EXEC_TIMEOUT}s", is_error=True)
        except Exception as e:
            return ToolResult(content=f"MCP tool execution failed: {e}", is_error=True)
        finally:
            if self._on_active_change:
                self._on_active_change(self.server_name, -1)

    async def _call(self, kwargs: dict) -> dict:
        """执行 transport 调用，由 execute 包装超时控制"""
        return await self.transport.send(
            "tools/call",
            {"name": self._tool_def["name"], "arguments": kwargs},
        )
