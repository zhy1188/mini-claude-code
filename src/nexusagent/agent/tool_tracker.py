"""Tool execution tracker with lifecycle states."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ToolExecution:
    """追踪单个工具执行生命周期"""

    id: str
    name: str
    input: dict
    status: str = "pending"  # pending | running | done | failed | cancelled
    output: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        """执行耗时（秒）"""
        if self.finished_at > 0:
            return self.finished_at - self.started_at
        if self.started_at > 0:
            return time.monotonic() - self.started_at
        return 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "input": self.input,
            "status": self.status,
            "output": self.output[:500],  # truncate for serialization
            "error": self.error,
            "duration": round(self.duration, 2),
        }


class ToolTracker:
    """
    追踪当前轮次内所有工具执行。

    提供:
        - 生命周期状态追踪（pending → running → done/failed）
        - 耗时监控
        - 检查点序列化摘要
    """

    def __init__(self):
        self.executions: list[ToolExecution] = []

    def create(self, tool_id: str, name: str, input: dict) -> ToolExecution:
        """注册新的工具执行，初始状态为 'pending'"""
        exec = ToolExecution(
            id=tool_id,
            name=name,
            input=input,
        )
        self.executions.append(exec)
        return exec

    def start(self, tool_id: str) -> None:
        """标记工具执行为 'running'"""
        exec = self._find(tool_id)
        if exec:
            exec.status = "running"
            exec.started_at = time.monotonic()

    def complete(self, tool_id: str, output: str) -> None:
        """标记工具执行为 'done'"""
        exec = self._find(tool_id)
        if exec:
            exec.status = "done"
            exec.output = output
            exec.finished_at = time.monotonic()

    def fail(self, tool_id: str, error: str) -> None:
        """标记工具执行为 'failed'"""
        exec = self._find(tool_id)
        if exec:
            exec.status = "failed"
            exec.error = error
            exec.finished_at = time.monotonic()

    def cancel(self, tool_id: str) -> None:
        """标记工具执行为 'cancelled'"""
        exec = self._find(tool_id)
        if exec and exec.status in ("pending", "running"):
            exec.status = "cancelled"
            exec.finished_at = time.monotonic()

    def pending(self) -> list[ToolExecution]:
        """获取所有仍处于 pending 或 running 的工具"""
        return [
            e for e in self.executions
            if e.status in ("pending", "running")
        ]

    def summary(self) -> str:
        """返回所有执行的可读摘要"""
        lines = []
        for e in self.executions:
            icon = {
                "done": "✓",
                "failed": "✗",
                "cancelled": "⊘",
                "running": "⟳",
                "pending": "◷",
            }.get(e.status, "?")
            lines.append(
                f"  [{icon}] {e.name} ({e.duration:.1f}s) "
                f"{'- ' + e.output[:80] if e.output else ''}"
            )
        return "\n".join(lines)

    def to_dicts(self) -> list[dict]:
        """序列化所有执行记录用于检查点"""
        return [e.to_dict() for e in self.executions]

    def reset(self) -> None:
        """清除所有追踪的执行"""
        self.executions.clear()

    def _find(self, tool_id: str) -> ToolExecution | None:
        for e in self.executions:
            if e.id == tool_id:
                return e
        return None
