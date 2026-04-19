"""Trust policy: declarative permission configuration."""

from __future__ import annotations

from pydantic import BaseModel

from nexusagent.config import NexusConfig


class TrustPolicy(BaseModel):
    """
    声明式工具权限策略。
    映射到 Claude Code 的权限模型。

    级别:
        - "approve": 自动批准，不提示用户
        - "ask": 提示用户确认
        - "deny": 始终阻止
    """

    tool_permissions: dict[str, str] = {
        "Read": "approve",
        "Glob": "approve",
        "Grep": "approve",
        "Write": "ask",
        "Bash": "ask",
        "Task": "ask",
        "MemoryWrite": "approve",
        "SessionSave": "approve",
    }

    @classmethod
    def from_config(cls, config: NexusConfig) -> "TrustPolicy":
        """从 NexusConfig 的 permissions 段构建 TrustPolicy"""
        perms = {}
        for tool_name, level in config.permissions.model_dump().items():
            perms[tool_name] = level
        return cls(tool_permissions=perms)

    def get_level(self, tool_name: str) -> str:
        """获取工具的权限级别。默认回退到 'ask'。"""
        return self.tool_permissions.get(tool_name, "ask")

    def set_level(self, tool_name: str, level: str) -> None:
        """设置工具的权限级别"""
        self.tool_permissions[tool_name] = level
