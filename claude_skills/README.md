# Claude Skills для bot7

Custom skills для Claude Code сессий в bot7 проекте. Версионируются в git
чтобы Mac и Windows Claude использовали одинаковый набор инструментов.

## Текущие скилы

| Скил | Назначение |
|---|---|
| `range-hunter-status` | Quick health-check Range Hunter стратегии (читает state/range_hunter_signals.jsonl) |
| `cross-claude-sync` | Git branch check — что нового в чужих ветках, конфликты с локальными изменениями |
| `live-trade-decision` | GO/CAUTION/SKIP рекомендации для ручных Phase-D сделок |

## Установка на новой машине

Claude Code ищет user-scope скилы в `~/.claude/skills/`. После `git pull`
скопировать или симлинкнуть содержимое этой папки туда.

### Mac/Linux (симлинк — обновления через git pull автоматом)

```bash
cd ~/.claude/skills
for skill in range-hunter-status cross-claude-sync live-trade-decision; do
    [ -e "$skill" ] && rm -rf "$skill"  # снести старую копию если есть
    ln -s ~/code/bot7/claude_skills/$skill "$skill"
done

# Проверка — должны появиться в скил-листе Claude Code:
ls -la ~/.claude/skills/
```

### Windows (копия — после каждого pull повторить, или симлинк через mklink)

```cmd
cd %USERPROFILE%\.claude\skills

REM Симлинк через mklink (нужны admin права или Developer Mode)
for %s in (range-hunter-status cross-claude-sync live-trade-decision) do (
    rmdir /s /q %s 2>nul
    mklink /D %s C:\bot7\claude_skills\%s
)
```

Или просто скопировать руками после каждого `git pull` если симлинки не вариант.

## Workflow обновления скила

1. Редактировать скил в `~/.claude/skills/<name>/` (где он реально подгружается).
2. После проверки — скопировать в `claude_skills/<name>/` в репо.
3. `git add claude_skills/<name>/ && git commit && git push`.
4. На другой машине: `git pull` (симлинк автоматом подтянет, копию — обновить руками).

## Структура скила

```
<skill-name>/
├── SKILL.md          # YAML frontmatter + markdown инструкции
└── scripts/
    └── *.py          # bundled scripts
```

`SKILL.md` подгружается в context Claude при триггере. Скрипты вызываются
по требованию из инструкций.

## Cross-platform notes

- Скрипты должны работать и на Win (cp1251) и на Mac (utf8). Избегайте
  unicode-символов в `print()` — используйте ASCII (`->`, `>=`, `[!]`).
- Пути ищите через fallback: `$BOT7_PATH` → `~/code/bot7` → `C:/bot7` → `Path.cwd()`.
- В качестве entry point — Python 3.10+ (тот что в .venv проекта).

## Не commit'ить сюда

- `__pycache__/`, `*.pyc` — авто-генерируемые
- Output из скриптов (если что-то пишут в файлы — лучше в state/ а не сюда)
- Скилы которые имеют смысл только локально (например test-stubs)
