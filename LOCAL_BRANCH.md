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

## Remote Layout

- `upstream`: `https://github.com/HKUDS/nanobot.git`
- `origin`: `https://github.com/Mlychen/nanobot.git`
- `main` tracks `upstream/main`
- `codex/local-feature` tracks `origin/codex/local-feature`

## Sync Workflow

- Keep `main` aligned with upstream:
  - `git checkout main`
  - `git pull --ff-only upstream main`
- Mirror the updated main branch to the fork when needed:
  - `git push origin main`
- Continue local customization work on the fork-backed branch:
  - `git checkout codex/local-feature`
  - `git push origin codex/local-feature`

## Practical Rules

- Do not develop directly on `main`; reserve it as the local mirror of `upstream/main`
- Put local-only features, routing changes, prompts, and workflow behavior on `codex/local-feature`
- When upstream fixes are needed, fast-forward `main` first, then merge or rebase `codex/local-feature` onto the updated `main`
- If `origin/main` ever drifts from `upstream/main`, treat `upstream/main` as the source of truth and realign the forked `main`

