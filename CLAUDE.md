# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nanobot is an ultra-lightweight personal AI assistant framework (~4,000 lines of core agent code). It provides a multi-channel AI assistant that can interact via CLI, Telegram, Discord, Slack, WhatsApp, Feishu, Matrix, QQ, DingTalk, and Email.

## Development Commands

```bash
# Install in development mode
pip install -e .

# Run tests
pytest

# Run a single test file
pytest tests/test_loop_save_turn.py

# Run a specific test
pytest tests/test_loop_save_turn.py::test_save_turn_truncates_tool_result

# Lint code
ruff check nanobot/

# Format code
ruff format nanobot/

# Run CLI agent
nanobot agent -m "Hello!"

# Run interactive chat
nanobot agent

# Start gateway (connects to chat channels)
nanobot gateway

# Initialize config
nanobot onboard
```

## Architecture Overview

```
nanobot/
├── agent/           # Core agent logic
│   ├── loop.py      # Agent loop (LLM ↔ tool execution)
│   ├── context.py   # Prompt builder
│   ├── memory.py    # Persistent memory consolidation
│   ├── skills.py    # Skills loader
│   └── tools/       # Built-in tools (shell, filesystem, web, cron, mcp, message, spawn)
├── bus/             # Message routing (InboundMessage → OutboundMessage)
├── channels/        # Chat channel integrations (inherit from BaseChannel)
├── providers/       # LLM providers via registry pattern
├── session/         # Conversation session management
├── config/          # Pydantic configuration schema
├── cron/            # Scheduled tasks service
├── heartbeat/       # Proactive wake-up service
└── cli/             # Typer CLI commands
```

### Core Components

**AgentLoop** (`agent/loop.py`): The central orchestrator that:
- Consumes inbound messages from the bus
- Builds prompts via ContextBuilder
- Calls the LLM provider
- Executes tool calls via ToolRegistry
- Publishes outbound responses

**MessageBus** (`bus/queue.py`): Async queue-based message routing between channels and agent.

**ToolRegistry** (`agent/tools/registry.py`): Dynamic tool registration and execution with validation.

**ProviderRegistry** (`providers/registry.py`): Single source of truth for LLM provider metadata. Adding a new provider requires only:
1. Add `ProviderSpec` to `PROVIDERS` tuple in `registry.py`
2. Add field to `ProvidersConfig` in `config/schema.py`

### Key Data Flows

1. **Inbound**: Channel → InboundMessage → Bus → AgentLoop → LLM
2. **Outbound**: AgentLoop → OutboundMessage → Bus → Channel
3. **Tool Execution**: AgentLoop → ToolRegistry.execute() → Tool.execute()

## Adding New Components

### Adding a Tool
1. Create a new file in `nanobot/agent/tools/`
2. Inherit from `Tool` base class in `base.py`
3. Register in `AgentLoop.__init__()` in `loop.py`

### Adding a Channel
1. Create a new file in `nanobot/channels/`
2. Inherit from `BaseChannel` in `base.py`
3. Add config schema to `config/schema.py`
4. Register in `ChannelManager._init_channels()` in `channels/manager.py`

### Adding a Provider
1. Add `ProviderSpec` to `PROVIDERS` in `providers/registry.py` (order = priority)
2. Add field to `ProvidersConfig` in `config/schema.py`

## Configuration

- Config file: `~/.nanobot/config.json`
- Schema: `config/schema.py` (Pydantic models)
- Workspace: `~/.nanobot/workspace/`

## Skills

Skills are stored in `nanobot/skills/` as directories containing `SKILL.md` files with YAML frontmatter and Markdown instructions. Skills are loaded by `agent/skills.py` on startup.

## Testing

Tests use pytest with async support (`pytest-asyncio`). Test files follow the pattern `test_*.py` in the `tests/` directory.