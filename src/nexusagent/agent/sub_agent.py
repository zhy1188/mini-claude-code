"""Sub-Agent: isolated execution unit with its own context and tools."""

from __future__ import annotations

from nexusagent.context.manager import ContextManager
from nexusagent.llm.base import LLMClient
from nexusagent.models import AgentResult, AssistantMessage, ToolCall, ToolResultMessage, UserMessage
from nexusagent.tools.registry import ToolRegistry


class SubAgent:
    """
    隔离执行单元：
    - 独立的消息历史（不污染主上下文）
    - 受限的工具集（按任务类型分配）
    - 结构化结果返回给父级
    - Token 预算限制防止失控执行
    """

    def __init__(
        self,
        task: str,
        tools: list,
        llm: LLMClient,
        system_prompt: str | None = None,
        max_tokens: int = 50_000,
        max_iterations: int = 20,
    ):
        self.task = task
        self.llm = llm
        self.registry = ToolRegistry()
        for tool in tools:
            self.registry.register(tool)
        self.system_prompt = system_prompt or self._default_prompt()
        self.context = ContextManager(max_tokens=max_tokens, compact_threshold=0.8)
        self.max_iterations = max_iterations
        self.tool_calls_made = 0
        self.token_usage = 0

    async def run(self) -> AgentResult:
        """执行子智能体任务并返回结构化结果"""
        self.context.add_message(UserMessage(content=self.task))
        artifacts = []

        for _ in range(self.max_iterations):
            messages = self.context.build_messages()
            tools = self.registry.get_tool_definitions()

            full_content = ""
            tool_calls = []

            async for response in self.llm.stream(
                messages=messages, tools=tools, system=self.system_prompt
            ):
                if response.content:
                    full_content += response.content
                if response.tool_calls:
                    tool_calls.extend(response.tool_calls)
                if response.usage:
                    self.token_usage += response.usage.get("output_tokens", 0)

            if tool_calls:
                self.context.add_message(AssistantMessage(content=full_content))
                full_content = ""  # Tool call response

                for tc in tool_calls:
                    result = await self._execute_tool(tc)
                    self.context.add_message(
                        ToolResultMessage(
                            content=result.content,
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                        )
                    )
                    self.tool_calls_made += 1

                # 追踪产出品
                    if tc.name == "Write" and not result.is_error:
                        path = tc.input.get("file_path", "")
                        if path:
                            artifacts.append(path)

                continue

            # 文本响应 → 完成
            if full_content:
                self.context.add_message(AssistantMessage(content=full_content))

            return AgentResult(
                task=self.task,
                status="success",
                summary=full_content,
                artifacts=artifacts,#修改的文件列表
                tool_calls_made=self.tool_calls_made,
                token_usage=self.token_usage,
            )

        return AgentResult(
            task=self.task,
            status="error",
            summary="Sub-agent exceeded maximum iterations",
            tool_calls_made=self.tool_calls_made,
            token_usage=self.token_usage,
        )

    async def _execute_tool(self, tool_call: ToolCall):
        from nexusagent.models import ToolResult

        tool = self.registry.get(tool_call.name)
        if not tool:
            return ToolResult(content=f"Unknown tool: {tool_call.name}", is_error=True)

        try:
            args = tool_call.input
            if isinstance(args, str):
                import json

                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            return await tool.execute(**args)
        except Exception as e:
            return ToolResult(content=f"Tool error: {e}", is_error=True)

    def _default_prompt(self) -> str:
        return (
            "You are a focused coding assistant. "
            "Complete the given task efficiently. "
            "Read files before editing. "
            "Return a concise summary of what you did."
        )
