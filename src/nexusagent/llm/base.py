"""Abstract LLM client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from nexusagent.models import LLMResponse


class LLMClient(ABC):
    """LLM 客户端抽象基类。支持 Anthropic 和 OpenAI 兼容 API。"""

    @abstractmethod
    async def stream(
        self, messages: list[dict], tools: list[dict], system: str
    ) -> AsyncIterator[LLMResponse]:
        """
        流式获取 LLM 响应。
        Token 到达时产生部分 LLMResponse 对象。
        最终响应包含完整内容和所有工具调用。
        """
        ...

    @abstractmethod
    async def compress_messages(self, messages: list[dict]) -> str:
        """
        将消息列表压缩为摘要。
        用于上下文压缩。
        """
        ...
