"""NexusAgent launcher: initializes all components and starts the REPL."""

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from nexusagent.config import load_config
from nexusagent.context.builder import PromptBuilder
from nexusagent.context.manager import ContextManager
from nexusagent.context.retriever import ContextRetriever
from nexusagent.llm.anthropic import AnthropicClient
from nexusagent.llm.openai_compat import OpenAICompatibleClient
from nexusagent.permission.gate import PermissionGate
from nexusagent.permission.policy import TrustPolicy
from nexusagent.tools.builtin.bash import BashTool
from nexusagent.tools.builtin.glob import GlobTool
from nexusagent.tools.builtin.grep import GrepTool
from nexusagent.tools.builtin.read import ReadTool
from nexusagent.tools.builtin.task import TaskTool
from nexusagent.tools.builtin.write import WriteTool
from nexusagent.tools.mcp.bridge import MCPBridge
from nexusagent.tools.registry import ToolRegistry
from nexusagent.tui.app import NexusTUI


async def _run_async(workdir: Path, config, console: Console):
    """Async REPL loop runner."""
    # Initialize LLM client
    if config.llm.provider == "anthropic":
        llm = AnthropicClient(
            model=config.llm.model,
            api_key=config.llm.api_key,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            thinking_budget=config.llm.thinking_budget,
        )
    else:
        llm = OpenAICompatibleClient(
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
        )

    # Initialize tool registry
    registry = ToolRegistry()
    registry.register(ReadTool(workdir))
    registry.register(WriteTool(workdir))
    registry.register(BashTool(workdir, config.bash))
    registry.register(GlobTool(workdir))
    registry.register(GrepTool(workdir))
    registry.register(TaskTool(workdir))

    # ── Phase 2: MCP Bridge ────────────────────────────────────────
    mcp_bridge = MCPBridge(registry)
    for server_name, command in config.mcp.items():
        await mcp_bridge.connect_server(server_name, command)

    # Initialize context manager
    context_mgr = ContextManager(
        max_tokens=config.context.max_tokens,
        compact_threshold=config.context.compact_threshold,
        compact_strategy=config.context.compact_strategy,
        provider=config.llm.provider,
    )

    # ── Phase 1: Structured Prompt Builder ──────────────────────────
    builder = context_mgr.prompt_builder

    # Load project context (.nexus.md + hierarchy)
    from nexusagent.context.project_context import load_hierarchy_context

    hierarchy_ctx = load_hierarchy_context(workdir, workdir)
    if hierarchy_ctx:
        builder.update_section("project", hierarchy_ctx)

    # Load cross-session memory
    from nexusagent.memory.memory import MemorySystem

    memory = MemorySystem(workdir / ".nexus" / "memory", max_entries_per_type=config.memory.max_memories_per_type)
    memory_content = memory.load_all()
    if memory_content:
        builder.update_section("memory", memory_content)

    # Initialize skill system
    from nexusagent.skills.registry import SkillRegistry

    skill_registry = SkillRegistry()
    skill_registry.add_directory(workdir / ".nexus" / "skills", scope="project")
    skill_registry.add_directory(
        Path.home() / ".nexus" / "skills", scope="global"
    )
    skill_registry.scan()

    # Inject skill list into system prompt (lazy loading: only names + descriptions)
    if skill_registry.skills:
        skill_list = "\n".join(
            f"- /{s.name}: {s.description}" for s in skill_registry.list_skills()
        )
        builder.update_section("skills", (
            f"Available skills. When the user triggers one via /name or mentions it, "
            f"follow the skill's instructions:\n\n{skill_list}"
        ))

    # Initialize permission system
    trust_policy = TrustPolicy.from_config(config)
    permission_gate = PermissionGate(trust_policy, console=console)

    # Initialize context retriever (Phase 4)
    context_retriever = ContextRetriever(workdir)

    # Initialize TUI
    tui = NexusTUI(console, history_file=str(workdir / ".nexus" / "history"))

    # Register slash commands
    async def cmd_config(args, agent):
        """Show current configuration."""
        tui.console.print(Panel(
            f"[bold]Model:[/bold] {config.llm.model}\n"
            f"[bold]Provider:[/bold] {config.llm.provider}\n"
            f"[bold]Max Tokens:[/bold] {config.llm.max_tokens}\n"
            f"[bold]Thinking Budget:[/bold] {config.llm.thinking_budget}\n"
            f"[bold]Context Max:[/bold] {config.context.max_tokens}\n"
            f"[bold]Compact Threshold:[/bold] {config.context.compact_threshold}\n"
            f"[bold]Tools:[/bold] {', '.join(t.name for t in registry.get_all())}",
            title="Config",
        ))

    async def cmd_model(args, agent):
        """Switch model (e.g., /model qwen-max)."""
        if args:
            config.llm.model = args
            tui.console.print(f"[green]Model changed to: {args}[/green]")
        else:
            tui.console.print(f"Current model: {config.llm.model}")

    async def cmd_compact(args, agent):
        """Force context compaction."""
        count = len(agent.context.messages)
        await agent.context.compact(agent.llm)
        new_count = len(agent.context.messages)
        tui.console.print(
            f"[green]Compacted: {count} → {new_count} messages[/green]"
        )

    async def cmd_memory(args, agent):
        """Show cross-session memory."""
        result = await agent.memory_write_tool.execute(operation="list")
        tui.console.print(Panel(
            result.content,
            title="Memory",
        ))

    async def cmd_forget(args, agent):
        """Forget a memory: /forget <name> --type <type>"""
        parts = args.split()
        if not parts:
            tui.console.print("[red]Usage: /forget <name> --type <type>[/red]")
            return
        name = parts[0]
        memory_type = "user"
        if "--type" in parts:
            idx = parts.index("--type")
            if idx + 1 < len(parts):
                memory_type = parts[idx + 1]
        result = await agent.memory_write_tool.execute(
            operation="forget", name=name, memory_type=memory_type
        )
        style = "red" if result.is_error else "green"
        tui.console.print(f"[{style}]{result.content}[/{style}]")

    async def cmd_memstats(args, agent):
        """Show memory count by type."""
        from nexusagent.memory.index import MemoryIndex
        idx = MemoryIndex(agent.workdir / ".nexus")
        counts = {}
        for mem_type in idx.VALID_TYPES:
            count = len(idx.list_entries(mem_type))
            counts[mem_type] = count
        lines = [f"  {t}: {counts[t]} memories" for t in idx.VALID_TYPES]
        total = sum(counts.values())
        lines.append(f"\n  [bold]Total: {total}[/bold]")
        tui.console.print(Panel("\n".join(lines), title="Memory Stats"))

    async def cmd_hooks(args, agent):
        """Show registered hooks."""
        if agent.hook_engine:
            hooks = agent.hook_engine.hooks
            tui.console.print(Panel(
                str(hooks) if hooks else "(no hooks registered)",
                title="Hooks",
            ))
        else:
            tui.console.print("[dim]No hook engine registered[/dim]")

    tui.register_command("config", cmd_config, "Show configuration")
    tui.register_command("model", cmd_model, "Switch model")
    tui.register_command("compact", cmd_compact, "Force context compaction")
    tui.register_command("memory", cmd_memory, "Show cross-session memory")
    tui.register_command("forget", cmd_forget, "Forget a memory")
    tui.register_command("memstats", cmd_memstats, "Memory count by type")
    tui.register_command("hooks", cmd_hooks, "Show registered hooks")

    # Register /skills command to list all loaded skills
    async def cmd_skills(args, agent):
        """List all loaded skills."""
        skills = skill_registry.list_skills()
        if skills:
            skill_list = "\n".join(
                f"  [bold]/{s.name}[/bold] - {s.description}"
                for s in skills
            )
            tui.console.print(Panel(skill_list, title="Skills"))
        else:
            tui.console.print("[dim]No skills loaded[/dim]")

    tui.register_command("skills", cmd_skills, "List all loaded skills")

    # Print banner
    tui.print_banner(
        model=config.llm.model,
        provider=config.llm.provider,
        workdir=workdir,
    )

    # Start REPL
    from nexusagent.agent.master import MasterAgent

    agent = MasterAgent(
        llm_client=llm,
        tool_registry=registry,
        context_manager=context_mgr,
        permission_gate=permission_gate,
        tui=tui,
        workdir=workdir,
        context_retriever=context_retriever,
        skill_registry=skill_registry,
        max_iterations=config.agent.max_iterations,
        max_duration_minutes=config.agent.max_duration_minutes,
        max_memories_per_type=config.memory.max_memories_per_type,
    )

    # 设置子智能体超时
    agent.orchestrator.timeout_seconds = config.agent.sub_agent_timeout_seconds

    # Start REPL with cleanup
    try:
        await tui.start_repl(agent)
    finally:
        await mcp_bridge.disconnect_all()


def main():
    parser = argparse.ArgumentParser(description="NexusAgent - AI coding assistant")
    parser.add_argument("workdir", nargs="?", default=".", help="Working directory")
    parser.add_argument("-c", "--config", default=None, help="Config file path")
    parser.add_argument("--model", default=None, help="Override model name")
    parser.add_argument(
        "--provider", default=None, choices=["anthropic", "openai"], help="LLM provider"
    )
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    console = Console()

    # Load config
    config_path = Path(args.config) if args.config else workdir / "nexus.toml"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent.parent / "nexus.toml"
    config = load_config(config_path)

    # CLI overrides
    if args.model:
        config.llm.model = args.model
    if args.provider:
        config.llm.provider = args.provider

    # Run async REPL
    asyncio.run(_run_async(workdir, config, console))


if __name__ == "__main__":
    main()
