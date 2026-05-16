---
name: cross-claude-sync
description: Check git branch state in the bot7 project to find out what work other Claudes (e.g. on Mac vs Windows) have committed, and detect conflicts with local changes. Use this skill whenever the user asks "что нового в репо", "что сделал коллега", "проверь ветки", "what did the other claude do", "are there conflicts", before merging branches, before starting a new task to see if state has changed, or after a long break to catch up. Also use when the user mentions specific branches like alexey/mac-2026-XX-XX or chechikov-win/XX.
---

# Cross-Claude Sync

The bot7 project is worked on simultaneously by two Claude instances:
- **Mac Claude** (`alexey/mac-*` branches) — runs production stack
- **Windows Claude** (`chechikov-win/*` branches) — works on backtests, R&D, dev

Both push to GitHub `Roflkemper/chat-bot-v2`. This skill helps quickly understand what the other Claude has done since the last interaction, and surface potential conflicts.

## When to use

- Start of session: "что нового" / "проверь репо" / "check repo state"
- Before merging a branch into main
- After a long break — "что было сделано пока меня не было"
- When user mentions another Claude's work or specific branch names
- Before starting a new task — verify base state is current

## What to do

1. Run the bundled script:
   ```bash
   python C:/Users/Kemper/.claude/skills/cross-claude-sync/scripts/sync_check.py
   ```
   (or `~/.claude/skills/cross-claude-sync/scripts/sync_check.py` on Mac)

2. The script reports:
   - All remote branches (fetched fresh)
   - Recent commits per branch (last 5)
   - Files changed vs current `main`
   - Local uncommitted changes (if any) that may conflict
   - Recommended action: "safe to pull", "merge needed", "stash first", etc.

3. Present to the user as a short summary:
   - **What the other Claude did** — 2-3 line summary per branch
   - **Conflicts** — list of files modified both locally and in another branch
   - **Recommended next action** — concrete git command(s)

## What NOT to do

- Don't blindly merge — surface conflicts first, let the user decide
- Don't run `git push --force` unless user explicitly asks (and double-check it's not main)
- Don't fetch heavy data (PRs, issues) — just branches and commit metadata
- Don't analyze full diffs — just file lists and commit messages (use Explore subagent if user wants deep review)

## Repository layout

- `main` — stable, primary branch. Don't break it.
- `alexey/mac-*` — Mac Claude's work, often parallel to main
- `chechikov-win/*` — Windows Claude's work
- Other branches — likely human-created PRs or experiments

## Daily workflow this skill supports

```
Win:  git checkout main → work → push to chechikov-win/feature
Mac:  git checkout alexey/mac-2026-XX → work → push
Both: periodic sync via this skill to detect overlap
Operator: merges decisions
```
