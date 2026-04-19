"""MCP Wrapped Tool: adapts a remote MCP tool to the local Tool interface."""

from __future__ import annotations

import asyncio
import json

from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class MCPWrappedTool(Tool):
    """
    包装远程 MCP 服务器暴露的工具。
    将 MCP 工具定义转换为本地 Tool 格式，通过 JSON-RPC 执行。
    """

    _EXEC_TIMEOUT = 30  # MCP 工具执行超时（秒）

    def __init__(self, proc, server_name: str, tool_def: dict):
        self.proc = proc
        self.server_name = server_name
        self._tool_def = tool_def

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
        """通过 JSON-RPC 执行远程 MCP 工具"""
        request = {
            "jsonrpc": "2.0",
            "id": id(object()),
            "method": "tools/call",
            "params": {"name": self._tool_def["name"], "arguments": kwargs},
        }

        try:
            if self.proc.stdin is None or self.proc.stdout is None:
                return ToolResult(content="MCP server disconnected", is_error=True)

            data = json.dumps(request) + "\n"
            self.proc.stdin.write(data.encode())
            await self.proc.stdin.drain()

            line = await asyncio.wait_for(
                self.proc.stdout.readline(), timeout=self._EXEC_TIMEOUT
            )
            if not line:
                return ToolResult(content="Empty response from MCP server", is_error=True)

            response = json.loads(line.decode())

            if "error" in response:
                return ToolResult(
                    content=f"MCP error: {response['error']}", is_error=True
                )

            result = response.get("result", {})
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
