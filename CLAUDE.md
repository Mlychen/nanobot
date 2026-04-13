# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 启动方式（重要 - Windows 编码问题）

**Windows**: 使用 `start.bat` 脚本，不要用 `nanobot` 命令（会有 GBK 编码错误）：
```bash
./start.bat gateway    # 启动网关
./start.bat agent      # 交互式对话
./start.bat serve      # API 服务器
./start.bat status     # 查看状态
```

**Linux/macOS**: 使用 `start.sh` 脚本：
```bash
./start.sh gateway
./start.sh agent
```

**原理**: 脚本设置 `PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8`，防止 emoji 和中文字符在 Windows GBK 控制台编码失败。

---

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run specific test
pytest tests/agent/test_loop.py -v

# Lint
ruff check nanobot/

# Format
ruff format nanobot/
```

## Architecture Overview

nanobot is an ultra-lightweight personal AI agent framework with a modular architecture:

```
nanobot/
├── agent/          # Core agent engine (loop, memory, tools, skills)
├── api/            # OpenAI-compatible API server
├── channels/       # Chat platform integrations (Telegram, Discord, Feishu, etc.)
├── cli/            # Command-line interface
├── command/        # Command routing and builtin commands
├── config/         # Configuration schema and loaders
├── cron/           # Scheduled tasks
├── providers/      # LLM provider implementations
├── session/        # Session management
├── templates/      # Prompt templates
└── utils/          # Shared utilities
```

### Core Components

**Agent Loop (`nanobot/agent/loop.py`)**: The central processing engine that:
- Receives messages via `MessageBus`
- Manages conversation context through `SessionManager`
- Calls tools via `ToolRegistry`
- Handles streaming responses through `AgentHook` lifecycle

**Memory System (`nanobot/agent/memory.py`)**: Three-layer file-based storage:
- `MemoryStore`: Raw I/O for MEMORY.md, history.jsonl, SOUL.md, USER.md
- `Consolidator`: Compresses conversation history
- `Dream`: Background memory optimization (runs periodically)

**Provider Registry (`nanobot/providers/registry.py`)**: Single source of truth for LLM providers. Adding a provider requires:
1. Add `ProviderSpec` to `PROVIDERS` tuple
2. Add field to `ProvidersConfig` in `config/schema.py`

**Tool System (`nanobot/agent/tools/`)**: Built-in tools include filesystem, shell, web search, MCP, cron, and message tools.

**Channels (`nanobot/channels/`)**: Each channel (Telegram, Discord, Feishu, etc.) implements a common base interface.

## Configuration

- **Config file**: `~/.nanobot/config.json`
- **Schema**: `nanobot/config/schema.py` (Pydantic-based)
- **Loading**: `nanobot/config/loader.py`

Key config sections:
- `agents.defaults`: Model, provider, workspace, temperature, max_tokens
- `channels`: Per-channel settings (enabled, tokens, allowFrom)
- `providers`: API keys and base URLs for each LLM provider
- `tools`: Web search, exec, MCP servers, SSRF whitelist

## Development Patterns

### Adding a New Provider

1. Add entry to `PROVIDERS` in `nanobot/providers/registry.py`
2. Add config field in `nanobot/config/schema.py::ProvidersConfig`
3. Implement provider class in `nanobot/providers/` (or use existing backend)

### Adding a New Channel

1. Extend `nanobot/channels/base.py::Channel`
2. Implement required methods: `start()`, `send_message()`, `send_delta()` (for streaming)
3. Register in `nanobot/channels/manager.py`
4. See `docs/CHANNEL_PLUGIN_GUIDE.md` for full guide

### Running Tests

```bash
# All tests
pytest

# By category
pytest tests/providers/
pytest tests/channels/
pytest tests/agent/

# With coverage
pytest --cov=nanobot
```

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases |
| `nightly` | Experimental features |

- Bug fixes, docs → `main`
- New features, refactoring → `nightly`
- Stable features cherry-picked from `nightly` to `main` weekly

## Key Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Dependencies, build config, ruff/pytest settings |
| `nanobot/nanobot.py` | High-level SDK facade |
| `nanobot/agent/loop.py` | Core agent processing engine |
| `nanobot/agent/memory.py` | Memory storage and consolidation |
| `nanobot/providers/registry.py` | LLM provider metadata |
| `nanobot/config/schema.py` | Configuration schema |
| `docs/MEMORY.md` | Memory system documentation |
| `docs/PYTHON_SDK.md` | SDK usage guide |

## Environment

- **Python**: 3.11+
- **Package manager**: uv (recommended) or pip
- **Platform**: Cross-platform (Windows, Linux, macOS)

## Common Errors & Solutions

### Windows Encoding Issues

**已解决**: 使用 `start.bat` 或 `start.sh` 脚本启动即可，无需手动设置环境变量。

### Virtual Environment Setup (Windows + Git Bash)

**Problem**: `.venv\Scripts\activate` not found in Git Bash

**Solution**: Use `source .venv/Scripts/activate` instead

### pip vs uv

**Problem**: Installing with pip bypasses `uv.lock` and causes dependency conflicts

**Solution**: Always use uv in projects with `uv.lock`:
```bash
uv venv                    # Create virtual environment
source .venv/Scripts/activate  # Activate (Git Bash)
uv pip install -e .        # Install with lock file
```

### Path Format in Tools

**Problem**: Windows paths with backslashes (`\`) fail in Read tool and Bash

**Solution**: Use forward slashes or absolute paths:
- ❌ `D:\Code\nanobot\pyproject.toml`
- ✅ `D:/Code/nanobot/pyproject.toml`

### Working Directory Confusion

**Problem**: Current directory may be `nanobot/nanobot` (package) not project root

**Solution**: Always verify with `pwd` before file operations:
```bash
pwd  # Confirm location
ls pyproject.toml  # Verify project root
```
