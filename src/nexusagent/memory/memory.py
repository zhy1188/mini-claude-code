"""Cross-session memory system (like Claude Code's .claude/ directory)."""

from __future__ import annotations

from pathlib import Path

from nexusagent.memory.frontmatter import format_frontmatter, parse_frontmatter
from nexusagent.memory.index import MemoryEntry, MemoryIndex


class MemorySystem:
    """
    跨会话持久化记忆，存储在 .nexus/memory/ 中。

    记忆类型:
        - user.md: 用户偏好、角色、知识
        - feedback.md: 用户的指导和纠正
        - project.md: 项目目标、决策、状态
        - reference.md: 外部系统指针

    使用两级索引: MEMORY.md 指针 + 带 YAML 前置元数据的
    独立 .md 文件。
    """

    MEMORY_TYPES = ["user", "feedback", "project", "reference"]

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = memory_dir or Path(".nexus") / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.nexus_dir = self.memory_dir.parent

        # 初始化索引（如果 MEMORY.md 存在则加载）
        self.index = MemoryIndex(self.nexus_dir)

        # 如果默认记忆文件不存在则创建
        for name in self.MEMORY_TYPES:
            path = self.memory_dir / f"{name}.md"
            if not path.exists():
                path.write_text(f"# {name.capitalize()} Memory\n\n", encoding="utf-8")

    def load_all(self) -> str:
        """加载所有记忆文件并返回合并后的字符串"""
        parts = []
        for name in self.MEMORY_TYPES:
            path = self.memory_dir / f"{name}.md"
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    # 如果有前置元数据则解析，否则使用原始内容
                    meta, body = parse_frontmatter(content)
                    display = body if body else content
                    parts.append(f"## {name.capitalize()} Memory\n{display}")
        return "\n\n".join(parts)

    def get(self, name: str) -> str:
        """获取特定记忆文件的内容"""
        path = self.memory_dir / f"{name}.md"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            _, body = parse_frontmatter(content)
            return body if body else content
        return ""

    def save(self, name: str, content: str, description: str = "") -> None:
        """
        保存记忆文件，带前置元数据。

        同时更新 MEMORY.md 索引。
        """
        from datetime import datetime

        path = self.memory_dir / f"{name}.md"

        # 从名称推断类型（仅限标准类型）
        memory_type = name if name in self.MEMORY_TYPES else "user"

        meta = {
            "name": name,
            "type": memory_type,
            "description": description,
            "created": datetime.now().isoformat(),
        }
        formatted = format_frontmatter(meta, content)
        path.write_text(formatted, encoding="utf-8")

        # 更新索引
        entry = MemoryEntry(
            name=name,
            memory_type=memory_type,
            file_path=f"memory/{name}.md",
            description=description,
        )
        self.index.add_entry(entry)
        self.index.save()

    def append(self, name: str, content: str) -> None:
        """追加到记忆文件"""
        existing = self.get(name)
        self.save(name, existing + "\n" + content)

    def build_system_prompt_section(self) -> str:
        """格式化所有记忆，注入到 LLM 系统提示"""
        memory_content = self.load_all()
        if not memory_content:
            return ""
        return f"\n# Cross-Session Memory\n\n{memory_content}\n"
