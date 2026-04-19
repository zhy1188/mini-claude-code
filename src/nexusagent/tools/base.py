"""Tool abstraction base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from nexusagent.models import ToolResult


class Tool(ABC):
    """所有工具的基类。直接映射到 LLM Tool Use API。"""

    name: str = ""
    description: str = ""
    parameters: dict = {}  # JSON Schema format

    def __init__(self, workdir: Path | None = None):
        self.workdir = workdir or Path.cwd()

    def to_llm_schema(self) -> dict:
        """转换为 LLM API JSON Schema 格式"""
        required = [
            name
            for name, spec in self.parameters.items()
            if spec.get("required", False)
        ]
        properties = {}
        for name, spec in self.parameters.items():
            prop = {k: v for k, v in spec.items() if k != "required"}
            properties[name] = prop

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """使用给定参数执行工具"""
        ...

    def _resolve_path(self, path: str) -> Path:
        """解析相对于 workdir 的路径，执行沙箱限制"""
        p = Path(path)
        workdir = Path(self.workdir)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (workdir / p).resolve()

        # 沙箱：确保路径在 workdir 范围内
        workdir_resolved = workdir.resolve()
        try:
            resolved.relative_to(workdir_resolved)
        except ValueError:
            raise PermissionError(
                f"Path '{path}' escapes workdir sandbox ({workdir_resolved})"
            )
        return resolved

    def _safe_read(self, path: Path, max_bytes: int = 50_000) -> str:
        """读取文件，带大小限制"""
        size = path.stat().st_size
        if size > max_bytes:
            content = path.read_text(errors="replace")[: max_bytes // 2]
            return f"[File too large ({size} bytes, showing first {max_bytes // 2} bytes)]\n{content}"
        return path.read_text(errors="replace")
