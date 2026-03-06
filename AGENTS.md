# Repository Guidelines

## Local Branch Status

This worktree is a local customization branch, not an upstream-integration branch.

- Branch: `codex/local-feature` 
- Worktree: `D:\Code\nanobot-local-feature` 
- Goal: maintain personal features locally and selectively absorb fixes from `main`
- Default expectation: changes here do not need to be prepared for merge back to the main branch

See `LOCAL_BRANCH.md` for the maintenance policy.

## Project Structure & Module Organization

Core Python code lives in `nanobot/`. Key modules include `agent/` for the main loop and tools, `channels/` for chat platform adapters, `cli/` for the Typer entrypoint, `session/` and `memory/` logic under `agent/`, and newer cross-channel layers in `identity/` and `routing/`. Tests live in `tests/` and follow the runtime layout. Workspace and design docs are under `docs/`. The `bridge/` directory contains the Node-based WhatsApp bridge.

## Build, Test, and Development Commands

- `uv sync --extra dev`: install Python dependencies, test tools, and optional Matrix extras.
- `uv run pytest -q`: run the full test suite.
- `uv run pytest -q tests/test_session_policy.py`: run a targeted test file during local iteration.
- `uv run ruff check .`: run linting.
- `uv run python -m nanobot.cli.commands agent -m "Hello"`: quick CLI smoke test.
- `uv run python -m nanobot.cli.commands gateway --workspace <path>`: run the gateway against a specific workspace.
- `cd bridge && npm install && npm run build`: build the WhatsApp bridge when working on `bridge/`.

## Coding Style & Naming Conventions

Use Python 3.11+, 4-space indentation, and keep lines near the repo Ruff limit of 100 chars. Prefer type hints on new code. Modules and functions use `snake_case`; classes use `PascalCase`; constants use `UPPER_SNAKE_CASE`. Keep new behavior in additive layers when possible instead of rewriting core engine code.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio` (`asyncio_mode = auto`). Name files `test_<feature>.py` and keep assertions behavior-focused. Add targeted tests for new routing, channel, or tool behavior, then rerun nearby regression tests. If a test depends on optional extras, make that explicit; Matrix tests require the `matrix` dependencies.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit style inside merge subjects, for example `feat(gateway): ...` and `fix(feishu): ...`. Use that format for commit subjects. Keep PRs small and scoped to one work package or bug. Include a short description, affected modules, test commands run, and screenshots/log snippets only when UI or channel behavior changed.

## Security & Configuration Tips

Do not commit secrets, local workspace state, or personal `config.json` values. Prefer workspace-local extensions over broad schema changes when adding assistant-specific features. Preserve compatibility with existing `session_key` and channel metadata contracts unless a migration is explicitly planned.

