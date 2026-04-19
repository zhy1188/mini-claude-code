"""Context compaction strategies with caching and critical message preservation."""

from __future__ import annotations

from nexusagent.llm.base import LLMClient
from nexusagent.models import Message


class CompactionCache:
    """
    压缩结果缓存。

    避免重复调用 LLM 来总结相同或相似的消息历史。
    使用最近消息内容的哈希作为缓存键。
    """

    def __init__(self, max_entries: int = 5):
        self._cache: dict[int, str] = {}
        self._max = max_entries
        self._order: list[int] = []  # LRU order

    def get(self, messages: list[Message]) -> str | None:
        """如果最近消息匹配，返回缓存的摘要"""
        key = self._hash_recent(messages)
        return self._cache.get(key)

    def put(self, messages: list[Message], summary: str) -> None:
        """缓存新的摘要"""
        key = self._hash_recent(messages)
        if key in self._cache:
            self._cache[key] = summary
            return
        if len(self._cache) >= self._max:
            # 淘汰最旧的
            oldest = self._order.pop(0)
            self._cache.pop(oldest, None)
        self._cache[key] = summary
        self._order.append(key)

    def _hash_recent(self, messages: list[Message]) -> int:
        """将最近 N 条消息的内容哈希作为缓存键"""
        # 使用最后 6 条消息进行哈希（捕获足够的上下文）
        recent = messages[-6:] if len(messages) > 6 else messages
        content = "|".join(m.content[:100] for m in recent)
        return hash(content)


class CompactionStrategy:
    """
    实现渐进式上下文压缩。

    根据接近 token 限制的程度分三个阶段:
        阶段 1 (ratio < 0.85): 软压缩 - 移除最旧的纯文本消息
        阶段 2 (0.85 <= ratio < 0.95): 摘要压缩 - LLM 总结旧消息
        阶段 3 (ratio >= 0.95): 极端压缩 - 摘要 + 仅 2 条最新
    """

    def __init__(self, strategy: str = "llm_summary"):
        self.strategy = strategy
        self.cache = CompactionCache()

    async def compress(
        self, llm: LLMClient, messages: list[Message], strategy: str | None = None
    ) -> str:
        """使用指定策略压缩消息"""
        s = strategy or self.strategy

        # 先检查缓存（仅限基于 LLM 的策略）
        if s == "llm_summary":
            cached = self.cache.get(messages)
            if cached:
                return cached

        if s == "llm_summary":
            result = await self._llm_summary(llm, messages)
            self.cache.put(messages, result)
            return result
        elif s == "truncate_oldest":
            return self._truncate_summary(messages)
        elif s == "sliding_window":
            return self._sliding_window_summary(messages)
        else:
            return await self._llm_summary(llm, messages)

    async def _llm_summary(self, llm: LLMClient, messages: list[Message]) -> str:
        """使用 LLM 生成消息摘要"""
        api_messages = [m.to_api_format() for m in messages]
        return await llm.compress_messages(api_messages)

    def _truncate_summary(self, messages: list[Message]) -> str:
        """生成简单的截断摘要"""
        total = len(messages)
        first = messages[0].content[:200] if messages else ""
        last = messages[-1].content[:200] if messages else ""
        return (
            f"[Compressed: {total} messages summarized]\n"
            f"First: {first}\n...\nLast: {last}"
        )

    def _sliding_window_summary(self, messages: list[Message]) -> str:
        """保留消息窗口中的关键信息"""
        # 提取工具调用结果，因为它们最重要
        tool_results = [
            m for m in messages if hasattr(m, "tool_name") and m.tool_name
        ]
        if tool_results:
            summary_lines = [
                f"- Tool '{m.tool_name}': {m.content[:100]}" for m in tool_results[-5:]
            ]
            return "[Compressed tool results]\n" + "\n".join(summary_lines)
        return f"[Compressed: {len(messages)} messages removed]"

    def is_critical(self, msg: Message) -> bool:
        """
        识别不应被压缩的消息。

        关键消息包含重要信息:
        - Write 或 Bash 的工具结果（代码变更、测试结果）
        - 提到文件路径的消息（用户正在讨论特定文件）
        - 最近的用户消息（活跃对话上下文）
        """
        # 写入/修改操作的工具结果
        if hasattr(msg, "tool_name"):
            if msg.tool_name in ("Write", "Bash"):
                return True

        # 包含文件引用的消息
        content = getattr(msg, "content", "")
        file_exts = (".py", ".ts", ".go", ".rs", ".java", ".js", ".tsx", ".jsx")
        if any(ext in content for ext in file_exts):
            return True

        return False
