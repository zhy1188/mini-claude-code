"""MCP Bridge: connects to MCP servers via stdio or Streamable HTTP."""

from __future__ import annotations

import asyncio

from nexusagent.tools.mcp.transport import HTTPTransport, MCPTransport, StdioTransport
from nexusagent.tools.mcp.wrapper import MCPWrappedTool
from nexusagent.tools.registry import ToolRegistry


class MCPBridge:
    """
    管理多个 MCP 服务器连接（stdio 或 HTTP）。
    统一处理初始化握手、工具发现和注册。
    支持运行时热插拔：add_server / remove_server。
    """

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._servers: dict[str, dict] = {}  # name -> {transport, info, ref_count}

    def _on_active_change(self, server_name: str, delta: int) -> None:
        """工具执行开始/结束时更新引用计数"""
        server = self._servers.get(server_name)
        if server:
            server["ref_count"] = max(0, server["ref_count"] + delta)

    async def connect_server(self, name: str, config: dict) -> None:
        """连接到 MCP 服务器并注册其工具"""
        await self.add_server(name, config)

    async def add_server(self, name: str, config: dict) -> None:
        """运行时动态接入新的 MCP 服务器"""
        if name in self._servers:
            print(f"MCP: Server '{name}' already connected, skipping")
            return

        transport_type = config.get("transport", "stdio")

        if transport_type == "http":
            transport: MCPTransport = HTTPTransport(url=config["url"])
        else:
            transport = StdioTransport(command=config["command"])

        try:
            init_result = await transport.connect()
        except Exception as e:
            await transport.disconnect()
            print(f"MCP: Failed to connect to '{name}' ({transport_type}): {e}")
            return

        # 发送已初始化通知
        await transport.send_notification("notifications/initialized", {})

        # 发现工具
        try:
            tools_resp = await transport.send("tools/list", {})
            tools = tools_resp if isinstance(tools_resp, list) else tools_resp.get("tools", [])

            for tool_def in tools:
                wrapped = MCPWrappedTool(
                    transport, name, tool_def,
                    on_active_change=self._on_active_change,
                )
                self.registry.register(wrapped)

            self._servers[name] = {"transport": transport, "info": init_result, "ref_count": 0}
            print(f"MCP: Connected to '{name}' ({transport_type}), registered {len(tools)} tools")
        except Exception as e:
            await transport.disconnect()
            print(f"MCP: Failed to list tools from '{name}': {e}")

    async def remove_server(self, name: str) -> tuple[bool, str]:
        """运行时断开指定 MCP 服务器，返回 (成功, 消息)"""
        server = self._servers.get(name)
        if not server:
            return False, f"Server '{name}' not found"

        # 并发安全：检查是否有工具正在执行中
        if server["ref_count"] > 0:
            return False, f"Server '{name}' has {server['ref_count']} tool(s) running, try again later"

        # 注销该服务器的所有工具
        prefix = f"mcp__{name}__"
        removed = self.registry.unregister_prefix(prefix)

        # 断开连接
        try:
            await server["transport"].disconnect()
        except Exception as e:
            del self._servers[name]
            return False, f"Disconnect error: {e}"

        del self._servers[name]
        return True, f"Removed server '{name}', unregistered {len(removed)} tools: {', '.join(removed)}"

    def list_servers(self) -> list[dict]:
        """列出所有已连接的 MCP 服务器"""
        result = []
        for name, server in self._servers.items():
            tools = [t.name for t in self.registry.get_all() if t.name.startswith(f"mcp__{name}__")]
            result.append({
                "name": name,
                "tools": tools,
                "tool_count": len(tools),
                "running": server["ref_count"],
            })
        return result

    async def disconnect_all(self) -> None:
        """断开所有 MCP 服务器连接"""
        for name in list(self._servers.keys()):
            await self.remove_server(name)
