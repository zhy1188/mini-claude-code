"""Context manager: token budgeting, compaction, message lifecycle."""

from __future__ import annotations

from nexusagent.context.builder import PromptBuilder
from nexusagent.context.compaction import CompactionStrategy
from nexusagent.context.tokenizer import TokenCounter
from nexusagent.llm.base import LLMClient
from nexusagent.models import AssistantMessage, Message, SystemMessage, ToolResultMessage


class ContextManager:
    """
    管理 LLM 上下文窗口生命周期。

    核心策略:
        1. Token 预算追踪 + API 校准
        2. 渐进式压缩 3 个阶段:
           - 阶段 1 (< 85%): 软压缩 - 移除旧文本，保留工具结果
           - 阶段 2 (85-95%): LLM 摘要，保留关键消息
           - 阶段 3 (>= 95%): 极端压缩 - 摘要 + 仅 2 条最新
        3. 预测性压缩: 添加工具结果后检查
        4. 结构化系统提示通过 PromptBuilder
    """

    def __init__(
        self,
        max_tokens: int = 200_000,
        compact_threshold: float = 0.75,
        compact_strategy: str = "llm_summary",
        provider: str = "anthropic",
    ):
        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold
        self.compaction = CompactionStrategy(compact_strategy)
        self.tokenizer = TokenCounter()
        self.messages: list[Message] = []
        self.provider = provider

        # 结构化提示构建器
        self.prompt_builder = PromptBuilder()
        self.total_token_count: int = 0

        # LLM 引用用于预测性压缩（由 MasterAgent 设置）
        self._llm_ref: LLMClient | None = None

    def set_llm_ref(self, llm: LLMClient) -> None:
        """存储 LLM 引用用于预测性压缩"""
        self._llm_ref = llm

    def add_message(self, message: Message) -> None:
        """添加消息并更新 token 计数"""
        message.token_count = self.tokenizer.count(message.content)
        self.messages.append(message)
        self.total_token_count += message.token_count

        # 如果消息有实际 token 数，校准计数器
        if message.metadata and "actual_tokens" in message.metadata:
            self.tokenizer.calibrate(message.content, message.metadata["actual_tokens"])

    def add_message_with_calibration(self, message: Message, actual_tokens: int) -> None:
        """添加已知 token 数的消息（来自 API 响应）"""
        message.token_count = actual_tokens
        self.messages.append(message)
        self.total_token_count += actual_tokens
        self.tokenizer.calibrate(message.content, actual_tokens)

    def calibrate_from_api_response(self, usage: dict) -> None:
        """使用 LLM API 使用数据校准 token 计数器"""
        if usage and "input_tokens" in usage:
            # 用实际计数校准当前总上下文
            actual = usage.get("input_tokens", 0)
            if actual > 0:
                estimated = self.total_token_count
                # 根据误差比率调整未来估计
                self.total_token_count = actual

    def build_messages(self) -> list[dict]:
        """构建 LLM API 格式的消息列表，适配不同提供商"""
        result = []
        for msg in self.messages:
            if isinstance(msg, ToolResultMessage) and self.provider != "anthropic":
                # OpenAI-compatible format
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
            else:
                result.append(msg.to_api_format())
        return result

    def build_system_prompt(self) -> str | list[dict]:
        """
        构建系统提示。

        Anthropic 提供商: 返回带 cache_control 的内容块列表
        其他提供商: 返回纯文本字符串
        """
        result = self.prompt_builder.build()
        if self.provider == "anthropic":
            return result["blocks"]
        return result["text"]

    def needs_compaction(self) -> bool:
        """检查上下文是否超过压缩阈值"""
        self.total_token_count = sum(m.token_count for m in self.messages)
        return self.total_token_count > self.max_tokens * self.compact_threshold

    def _get_compaction_phase(self) -> int:
        """
        根据 token 比率确定压缩阶段。

        阶段 1 (< 0.85): 软压缩 - 丢弃旧文本，保留工具结果
        阶段 2 (0.85 - 0.95): 摘要压缩 - LLM 摘要，保留关键
        阶段 3 (>= 0.95): 极端压缩 - 摘要 + 仅最近 2 条
        """
        ratio = self.total_token_count / self.max_tokens
        if ratio >= 0.95:
            return 3
        elif ratio >= 0.85:
            return 2
        return 1

    async def compact(self, llm: LLMClient) -> None:
        """
        执行渐进式上下文压缩。

        阶段选择基于接近 token 限制的程度:
          阶段 1: 移除最旧的非关键文本消息
          阶段 2: LLM 摘要压缩，保留关键消息
          阶段 3: 极端压缩 - 摘要 + 仅 2 条最新
        """
        if not self.messages:
            return

        phase = self._get_compaction_phase()

        if phase == 1:
            self._soft_compact()
        elif phase == 2:
            await self._summarize_compact(llm)
        else:
            await self._extreme_compact(llm)

    def _soft_compact(self) -> None:
        """
        阶段 1: 软压缩
        移除最旧的非关键纯文本消息，保留所有工具结果
        """
        if len(self.messages) <= 6:
            return

        # 查找并移除最旧的非关键、非工具消息
        kept = []
        removed_count = 0
        target_remove = min(2, len(self.messages) - 6)  # Remove up to 2 messages

        for msg in self.messages:
            if removed_count < target_remove and not self.compaction.is_critical(msg):
                if not hasattr(msg, "tool_name") or not getattr(msg, "tool_name", None):
                    self.total_token_count -= msg.token_count
                    removed_count += 1
                    continue
            kept.append(msg)

        if removed_count > 0:
            self.messages = kept

    async def _summarize_compact(self, llm: LLMClient) -> None:
        """
        阶段 2: 摘要压缩
        LLM 总结旧消息，同时保留关键消息
        """
        critical = self._extract_critical_messages()
        compressible = self._get_compressible_messages()

        if not compressible:
            return

        # LLM 压缩
        summary = await self.compaction.compress(
            llm, compressible, strategy=self.compaction.strategy
        )

        # 重建: 摘要 + 关键消息
        self.messages = [
            AssistantMessage(content=f"[Context Compaction Summary]\n{summary}"),
            *critical,
        ]
        self.total_token_count = sum(m.token_count for m in self.messages)

    async def _extreme_compact(self, llm: LLMClient) -> None:
        """
        阶段 3: 极端压缩
        只保留系统提示 + LLM 摘要 + 2 条最新消息
        """
        # Keep only the last 2 messages
        recent = self.messages[-2:] if len(self.messages) > 2 else self.messages

        if len(self.messages) > 2:
            compressible = self.messages[:-2]
            summary = await self.compaction.compress(
                llm, compressible, strategy=self.compaction.strategy
            )
            self.messages = [
                AssistantMessage(content=f"[Context Compaction Summary]\n{summary}"),
                *recent,
            ]
        self.total_token_count = sum(m.token_count for m in self.messages)

    def _extract_critical_messages(self) -> list[Message]:
        """提取不应被压缩的消息"""
        critical = []
        # 始终保留最近的消息（最后 4 条）
        for msg in self.messages[-4:]:
            critical.append(msg)
        # 同时保留早期关键工具结果
        for msg in self.messages[:-4]:
            if self.compaction.is_critical(msg) and msg not in critical:
                critical.append(msg)
        return critical

    def _get_compressible_messages(self) -> list[Message]:
        """获取可压缩的消息（旧的、非关键历史）"""
        critical_set = set(id(m) for m in self._extract_critical_messages())
        return [m for m in self.messages if id(m) not in critical_set]

    def reset(self) -> None:
        """清空所有消息"""
        self.messages = []
        self.total_token_count = 0

    @property
    def strategy(self) -> str:
        return self.compaction.strategy
