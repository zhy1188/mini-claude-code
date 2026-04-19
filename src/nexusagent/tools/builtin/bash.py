"""Bash tool: execute shell commands with safety controls."""

from __future__ import annotations

import asyncio
import hashlib
import re

from nexusagent.config import BashConfig
from nexusagent.models import ToolResult
from nexusagent.tools.base import Tool


class BashTool(Tool):
    name = "Bash"
    description = (
        "Execute a shell command. Has timeout, sandbox, and safety restrictions. "
        "Output is structured as stdout/stderr separated."
    )
    parameters = {
        "command": {
            "type": "string",
            "description": "The shell command to execute",
            "required": True,
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default: 120)",
            "required": False,
        },
        "dangerous": {
            "type": "boolean",
            "description": "Skip dangerous command checks (requires user approval)",
            "required": False,
        },
    }

    # Patterns that escape the working directory
    _PATH_ESCAPE = re.compile(r"\.\./|\.\.\\")

    def __init__(self, workdir, config: BashConfig | None = None):
        super().__init__(workdir)
        self.config = config or BashConfig()
        self._cache: dict[str, ToolResult] = {}

    def _check_dangerous(self, command: str) -> str | None:
        """Check if command matches dangerous patterns."""
        cmd_lower = command.lower()
        for pattern in self.config.dangerous_patterns:
            if pattern.lower() in cmd_lower:
                return f"Dangerous pattern detected: {pattern}"
        return None

    def _check_sandbox(self, command: str) -> str | None:
        """Check if command tries to escape the workdir sandbox."""
        # Check for path traversal
        if self._PATH_ESCAPE.search(command):
            return f"Path traversal detected: command escapes workdir"
        return None

    def _smart_truncate(self, output: str) -> str:
        """Truncate output keeping head and tail for context."""
        max_bytes = self.config.max_output_bytes
        if len(output.encode()) <= max_bytes:
            return output

        head_bytes = max_bytes // 3
        tail_bytes = max_bytes // 3

        encoded = output.encode()
        head = encoded[:head_bytes].decode(errors="replace")
        tail = encoded[-tail_bytes:].decode(errors="replace")

        total = len(output.encode())
        skipped = total - head_bytes - tail_bytes
        return (
            f"[Output truncated ({total} bytes total). "
            f"Showing first {head_bytes} and last {tail_bytes} bytes]\n\n"
            f"{head}\n\n--- {skipped} bytes omitted ---\n\n{tail}"
        )

    def _cache_key(self, command: str) -> str:
        """Generate a cache key for a command."""
        return hashlib.md5(command.encode()).hexdigest()

    async def execute(
        self, command: str, timeout: int = None, dangerous: bool = False
    ) -> ToolResult:
        # Safety check
        if not dangerous:
            reason = self._check_dangerous(command)
            if reason:
                return ToolResult(
                    content=f"Blocked: {reason}\nCommand: {command}", is_error=True
                )

            # Sandbox check
            reason = self._check_sandbox(command)
            if reason:
                return ToolResult(
                    content=f"Sandbox violation: {reason}\nCommand: {command}",
                    is_error=True,
                )

        # Check cache (read-only commands only)
        cache_key = self._cache_key(command)
        read_only = all(
            not command.startswith(cmd)
            for cmd in ("git", "make", "python", "pip", "npm", "cargo", "cmake")
        )
        if read_only and cache_key in self._cache:
            return self._cache[cache_key]

        # Execute with timeout
        actual_timeout = timeout or self.config.timeout

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workdir),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=actual_timeout
            )

            stdout_str = stdout.decode(errors="replace")
            stderr_str = stderr.decode(errors="replace")

            # Build structured output
            parts = []
            if stdout_str.strip():
                parts.append(f"=== stdout ===\n{self._smart_truncate(stdout_str)}")
            if stderr_str.strip():
                parts.append(f"=== stderr ===\n{self._smart_truncate(stderr_str)}")
            parts.append(f"=== exit code: {proc.returncode} ===")

            output = "\n\n".join(parts)

            result = ToolResult(
                content=output,
                metadata={
                    "exit_code": proc.returncode,
                    "command": command,
                    "stdout_bytes": len(stdout_str),
                    "stderr_bytes": len(stderr_str),
                },
            )

            # Cache read-only results
            if read_only:
                self._cache[cache_key] = result

            return result

        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ToolResult(
                content=f"Command timed out after {actual_timeout}s: {command}",
                is_error=True,
                metadata={"exit_code": -1},
            )
        except Exception as e:
            return ToolResult(content=f"Error executing command: {e}", is_error=True)
