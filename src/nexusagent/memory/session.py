"""Session manager: save/load conversation history."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class SessionManager:
    """
    管理对话会话持久化。
    - 每轮自动保存到 JSON
    - 支持恢复之前的会话
    - 会话按时间戳命名
    """

    def __init__(self, sessions_dir: Path | None = None):
        self.sessions_dir = sessions_dir or Path(".nexus") / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, messages: list[dict]) -> Path:
        """保存会话消息到 JSON"""
        path = self.sessions_dir / f"{session_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": session_id,
                    "created_at": datetime.now().isoformat(),
                    "messages": messages,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        return path

    def load(self, session_id: str) -> list[dict] | None:
        """加载之前的会话"""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("messages", [])

    def list_sessions(self) -> list[dict]:
        """列出所有可用会话"""
        sessions = []
        for f in self.sessions_dir.glob("*.json"):
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            sessions.append(
                {
                    "id": f.stem,
                    "created_at": data.get("created_at", ""),
                    "message_count": len(data.get("messages", [])),
                }
            )
        return sorted(sessions, key=lambda s: s["created_at"], reverse=True)

    def create_session_id(self) -> str:
        """生成新的会话 ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
