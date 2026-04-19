"""Hook types and configuration."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class HookType(Enum):
    """NexusAgent 中可用的生命周期钩子"""

    PRE_USER_MESSAGE = "pre_user_message"    # 处理用户输入之前
    POST_USER_MESSAGE = "post_user_message"  # 处理用户输入之后
    PRE_TOOL_USE = "pre_tool_use"           # 执行工具之前
    POST_TOOL_USE = "post_tool_use"         # 执行工具之后
    PRE_RESPONSE = "pre_response"           # 发送 LLM 响应之前
    POST_RESPONSE = "post_response"         # 发送 LLM 响应之后


class HookConfig(BaseModel):
    """
    单个钩子配置。

    示例 (nexus.toml):
        [hooks.pre_tool_use]
        Bash = "echo '{command}' >> audit.log"
    """

    hook_type: HookType
    matcher: str          # 工具名称或通配符模式
    command: str          # 要执行的 Shell 命令
    blocking: bool = False  # 如果为 true，Agent 阻塞直到完成

    def matches(self, context: dict) -> bool:
        """检查此钩子是否匹配当前上下文"""
        if self.matcher == "*":
            return True
        tool_name = context.get("tool_name", "")
        return self.matcher == tool_name
