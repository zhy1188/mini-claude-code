"""Agent orchestrator: manages concurrent sub-agent execution."""

from __future__ import annotations

import asyncio

from nexusagent.llm.base import LLMClient
from nexusagent.models import AgentResult
from nexusagent.tools.registry import ToolRegistry

# 子智能体类型的系统提示
_SUBAGENT_PROMPTS = {
    "general": (
        "You are a focused coding assistant. "
        "Complete the given task efficiently. "
        "Read files before editing. Return a concise summary of what you did."
    ),
    "research": (
        "You are a research assistant. Analyze the codebase, "
        "read files, search for patterns, and provide a detailed report. "
        "Do NOT modify files unless explicitly asked."
    ),
    "code": (
        "You are a code modification assistant. Read files carefully before making changes. "
        "Always verify your changes work by running relevant commands. "
        "Return a summary of changes made."
    ),
}

# 每种子智能体类型的默认工具集
# 实现动态工具过滤：每种子智能体只获得所需的工具，
# 减少 token 消耗并防止意外操作。
_SUBAGENT_TOOLS = {
    "general": ["Read", "Write", "Bash", "Glob", "Grep"],
    "research": ["Read", "Glob", "Grep"],          # Read-only: no Write/Bash
    "code": ["Read", "Write", "Bash", "Glob", "Grep"],
}


class SubTask:
    """子智能体执行的一个任务"""

    def __init__(
        self,
        description: str,
        tool_names: list[str] | None = None,
        subagent_type: str = "general",
        prompt: str = "",
    ):
        self.description = description
        self.tool_names = tool_names
        self.subagent_type = subagent_type
        self.prompt = prompt

    @property
    def resolved_tool_names(self) -> list[str]:
        """
        解析工具名称：显式列表 > 子智能体类型默认值。

        这是动态工具过滤机制。如果 tool_names 没有显式设置，
        则回退到该子智能体类型的默认值。
        """
        if self.tool_names is not None:
            return self.tool_names
        return list(_SUBAGENT_TOOLS.get(self.subagent_type, ["Read", "Grep"]))


class AgentOrchestrator:
    """
    编排多个子智能体并发运行。

    流程:
        1. 主智能体识别可并行的子任务
        2. 编排器创建带适当工具集的子智能体
        3. asyncio.gather 并发执行
        4. 结果聚合后返回给主智能体

    动态工具过滤:
        每种子智能体类型有受限的工具集（定义在 _SUBAGENT_TOOLS 中），
        这减少了 token 消耗（请求中更少的工具 schema）并强制
        能力隔离（研究智能体不会意外修改文件）。
    """

    def __init__(self, llm: LLMClient, registry: ToolRegistry):
        self.llm = llm
        self.registry = registry

    async def spawn(self, tasks: list[SubTask]) -> list[AgentResult]:
        """并发派生并运行多个子智能体"""
        from nexusagent.agent.sub_agent import SubAgent

        agents = []
        for task in tasks:
            tools = [
                self.registry.get(name)
                for name in task.resolved_tool_names
                if self.registry.get(name)
            ]
            if not tools:
                tools = self.registry.get_all()[:3]

            system_prompt = task.prompt or _SUBAGENT_PROMPTS.get(task.subagent_type, "")

            agent = SubAgent(
                task=task.description,
                tools=tools,
                llm=self.llm,
                system_prompt=system_prompt,
            )
            agents.append(agent)

        # 并发执行
        results = await asyncio.gather(
            *[agent.run() for agent in agents],
            return_exceptions=True,
        )

        # 处理异常
        processed = []
        for r in results:
            if isinstance(r, Exception):
                processed.append(
                    AgentResult(
                        task="",
                        status="error",
                        summary=str(r),
                    )
                )
            else:
                processed.append(r)

        return processed

    def format_results(self, results: list[AgentResult]) -> str:
        """格式化子智能体结果，注入到主上下文"""
        parts = []
        for i, r in enumerate(results):
            status_icon = "done" if r.status == "success" else "failed"
            parts.append(
                f"### Sub-Agent {i + 1} [{status_icon}]\n"
                f"**Task:** {r.task}\n"
                f"**Summary:** {r.summary}\n"
                f"**Artifacts:** {', '.join(r.artifacts) if r.artifacts else 'none'}\n"
                f"**Tool calls:** {r.tool_calls_made} | **Tokens:** {r.token_usage}"
            )
        return "\n\n".join(parts)
