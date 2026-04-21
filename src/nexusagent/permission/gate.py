"""Permission gate: intercept tool calls and enforce trust policy."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from nexusagent.models import PermissionDecision, ToolCall
from nexusagent.permission.policy import TrustPolicy


class PermissionGate:
    """
    在工具执行前拦截调用并执行信任策略。

    流程:
        1. 工具被调用
        2. PermissionGate 检查 TrustPolicy
        3. 如果是 "approve" → 直接通过
        4. 如果是 "ask" → 阻塞等待用户确认
        5. 如果是 "deny" → 拒绝并返回错误给 LLM
    """

    def __init__(self, policy: TrustPolicy, console: Console | None = None, hide_hook=None, show_hook=None):
        self.policy = policy
        self.console = console or Console()
        self._hide_hook = hide_hook  # callable to hide UI before input
        self._show_hook = show_hook  # callable to restore UI after input

    async def check(self, tool_call: ToolCall) -> PermissionDecision:
        """检查工具调用的权限。需要时阻塞等待用户输入。"""
        level = self.policy.get_level(tool_call.name)

        if level == "approve":
            return PermissionDecision.APPROVE

        if level == "deny":
            return PermissionDecision.DENY

        # "ask": 提示用户
        return await self._prompt_user(tool_call)

    async def _prompt_user(self, tool_call: ToolCall) -> PermissionDecision:
        """向用户展示工具调用详情并等待确认"""
        args_preview = ""
        if tool_call.input:
            args_preview = "\n  Args: " + str(tool_call.input)

        # Hide active UI (e.g., status bar Live) before showing prompt
        if self._hide_hook:
            self._hide_hook()

        self.console.print(
            Panel(
                f"[yellow]Tool:[/yellow] {tool_call.name}{args_preview}\n"
                f"[yellow]Approve?[/yellow] (y/n)",
                title="Permission Request",
                border_style="yellow",
            )
        )

        # Read user input
        try:
            answer = await self._read_input()
            if answer.strip().lower() in ("y", "yes", ""):
                return PermissionDecision.APPROVE
            return PermissionDecision.DENY
        except (EOFError, KeyboardInterrupt):
            return PermissionDecision.DENY
        finally:
            # Restore UI after input
            if self._show_hook:
                self._show_hook()

    async def _read_input(self) -> str:
        """从用户读取一行输入。可重写用于测试。"""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, input)
