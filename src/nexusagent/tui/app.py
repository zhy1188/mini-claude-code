"""NexusAgent Terminal UI: Rich-based REPL with slash commands and history."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel


class NexusTUI:
    """Rich-based terminal interface with slash commands and command history."""

    def __init__(self, console: Console | None = None, history_file: str | None = None):
        self.console = console or Console(force_terminal=True, encoding="utf-8")
        self._live = None
        self._buffer = ""
        self._session: PromptSession | None = None
        self._history_file = history_file or str(Path(".nexus") / "history")
        self._commands: dict[str, callable] = {}

    def register_command(self, name: str, handler: callable, description: str = ""):
        """Register a slash command."""
        self._commands[name] = (handler, description)

    def print_banner(
        self, model: str, provider: str, workdir: Path
    ) -> None:
        """Print startup banner."""
        cmd_list = "\n".join(
            f"  [dim]/{name}[/dim] - {desc}"
            for name, (_, desc) in sorted(self._commands.items())
        )
        banner = (
            f"[bold cyan]NexusAgent[/bold cyan] v0.1.0\n"
            f"Model: {model} ({provider})\n"
            f"Working directory: {workdir}\n"
            f"Type 'quit' or 'exit' to leave.\n\n"
            f"[bold]Slash Commands:[/bold]\n"
            f"{cmd_list or '  (none)'}"
        )
        self.console.print(Panel(banner, title="Welcome", border_style="cyan"))
        self.console.print()

    def _get_session(self) -> PromptSession:
        """Get or create a prompt_toolkit session with history."""
        if self._session is None:
            Path(self._history_file).parent.mkdir(parents=True, exist_ok=True)
            self._session = PromptSession(
                history=FileHistory(self._history_file),
            )
        return self._session

    async def start_repl(self, agent) -> None:
        """Start the REPL loop with slash command support."""
        self.console.print(
            Panel(
                "NexusAgent REPL\n"
                "Type your request and press Enter. Use /help for commands.",
                border_style="blue",
            )
        )

        session = self._get_session()

        while True:
            self.console.print()
            try:
                answer = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: session.prompt("\n[bold green]> [/bold green]")
                )
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]Goodbye![/dim]")
                break

            answer = answer.strip()
            if not answer:
                continue
            if answer.lower() in ("quit", "exit", "q"):
                self.console.print("[dim]Goodbye![/dim]")
                break

            # Handle slash commands
            if answer.startswith("/"):
                await self._handle_command(answer, agent)
                continue

            await agent.run(answer)
            self.console.print()

    async def _handle_command(self, cmd: str, agent) -> None:
        """Parse and execute a slash command."""
        parts = cmd[1:].split(maxsplit=1)
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if name == "help":
            cmd_list = "\n".join(
                f"  /{n:12s} - {d}" for n, (_, d) in sorted(self._commands.items())
            )
            self.console.print(Panel(cmd_list or "(no commands)", title="Commands"))
        elif name in self._commands:
            handler, _ = self._commands[name]
            await handler(args, agent)
        else:
            self.console.print(f"[red]Unknown command: /{name}[/red]")

    async def show_status(self, text: str) -> None:
        """Show a status message."""
        self.console.print(f"[dim]{text}[/dim]")

    async def start_thinking(self) -> None:
        """Show thinking indicator."""
        self._buffer = ""
        self._live = Live(
            Panel("[dim]Thinking...[/dim]", border_style="yellow"),
            console=self.console,
            refresh_per_second=4,
        )
        self._live.start()

    async def show_token(self, token: str) -> None:
        """Show a streamed token in the thinking panel."""
        self._buffer += token
        if self._live:
            self._live.update(
                Panel(Markdown(self._buffer), title="Thinking", border_style="yellow")
            )

    async def stop_thinking(self) -> None:
        """Stop the thinking indicator."""
        if self._live:
            self._live.stop()
            self._live = None
            self.console.print()

    async def show_tool_start(self, name: str, args: dict) -> None:
        """Show tool execution starting."""
        self.console.print(
            Panel(
                f"[bold]{name}[/bold]\n{args}",
                title="Tool Call",
                border_style="yellow",
            )
        )

    async def show_tool_end(self, name: str, status: str) -> None:
        """Show tool execution completed."""
        icon = {"done": "done", "error": "failed", "denied": "denied"}.get(status, status)
        style = {"done": "green", "error": "red", "denied": "yellow"}.get(status, "dim")
        self.console.print(f"[{style}]{name}: {icon}[/{style}]")
