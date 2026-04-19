"""Checkpoint system for save/restore agent state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Checkpoint:
    """
    将 Agent 状态持久化到磁盘，用于崩溃恢复和中断恢复。

    检查点格式 (.nexus/checkpoints/checkpoint_TIMESTAMP.json):
    {
        "timestamp": "2026-04-18T14:30:00",
        "state": "thinking",
        "session_id": "20260418_143000",
        "messages": [...],  # 序列化后的 Message 列表
        "user_input": "fix auth.py bug",  # 本轮的原始用户输入
        "iteration": 3,
        "tool_executions": [...]  # 待执行的工具调用
    }
    """

    def __init__(self, checkpoint_dir: Path | None = None):
        self.checkpoint_dir = checkpoint_dir or Path(".nexus") / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        # 只保留最新的 N 个检查点
        self._max_checkpoints = 10

    def save(
        self,
        state: str,
        messages: list[dict],
        session_id: str,
        user_input: str = "",
        iteration: int = 0,
        tool_executions: list[dict] | None = None,
    ) -> Path:
        """保存当前 Agent 状态到检查点文件"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.checkpoint_dir / f"checkpoint_{ts}.json"

        data = {
            "timestamp": datetime.now().isoformat(),
            "state": state,
            "session_id": session_id,
            "messages": messages,
            "user_input": user_input,
            "iteration": iteration,
            "tool_executions": tool_executions or [],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self._cleanup_old()
        return path

    def load_latest(self) -> dict | None:
        """加载最新的检查点。没有则返回 None。"""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        if not checkpoints:
            return None

        with open(checkpoints[-1], "r", encoding="utf-8") as f:
            return json.load(f)

    def clear(self) -> None:
        """移除所有检查点文件"""
        for f in self.checkpoint_dir.glob("checkpoint_*.json"):
            f.unlink()

    def has_pending(self) -> bool:
        """检查是否有未完成的可恢复会话"""
        cp = self.load_latest()
        if cp is None:
            return False
        # 检查点处于 "pending" 状态当状态不是 idle/done
        return cp["state"] not in ("idle", "done")

    def _cleanup_old(self) -> None:
        """清理旧检查点，只保留最新的 N 个"""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        while len(checkpoints) > self._max_checkpoints:
            checkpoints[0].unlink()
            checkpoints.pop(0)
