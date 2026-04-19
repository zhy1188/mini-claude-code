"""Basic example: using NexusAgent programmatically."""

import asyncio
from pathlib import Path

from nexusagent.config import load_config, BashConfig
from nexusagent.context.manager import ContextManager
from nexusagent.llm.anthropic import AnthropicClient
from nexusagent.permission.gate import PermissionGate
from nexusagent.permission.policy import TrustPolicy
from nexusagent.tools.builtin.bash import BashTool
from nexusagent.tools.builtin.glob import GlobTool
from nexusagent.tools.builtin.grep import GrepTool
from nexusagent.tools.builtin.read import ReadTool
from nexusagent.tools.builtin.write import WriteTool
from nexusagent.tools.registry import ToolRegistry
from nexusagent.agent.master import MasterAgent


async def main():
    config = load_config()

    # Initialize components
    llm = AnthropicClient(
        model=config.llm.model,
        api_key=config.llm.api_key,
        max_tokens=config.llm.max_tokens,
    )

    registry = ToolRegistry()
    workdir = Path(".")
    registry.register(ReadTool(workdir))
    registry.register(WriteTool(workdir))
    registry.register(BashTool(workdir, config.bash))
    registry.register(GlobTool(workdir))
    registry.register(GrepTool(workdir))

    context_mgr = ContextManager(
        max_tokens=config.context.max_tokens,
        compact_threshold=config.context.compact_threshold,
    )

    trust_policy = TrustPolicy.from_config(config)
    permission_gate = PermissionGate(trust_policy)

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        context_manager=context_mgr,
        permission_gate=permission_gate,
    )

    # Run a single turn
    await agent.run("Read the README.md file and summarize it")


if __name__ == "__main__":
    asyncio.run(main())
