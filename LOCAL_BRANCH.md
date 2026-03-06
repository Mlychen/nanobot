# Local Branch Policy

This worktree and branch exist for local, long-term customization.

## Branch Role

- Branch: `codex/local-feature`
- Worktree: `D:\Code\nanobot-local-feature`
- Primary goal: maintain personal features and workflow-specific behavior
- Non-goal: preparing changes for upstream merge by default

## Maintenance Strategy

- Regularly absorb bug fixes and safe improvements from `main`
- Prefer compatibility with local workflows over upstream generality when tradeoffs appear
- Keep local customization explicit in docs and code comments when behavior diverges from upstream
- Treat upstream sync as selective maintenance, not as preparation for a pull request

## Working Rules

- New features may target personal channels, routing rules, prompts, and automation flows
- When upstream fixes are needed, merge or rebase from `main` into this branch and resolve conflicts locally
- Do not assume this branch must satisfy upstream review scope, naming, or minimal-diff constraints
- If a change could still be useful upstream later, isolate it into a clean commit, but that is optional
