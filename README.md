# NexusAgent

A Claude Code-inspired AI coding agent, built in Python.

## Architecture

NexusAgent implements the core patterns of Claude Code:

- **Agentic Loop**: Single-threaded master loop (Gather → Act → Verify)
- **Tool System**: Extensible tools via JSON Schema, with MCP bridge support
- **Context Management**: Token budgeting, LLM-based compaction, .nexus.md project context
- **Permission System**: Declarative trust policy per tool
- **Sub-Agent Orchestration**: Concurrent sub-agents with isolated contexts
- **Hooks**: Lifecycle hooks for extensibility (pre/post tool use, etc.)
- **Session Memory**: Persistent conversation history and cross-session memory

## Project Structure

```
src/nexusagent/
├── agent/          Master loop, sub-agents, orchestrator
├── tools/          Built-in tools + MCP bridge
├── context/        Context management, compaction, token counting
├── llm/            Anthropic + OpenAI-compatible clients
├── permission/     Trust policy + permission gate
├── hooks/          Lifecycle hook engine
├── memory/         Session persistence + cross-session memory
└── tui/            Rich-based terminal interface
```

## Quick Start

```bash
# Install dependencies
pip install -e .

# Set API key
export ANTHROPIC_API_KEY=your_key_here

# Run
python -m nexusagent
```

## Configuration

See `nexus.toml` for all configuration options.

## .nexus.md

Place a `.nexus.md` file in your project root to provide project context
(similar to CLAUDE.md in Claude Code). This is automatically loaded
into the system prompt.
