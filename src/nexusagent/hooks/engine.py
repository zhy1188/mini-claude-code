"""Hook engine: triggers configured hooks at lifecycle points."""

from __future__ import annotations

import asyncio
import string
from dataclasses import dataclass, field

from nexusagent.hooks.types import HookConfig, HookType


@dataclass
class HookResult:
    blocked: bool = False
    reason: str = ""
    output: str = ""


class HookEngine:
    """
    在生命周期节点执行配置的钩子。

    类似 Git 钩子或 Express 中间件，钩子让用户无需修改代码
    即可自定义 Agent 行为。

    用法:
        engine = HookEngine()
        engine.register(HookConfig(
            hook_type=HookType.PRE_TOOL_USE,
            matcher="Bash",
            command="echo '{command}' >> audit.log",
            blocking=True,
        ))

        # 在 Agent 循环中:
        result = await engine.trigger(HookType.PRE_TOOL_USE, {
            "tool_name": "Bash",
            "command": "ls -la",
        })
        if result.blocked:
            # 不执行工具
            return
    """

    def __init__(self):
        self.hooks: dict[HookType, list[HookConfig]] = {}

    def register(self, hook: HookConfig) -> None:
        """注册一个钩子"""
        if hook.hook_type not in self.hooks:
            self.hooks[hook.hook_type] = []
        self.hooks[hook.hook_type].append(hook)

    async def trigger(self, hook_type: HookType, context: dict) -> HookResult:
        """
        触发指定类型的所有钩子。

        返回:
            如果任何阻塞钩失败，返回 blocked=True 的 HookResult。
        """
        hooks = self.hooks.get(hook_type, [])

        for hook in hooks:
            if hook.matches(context):
                result = await self._execute_hook(hook, context)
                if result.blocked:
                    return result

        return HookResult()

    async def _execute_hook(self, hook: HookConfig, context: dict) -> HookResult:
        """执行单个钩子命令"""
        # 将上下文变量插值到命令模板中
        cmd = self._interpolate(hook.command, context)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            if hook.blocking:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=30
                )
                output = stdout.decode() + stderr.decode()
                if proc.returncode != 0:
                    return HookResult(
                        blocked=True,
                        reason=f"Hook failed (exit {proc.returncode}): {output[:200]}",
                        output=output,
                    )
                return HookResult(output=output)
            else:
                # 后台异步执行，不阻塞
                asyncio.create_task(proc.communicate())
                return HookResult()

        except Exception as e:
            return HookResult(
                blocked=True, reason=f"Hook execution error: {e}"
            )

    def _interpolate(self, template: str, context: dict) -> str:
        """将上下文变量插值到命令模板"""
        try:
            return string.Template(template).safe_substitute(context)
        except Exception:
            return template
