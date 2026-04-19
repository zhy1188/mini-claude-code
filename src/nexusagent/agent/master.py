"""Master Agent: the core agentic loop (Gather → Act → Verify)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nexusagent.agent.checkpoint import Checkpoint
from nexusagent.agent.orchestrator import AgentOrchestrator
from nexusagent.agent.state_machine import StateMachine, VALID_TRANSITIONS
from nexusagent.agent.tool_tracker import ToolTracker
from nexusagent.context.manager import ContextManager
from nexusagent.context.retriever import ContextRetriever
from nexusagent.llm.base import LLMClient
from nexusagent.models import (
    AgentState,
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from nexusagent.hooks.engine import HookEngine
from nexusagent.hooks.types import HookType
from nexusagent.memory.session import SessionManager
from nexusagent.permission.gate import PermissionGate
from nexusagent.skills.matcher import SkillMatcher
from nexusagent.skills.registry import SkillRegistry
from nexusagent.tools.builtin.memory_write import MemoryWriteTool
from nexusagent.tools.builtin.session_save import SessionSaveTool
from nexusagent.tools.builtin.task import TaskTool
from nexusagent.tools.registry import ToolRegistry
from nexusagent.tui.app import NexusTUI


class MasterAgent:
    """
    单线程主循环，管理整个对话生命周期。

    状态管理（4 层）:
        1. 有限状态机: 通过转换表强制验证状态转换
        2. 检查点: 在关键节点保存状态，用于崩溃恢复
        3. 异步取消: asyncio.Event 安全中断（Ctrl+C / /stop）
        4. 工具追踪: 每个工具的生命周期追踪（pending→running→done/failed）

    核心循环:
        1. 接收用户输入 → 加入历史
        2. 主动上下文检索（预加载文件内容）
        3. 检查是否需要上下文压缩
        4. 构建消息（结构化系统提示 + 历史 + 工具定义）
        5. 调用 LLM（流式，带提示缓存）
        6. 解析响应（文本或工具调用）
        7. 如果是工具调用 → 执行 → 结果加入历史 → 回到 5
        8. 如果是文本响应 → 加入历史 → 完成 → 回到 1
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        permission_gate: PermissionGate,
        tui: NexusTUI,
        workdir: Path | None = None,
        hook_engine: HookEngine | None = None,
        max_iterations: int = 50,
        context_retriever: ContextRetriever | None = None,
        skill_registry: SkillRegistry | None = None,
    ):
        self.llm = llm_client
        self.registry = tool_registry
        self.context = context_manager
        self.permission = permission_gate
        self.tui = tui
        self.workdir = workdir or Path.cwd()
        self.hook_engine = hook_engine
        self.max_iterations = max_iterations
        self.context_retriever = context_retriever
        self.skill_registry = skill_registry
        self._skill_matcher = SkillMatcher(skill_registry) if skill_registry else None

        # 第 1 层: 有限状态机（替代裸枚举）
        self.state_machine = StateMachine(current="idle")
        # 保留旧枚举以兼容旧代码
        self.state = AgentState.IDLE

        # 第 2 层: 检查点系统
        self.checkpoint = Checkpoint(self.workdir / ".nexus" / "checkpoints")

        # 第 3 层: 异步取消机制
        self._cancel_event = asyncio.Event()
        self._current_user_input = ""

        # 第 4 层: 工具追踪
        self.tool_tracker = ToolTracker()

        # 会话管理器，用于自动保存
        self.session_manager = SessionManager(self.workdir / ".nexus" / "sessions")
        self._current_session_id = self.session_manager.create_session_id()

        # Memory write tool
        nexus_dir = self.workdir / ".nexus"
        self.memory_write_tool = MemoryWriteTool(nexus_dir)
        self.registry.register(self.memory_write_tool)

        # 子智能体编排器，用于派生子 Agent
        self.orchestrator = AgentOrchestrator(self.llm, self.registry)

        # Wire TaskTool to orchestrator + registry
        self._wire_task_tool()

        # 注册状态转换回调，用于 TUI 更新
        self._register_state_callbacks()

    def _register_state_callbacks(self) -> None:
        """Register TUI updates on state transitions."""
        self.state_machine.on_transition("thinking", lambda old, new: None)  # handled inline
        self.state_machine.on_transition("compact", lambda old, new: None)

    def _sync_legacy_state(self) -> None:
        # 将 FSM 状态同步到旧版 AgentState 枚举（向后兼容）
        state_map = {
            "idle": AgentState.IDLE,
            "gathering": AgentState.GATHERING,
            "thinking": AgentState.THINKING,
            "acting": AgentState.ACTING,
            "verifying": AgentState.VERIFYING,
            "compact": AgentState.COMPACTING,
            "done": AgentState.DONE,
            "error": AgentState.ERROR,
        }
        self.state = state_map.get(self.state_machine.current, AgentState.IDLE)

    def _wire_task_tool(self):
        """将 TaskTool 连接到编排器（创建后绑定）"""
        task = self.registry.get("Task")
        if isinstance(task, TaskTool):
            task.set_orchestrator(self.orchestrator, self.registry)

        # 将 LLM 引用传递给上下文管理器，用于预测性压缩
        self.context.set_llm_ref(self.llm)

    def request_cancel(self) -> None:
        """优雅停止信号（TUI 在 Ctrl+C 或 /stop 时调用）"""
        self._cancel_event.set()

    def _check_cancelled(self) -> bool:
        """检查是否请求取消。如果是，保存检查点并返回 True。"""
        if self._cancel_event.is_set():
            self._save_checkpoint("cancelled")
            self._save_session()
            return True
        return False

    async def run(self, user_input: str):
        """运行一轮 Agent 循环（FSM + 检查点 + 取消机制）"""
        self._cancel_event.clear()
        self.tool_tracker.reset()
        self._current_user_input = user_input

        # 阶段 1: FSM 状态转换
        try:
            self.state_machine.transition("gathering")
        except Exception:
            self.state_machine.force("gathering")
        self._sync_legacy_state()

        # 触发用户消息前钩子
        if self.hook_engine:
            hook_result = await self.hook_engine.trigger(
                HookType.PRE_USER_MESSAGE, {"user_input": user_input}
            )
            if hook_result.blocked:
                await self.tui.show_status(f"Hook blocked: {hook_result.reason}")
                self.state_machine.transition("done")
                self._sync_legacy_state()
                return

        # 处理前检查取消
        if self._check_cancelled():
            return

        # Skill 匹配：惰性加载完整内容并增强用户输入
        if self._skill_matcher:
            enhanced_input, matched_skill = self._skill_matcher.match(user_input)
            if matched_skill:
                await self.tui.show_status(f"Activating skill: {matched_skill.name}")
                user_input = enhanced_input

        # 阶段 4: 主动上下文检索
        if self.context_retriever:
            attached = self.context_retriever.attach_context(user_input)
            if attached:
                builder = self.context.prompt_builder
                current_memory = builder.get_section("memory") or ""
                builder.update_section("memory", f"{current_memory}\n\n{attached}")

        self.context.add_message(UserMessage(content=user_input))

        # 阶段 2: 用户输入后保存检查点
        self._save_checkpoint("user_input", user_input=user_input)

        iteration = 0
        while self.state_machine.current not in ("done", "error") and iteration < self.max_iterations:
            iteration += 1

            # 循环边界检查取消
            if self._check_cancelled():
                return

            # 检查是否需要压缩
            if self.context.needs_compaction():
                try:
                    self.state_machine.transition("compact")
                except Exception:
                    self.state_machine.force("compact")
                self._sync_legacy_state()
                await self.tui.show_status("Compressing context...")
                await self.context.compact(self.llm)

            # 构建 LLM 消息
            messages = self.context.build_messages()
            tools = self.registry.get_tool_definitions()

            # 阶段 1+2: 构建结构化系统提示
            system_prompt = self.context.build_system_prompt()

            # 阶段 2: LLM 调用前保存检查点
            self._save_checkpoint("before_llm", iteration=iteration)

            # 流式调用 LLM
            try:
                self.state_machine.transition("thinking")
            except Exception:
                self.state_machine.force("thinking")
            self._sync_legacy_state()
            await self.tui.start_thinking()

            full_content = ""
            tool_calls = []
            last_response = None

            async for response in self.llm.stream(
                messages=messages, tools=tools, system=system_prompt
            ):
                # 阶段 3: 流式输出期间检查取消
                if self._cancel_event.is_set():
                    await self.tui.stop_thinking()
                    await self.tui.show_status("Interrupted by user")
                    await self._graceful_stop(user_input, iteration)
                    return

                if response.content:
                    full_content += response.content
                    await self.tui.show_token(response.content)
                if response.tool_calls:
                    tool_calls.extend(response.tool_calls)
                last_response = response

            await self.tui.stop_thinking()

            # 用 API 返回的实际 token 数校准计数器
            if last_response and last_response.usage:
                self.context.calibrate_from_api_response(last_response.usage)

            # 处理工具调用
            if tool_calls:
                try:
                    self.state_machine.transition("acting")
                except Exception:
                    self.state_machine.force("acting")
                self._sync_legacy_state()
                if full_content:
                    self.context.add_message(AssistantMessage(content=full_content))

                # 阶段 4: 在追踪器中注册所有工具
                for tc in tool_calls:
                    self.tool_tracker.create(tc.id, tc.name, tc.input)

                for tc in tool_calls:
                    # 每个工具执行前检查取消
                    if self._check_cancelled():
                        # 取消剩余待执行的工具
                        for remaining in self.tool_tracker.pending():
                            self.tool_tracker.cancel(remaining.id)
                        return

                    await self.tui.show_tool_start(tc.name, tc.input)
                    self.tool_tracker.start(tc.id)

                    # Trigger pre-tool-use hooks
                    if self.hook_engine:
                        hook_ctx = {
                            "tool_name": tc.name,
                            "tool_input": json.dumps(tc.input),
                        }
                        hook_result = await self.hook_engine.trigger(
                            HookType.PRE_TOOL_USE, hook_ctx
                        )
                        if hook_result.blocked:
                            await self.tui.show_status(f"Hook blocked {tc.name}: {hook_result.reason}")
                            self.tool_tracker.fail(tc.id, "Hook blocked")
                            continue

                    # 权限检查
                    decision = await self.permission.check(tc)
                    if decision.value == "deny":
                        result_content = f"Permission denied for tool: {tc.name}"
                        await self.tui.show_tool_end(tc.name, "denied")
                        self.tool_tracker.fail(tc.id, "Permission denied")
                    else:
                        result = await self._execute_tool(tc)
                        result_content = result.content
                        status = "done" if not result.is_error else "error"
                        await self.tui.show_tool_end(tc.name, status)

                        if result.is_error:
                            self.tool_tracker.fail(tc.id, result_content)
                        else:
                            self.tool_tracker.complete(tc.id, result_content)

                    # 触发工具使用后钩子
                        if self.hook_engine:
                            await self.hook_engine.trigger(
                                HookType.POST_TOOL_USE,
                                {
                                    "tool_name": tc.name,
                                    "tool_input": json.dumps(tc.input),
                                    "tool_output": result_content,
                                    "status": status,
                                },
                            )

                    # 将工具结果加入历史
                    tool_msg = ToolResultMessage(
                        content=result_content if not result.is_error else f"Error: {result_content}",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                    )
                    self.context.add_message(tool_msg)

                    # 阶段 2: 每个工具执行后保存检查点
                    self._save_checkpoint("tool_done", iteration=iteration)

                # 继续循环：将工具结果返回给 LLM
                continue

            # 文本响应 → 验证 → 完成
            if full_content:
                try:
                    self.state_machine.transition("verifying")
                except Exception:
                    self.state_machine.force("verifying")
                self._sync_legacy_state()
                self.context.add_message(AssistantMessage(content=full_content))

                # 触发响应后钩子
                if self.hook_engine:
                    await self.hook_engine.trigger(
                        HookType.POST_RESPONSE,
                        {"response": full_content},
                    )

                try:
                    self.state_machine.transition("done")
                except Exception:
                    self.state_machine.force("done")
                self._sync_legacy_state()
                break

        # 正常完成
        try:
            self.state_machine.transition("done")
        except Exception:
            self.state_machine.force("done")
        self._sync_legacy_state()

        # 触发用户消息后钩子
        if self.hook_engine:
            await self.hook_engine.trigger(
                HookType.POST_USER_MESSAGE,
                {"user_input": user_input, "state": self.state.value},
            )

        # 自动保存会话
        self._save_session()

        # 成功完成后清除检查点
        self.checkpoint.clear()

    async def _graceful_stop(self, user_input: str, iteration: int) -> None:
        """取消时保存状态并转换到完成"""
        self.state_machine.force("done")
        self._sync_legacy_state()
        self._save_session()
        # 保留检查点以便用户恢复

    def _save_checkpoint(
        self,
        phase: str = "",
        user_input: str = "",
        iteration: int = 0,
    ) -> None:
        """保存当前状态到检查点文件"""
        messages = [msg.model_dump() for msg in self.context.messages]
        self.checkpoint.save(
            state=self.state_machine.current,
            messages=messages,
            session_id=self._current_session_id,
            user_input=user_input or self._current_user_input,
            iteration=iteration,
            tool_executions=self.tool_tracker.to_dicts(),
        )

    async def resume(self) -> bool:
        """
        从最新检查点恢复。

        返回 True 表示找到并加载了检查点，False 表示没有。
        """
        cp = self.checkpoint.load_latest()
        if cp is None:
            return False

        # 恢复会话 ID
        self._current_session_id = cp["session_id"]

        # 恢复消息历史
        from nexusagent.models import (
            AssistantMessage,
            SystemMessage,
            ToolResultMessage,
            UserMessage,
        )

        self.context.messages.clear()
        for msg_data in cp["messages"]:
            role = msg_data.get("role", "")
            content = msg_data.get("content", "")
            if role == "user":
                # Check if it's a tool result
                if isinstance(content, list) and content:
                    item = content[0]
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        self.context.messages.append(ToolResultMessage(
                            content=str(item.get("content", "")),
                            tool_call_id=item.get("tool_use_id", ""),
                            tool_name="",
                        ))
                        continue
                self.context.messages.append(UserMessage(content=content))
            elif role == "assistant":
                self.context.messages.append(AssistantMessage(content=content))
            elif role == "system":
                self.context.messages.append(SystemMessage(content=content))

        # 重新计算 token 数量
        self.context.total_token_count = sum(
            m.token_count for m in self.context.messages
        )

        return True

    async def _execute_tool(self, tool_call: ToolCall):
        """执行工具调用并返回结果"""
        tool = self.registry.get(tool_call.name)
        if not tool:
            return ToolResult(
                content=f"Unknown tool: {tool_call.name}", is_error=True
            )

        try:
            args = tool_call.input
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"command": args} if tool_call.name == "Bash" else {}

            return await tool.execute(**args)
        except Exception as e:
            return ToolResult(content=f"Tool error: {e}", is_error=True)

    def _save_session(self):
        """保存当前对话到会话文件"""
        messages = [msg.model_dump() for msg in self.context.messages]
        self.session_manager.save(self._current_session_id, messages)

    def reset(self):
        """重置 Agent 状态以开始新会话"""
        self.state_machine.reset()
        self._sync_legacy_state()
        self.context.reset()
        self.tool_tracker.reset()
        self._cancel_event.clear()
        self._current_session_id = self.session_manager.create_session_id()
