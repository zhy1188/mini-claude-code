"""Finite state machine for agent lifecycle management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


class InvalidStateTransition(Exception):
    """在尝试非法状态转换时抛出"""

    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid state transition: '{current}' → '{target}'"
        )


# MasterAgent 的合法状态转换表
# 键 = 当前状态，值 = 允许的下一个状态集合
#
# 状态中文含义与业务说明：
#   idle       — 空闲：等待用户输入，Agent 未执行任何任务
#   gathering  — 收集中：加载项目上下文、记忆、token 统计等前置信息
#   thinking   — 思考中：向 LLM 发起请求，等待流式响应
#   acting     — 执行中：LLM 返回了 tool call，正在执行工具（Bash/Read/Write 等）
#   verifying  — 验证中：LLM 返回了纯文本响应，准备结束本轮对话
#   compact    — 压缩中：token 用量超过阈值，正在执行上下文压缩
#   done       — 完成：本轮对话结束，结果已返回用户
#   error      — 错误：执行过程中发生异常，需降级恢复
VALID_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"gathering"},           # 收到用户输入 → 开始收集上下文
    "gathering": {"thinking", "compact", "done"},  # 收集完成 → 调用 LLM / 需要压缩 / 直接结束
    "thinking": {"acting", "verifying", "done", "error"},  # LLM 返回 → 有工具调用 / 有文本响应 / 完成 / 异常
    "acting": {"gathering", "thinking", "verifying", "error"},  # 工具执行完 → 继续收集 / 再次调用 LLM / 验证 / 异常
    "verifying": {"gathering", "done", "error"},  # 验证通过 → 继续收集 / 完成 / 异常
    "compact": {"thinking", "error"},  # 压缩完成 → 回到调用 LLM / 压缩异常
    "error": {"idle"},               # 错误处理完 → 回到空闲等待用户
    "done": {"idle"},                # 本轮结束 → 回到空闲等待下一轮
}


@dataclass
class StateMachine:
    """
    带转换验证和事件回调的有限状态机。

    用法:
        sm = StateMachine(initial="idle")
        sm.on_transition("gathering", lambda: print("started gathering"))
        sm.transition("gathering")  # 合法
        sm.transition("acting")     # 抛出 InvalidStateTransition
    """

    current: str = "idle"
    _callbacks: dict[str, list[Callable]] = field(default_factory=dict)

    def transition(self, target: str) -> None:
        """
        转换到新状态。

        抛出:
            InvalidStateTransition: 如果该转换不在有效表中。
        """
        allowed = VALID_TRANSITIONS.get(self.current, set())
        if target not in allowed:
            raise InvalidStateTransition(self.current, target)

        old = self.current
        self.current = target

        # 触发进入新状态的回调
        for cb in self._callbacks.get(target, []):
            cb(old, target)

    def can_transition(self, target: str) -> bool:
        """检查转换是否合法，不实际执行"""
        return target in VALID_TRANSITIONS.get(self.current, set())

    def force(self, target: str) -> None:
        """强制转换状态，不验证（用于恢复）"""
        self.current = target

    def on_transition(self, state: str, callback: Callable) -> None:
        """注册进入 `state` 时触发的回调"""
        self._callbacks.setdefault(state, []).append(callback)

    def reset(self) -> None:
        """重置到空闲状态"""
        self.current = "idle"

    def __repr__(self) -> str:
        return f"StateMachine(state='{self.current}')"
