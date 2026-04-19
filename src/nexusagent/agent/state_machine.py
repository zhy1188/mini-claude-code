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
VALID_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"gathering"},
    "gathering": {"thinking", "compact", "done"},
    "thinking": {"acting", "verifying", "done", "error"},
    "acting": {"gathering", "thinking", "verifying", "error"},
    "verifying": {"gathering", "done", "error"},
    "compact": {"thinking", "error"},
    "error": {"idle"},
    "done": {"idle"},
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
