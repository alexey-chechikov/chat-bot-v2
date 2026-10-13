---
name: cross-claude-sync
description: Check git branch state in the bot7 project — what GPT/Codex reviews or other Claudes have pushed, and conflicts with local changes. Use when the user asks "что нового в репо", "что сделал коллега", "проверь ветки", "пришёл ли разбор GPT", "what did the other claude do", "are there conflicts", or mentions branches like alexey/mac-2026-05-29 or chechikov-win/XX. Report only — never merge, stash or fix anything from here.
---

# Cross-Claude Sync (report only)

Repo: GitHub `alexey-chechikov/chat-bot-v2` (public), local `/Users/alexeychechikov/code/bot7`.
Working branch: `alexey/mac-2026-05-29` (Mac Claude + GPT/Codex reviews `docs/WEEX_GPT_*`). Windows Claude
(`chechikov-win/*`) has not committed since 29.09.2026. Absolute paths, `git -C`, no `cd`, no `$(…)`.

## What to do
1. `git -C /Users/alexeychechikov/code/bot7 fetch --prune`
2. New on the working branch (three dots — only THEIR commits, full paths):
   `git -C /Users/alexeychechikov/code/bot7 log --oneline HEAD..origin/alexey/mac-2026-05-29` and
   `git -C /Users/alexeychechikov/code/bot7 diff --name-only HEAD...origin/alexey/mac-2026-05-29`
   - a new `docs/WEEX_GPT_*` → one line: «пришёл разбор docs/…, пунктов N» — no merge, no fixes (the review cycle
     runs only when the operator asks: skill `model-answer-comparison`);
   - any file outside `docs/` from GPT/Codex → say so explicitly: external code, not merged without the operator.
3. Optional overview of other branches: `/Users/alexeychechikov/code/bot7/.venv/bin/python3
   /Users/alexeychechikov/.claude/skills/cross-claude-sync/scripts/sync_check.py` (compares with `origin/main`,
   which is NOT the working branch — treat its ahead/behind as background only).
4. Local uncommitted files: `git -C … status --short` — list them; never suggest `git stash` (forbidden, CLAUDE.md);
   commits only by name and only on the operator's request («дай GPT на проверку» = commit + push).

## Present
Short Russian summary: what arrived (who, which files), whether it touches live code (`services/weex_*`,
`app_runner.py`, `services/telegram_runtime.py`), conflicts with local changes, and the one recommended next step.

## Do not
- merge, rebase, stash, push, or run anything from fetched code;
- `git push --force`;
- analyze full diffs unless asked.
