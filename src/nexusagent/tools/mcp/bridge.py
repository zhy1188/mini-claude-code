"""MCP Bridge: connects to external MCP servers via stdio JSON-RPC."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nexusagent.tools.base import Tool
from nexusagent.tools.mcp.wrapper import MCPWrappedTool
from nexusagent.tools.registry import ToolRegistry


class MCPBridge:
    """
    实现 MCP（模型上下文协议）子集:
    - 连接到本地 stdio MCP 服务器
    - JSON-RPC 初始化握手
    - tools/list: 发现工具定义
    - tools/call: 执行远程工具
    - 将发现的工具注册到 ToolRegistry

    MCP 协议流程:
        1. 派生子进程（stdio 通信）
        2. JSON-RPC 初始化握手
        3. tools/list: 获取工具定义
        4. tools/call: 执行工具
    """

    _JSONRPC_TIMEOUT = 30  # JSON-RPC 请求超时（秒）

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._servers: dict[str, dict] = {}  # name -> {proc, info}

    async def connect_server(self, name: str, command: str) -> None:
        """连接到 MCP 服务器并注册其工具"""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            print(f"MCP: Failed to start server '{name}': {e}")
            return

        # 启动 stderr 后台读取任务，捕获服务器日志
        asyncio.create_task(self._drain_stderr(proc, name))

        # 初始化握手
        try:
            init_result = await self._jsonrpc_request(
                proc,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "NexusAgent", "version": "0.1.0"},
                },
            )
        except Exception as e:
            proc.kill()
            print(f"MCP: Failed to initialize server '{name}': {e}")
            return

        # 发送已初始化通知
        await self._jsonrpc_notify(proc, "notifications/initialized", {})

        # 发现工具
        try:
            tools_resp = await self._jsonrpc_request(proc, "tools/list", {})
            tools = tools_resp if isinstance(tools_resp, list) else tools_resp.get("tools", [])

            for tool_def in tools:
                wrapped = MCPWrappedTool(proc, name, tool_def)
                self.registry.register(wrapped)

            self._servers[name] = {"proc": proc, "info": init_result}
            print(f"MCP: Connected to '{name}', registered {len(tools)} tools")
        except Exception as e:
            proc.kill()
            print(f"MCP: Failed to list tools from '{name}': {e}")

    async def _jsonrpc_request(self, proc, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应"""
        request_id = id(object())
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        if proc.stdin is None:
            raise RuntimeError("Process stdin is None")

        data = json.dumps(request) + "\n"
        proc.stdin.write(data.encode())
        await proc.stdin.drain()

        # 循环读取直到收到匹配 request_id 的响应
        # MCP 服务器可能在 stdout 输出日志行（非 JSON）或通知消息
        if proc.stdout is None:
            raise RuntimeError("Process stdout is None")

        while True:
            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=self._JSONRPC_TIMEOUT
            )
            if not line:
                raise RuntimeError("MCP server closed connection")
            try:
                response = json.loads(line.decode())
                # 忽略通知或日志（没有 id 字段，或 id 不匹配）
                if "id" in response and response["id"] != request_id:
                    continue
                if "error" in response:
                    raise RuntimeError(f"MCP error: {response['error']}")
                # 返回结果（可能是 dict 或列表）
                return response.get("result", {})
            except json.JSONDecodeError:
                # 忽略非 JSON 行（如服务器日志输出）
                continue

    async def _jsonrpc_notify(self, proc, method: str, params: dict) -> None:
        """发送 JSON-RPC 通知（不需要响应）"""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if proc.stdin is None:
            return
        data = json.dumps(notification) + "\n"
        proc.stdin.write(data.encode())
        await proc.stdin.drain()

    async def _drain_stderr(self, proc, name: str) -> None:
        """后台读取 stderr 并打印日志"""
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    print(f"MCP[{name}] stderr: {text}")
        except Exception:
            pass

    async def disconnect_all(self) -> None:
        """断开所有 MCP 服务器连接"""
        for name, server in self._servers.items():
            try:
                server["proc"].kill()
            except Exception:
                pass
        self._servers.clear()
