"""Active context retrieval: auto-attach file contents from user input."""

from __future__ import annotations

import re
from pathlib import Path


class ContextRetriever:
    """
    从用户输入中扫描文件路径并预加载文件内容。

    在 LLM 看到用户请求之前，这个类:
        1. 从输入文本中提取文件路径
        2. 检查工作目录中文件是否存在
        3. 读取每个文件的前 N 行
        4. 返回格式化的上下文块注入到提示中

    这节省了一次往返：LLM 不需要调用 Read 来
    发现已提及文件的内容。

    灵感来自 Claude Code 的上下文检索模式。
    """

    # 匹配带常见代码扩展名的文件路径
    FILE_PATTERN = re.compile(
        r'(?:^|[\s,;:()"\'])([^\s,;:()"\']*\.[a-zA-Z0-9]{1,8})'
    )
    # 同时匹配看起来像文件引用的无扩展名路径
    PATH_PATTERN = re.compile(
        r'(?:^|[\s,;:()"\'])'
        r'((?:\.{0,2}/)?[^\s,;:()"\']{3,}(?:\.[a-zA-Z0-9]{1,8})?)'
        r'(?:[\s,;:()"\']|$)'
    )
    # 已知代码文件扩展名
    CODE_EXTENSIONS = {
        'py', 'js', 'ts', 'jsx', 'tsx', 'go', 'rs', 'java', 'c', 'cpp',
        'h', 'hpp', 'rb', 'php', 'cs', 'sh', 'bash', 'zsh', 'ps1',
        'yml', 'yaml', 'toml', 'json', 'xml', 'html', 'css', 'scss',
        'md', 'rst', 'txt', 'cfg', 'ini', 'conf', 'sql', 'graphql',
        'proto', 'dockerfile', 'makefile', 'cmake', 'lock',
    }
    # 默认：每个文件读取前 N 行
    DEFAULT_LINES = 50

    def __init__(self, workdir: Path):
        self.workdir = workdir.resolve()

    def extract_file_paths(self, user_input: str) -> list[str]:
        """
        从用户输入文本中提取文件路径。

        返回看起来像代码文件的唯一路径。
        """
        paths = set()

        # 先按扩展名匹配（最可靠）
        for match in self.FILE_PATTERN.finditer(user_input):
            candidate = match.group(1)
            ext = candidate.rsplit('.', 1)[-1].lower() if '.' in candidate else ''
            if ext in self.CODE_EXTENSIONS:
                paths.add(candidate)

        # 同时尝试路径模式匹配已知文件名
        for match in self.PATH_PATTERN.finditer(user_input):
            candidate = match.group(1)
            # 跳过明显是目录的路径（以 / 结尾）
            if candidate.endswith('/'):
                continue
            # 检查是否有代码扩展名
            if '.' in candidate:
                ext = candidate.rsplit('.', 1)[-1].lower()
                if ext in self.CODE_EXTENSIONS:
                    paths.add(candidate)

        return list(paths)

    def attach_context(self, user_input: str, max_lines: int = DEFAULT_LINES) -> str:
        """
        用预读的文件内容构建上下文附件块。

        如果没找到文件或所有文件都不存在，返回空字符串。
        """
        file_paths = self.extract_file_paths(user_input)
        if not file_paths:
            return ""

        attachments = []
        for fp in file_paths:
            path = self._resolve(fp)
            if path and path.is_file():
                content = self._read_head(path, max_lines)
                if content:
                    attachments.append(content)

        if not attachments:
            return ""

        return "\n\n".join(
            ["[Attached File Context]"] + attachments
        )

    def _resolve(self, path: str) -> Path | None:
        """解析路径（相对于 workdir），确保不超出沙箱"""
        try:
            p = Path(path)
            if not p.is_absolute():
                p = self.workdir / p
            resolved = p.resolve()
            resolved.relative_to(self.workdir)
            return resolved
        except (ValueError, RuntimeError):
            return None

    def _read_head(self, path: Path, max_lines: int) -> str | None:
        """读取文件前 N 行，带行号"""
        try:
            with open(path, 'r', errors='replace') as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(f"{i + 1:6d}  {line.rstrip()}")
                if not lines:
                    return None
                total = self._count_lines(path)
                if total > max_lines:
                    lines.append(
                        f"       ... ({total - max_lines} more lines, "
                        f"{total} total)"
                    )
                return (
                    f"## {path.relative_to(self.workdir)} "
                    f"(first {min(max_lines, total)} of {total} lines)\n"
                    + "\n".join(lines)
                )
        except (OSError, IOError):
            return None

    def _count_lines(self, path: Path) -> int:
        """统计文件总行数"""
        try:
            with open(path, 'r', errors='replace') as f:
                return sum(1 for _ in f)
        except (OSError, IOError):
            return 0
