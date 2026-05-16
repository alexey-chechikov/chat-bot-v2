# Onboarding — bot7 на новой машине

Этот гайд для случая когда переезжаешь с production-машины (Windows, `C:\bot7`) на новую (MacBook, разработка). Покрывает: что клонировать, какой env, какие секреты, что **не** переносить.

## Quick start (TL;DR)

```bash
# 1. Clone
git clone <ваш-remote-url> bot7
cd bot7

# 2. Python 3.10+ virtualenv
python3.10 -m venv .venv
source .venv/bin/activate    # Win: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Config secrets
cp .env.example .env.local
# редактируй .env.local: вставь BOT_TOKEN, BITMEX_API_KEY, GINAREA_*, ADVISOR_DEPO_TOTAL

# 4. Run tests
python -m pytest tests/services/ -q   # должно быть 1100+ passed

# 5. Запустить
python app_runner.py
```

---

## Что переносить

### ✅ Переносить (из git)

- Весь код: `app_runner.py`, `services/`, `core/`, `scripts/`, `tools/`, `market_collector/`, `bot7/`
- Тесты: `tests/`
- Конфиги: `config/`, `requirements.txt`
- Доки: `docs/`, `README.md`, `ONBOARDING.md` (этот файл), `CHANGELOG.md`
- Историческая research-data: `data/historical/` (parquet с OI/funding/LS — для backtests)
- Pattern memory: `state/pattern_memory_*.csv` (трекается в git)

### ⚠️ Переносить отдельно (вне git)

- **Секреты**: `.env.local` (не в git!) — скопировать вручную или через secure transfer
- **Pre-existing runtime state** (опционально, если хочешь сохранить накопленное):
  - `state/setups.jsonl` — накопленные сетапы
  - `state/paper_trades.jsonl` — paper trading история
  - `state/cascade_accuracy.jsonl` — KPI каскадных alerts
  - `state/liq_pre_cascade_fires.jsonl` — журнал pre-cascade alerts
  - `ginarea_live/snapshots.csv` — снапшоты ботов GinArea
  - `market_live/liquidations*.csv` — live liq-feed (можно начать с нуля)

### ❌ Не переносить

- `__pycache__/`, `.venv/`, `*.pyc`
- `state/deriv_live*.json` — live snapshot, регенерируется за 5 минут
- `state/*_dedup.json`, `state/*_state.json` — runtime dedup, начнётся с чистого
- `logs/`, `_*.txt` — старые логи и dump'ы (займут много, не нужны)
- `_recovery/`, `state/_archive/` — old backups
- `data/backtest_archive/` — старые backtest runs

---

## Секреты — что заполнить в .env.local

Минимум для запуска (с учётом текущей prod-конфигурации, см. .env.example):

```env
BOT_TOKEN=<TG bot token из BotFather>
ALLOWED_CHAT_IDS=<chat_id или несколько через запятую>
ROUTINE_CHAT_IDS=<chat_id для низкоприоритетного канала>  # опционально

BITMEX_API_KEY=<read-only ключ>
BITMEX_API_SECRET=<секрет>

GINAREA_EMAIL=<email от GinArea>
GINAREA_PASSWORD=<пароль>
GINAREA_TOTP_SECRET=<TOTP secret для 2FA>
GINAREA_API_URL=https://app.ginarea.io/api  # production endpoint

ADVISOR_DEPO_TOTAL=15145  # текущий депозит USD, обновлять при +/-500
ENABLE_TELEGRAM=1

# Optional но желательно:
ANTHROPIC_API_KEY=<если используешь regime_narrator или claude_bot>
COINGLASS_API_KEY=<auxiliary data, можно без>
```

Полный список — см. `.env.example`.

---

## Mac-специфичные нюансы

### Python
- Использовать Python 3.10 (как на prod). Через Homebrew: `brew install python@3.10`
- Виртуалка: `python3.10 -m venv .venv`

### Зависимости
- `requirements.txt` написан под Windows но работает и на Mac. Большинство пакетов кроссплатформенные.
- Может потребовать `xcode-select --install` для C-extensions (numpy, pandas).
- Если упадёт `httpx-mock` или `pytest-httpx` — установить отдельно: `pip install pytest-httpx`.

### Запуск в фоне
- Windows: `pythonw.exe app_runner.py` + Task Scheduler
- Mac: использовать `launchd` (`~/Library/LaunchAgents/com.bot7.plist`) ИЛИ `nohup python app_runner.py > app.log 2>&1 &` ИЛИ `tmux`/`screen` сессия.

### Пути к файлам
- В коде есть hardcoded `c:\bot7` — это **только в логах**, не в логике. `Path(__file__).resolve().parents[N]` используется везде где нужны абсолютные пути.

---

## Разделение Win=prod / Mac=dev

Стратегия (из переписки оператора 2026-05-13):

1. **Windows-машина** = stable production. Бот, collector, watchdog, ginarea_tracker — крутятся 24/7. Только pull обновлений + рестарт.
2. **MacBook** = разработка. Здесь делаются:
   - Новые фичи / стратегии
   - Backtests (tools/_backtest_*.py)
   - Документация (docs/STRATEGIES/*)
   - Эксперименты в feature branches

### Git workflow для двух машин

```bash
# На Mac: разработка
git checkout -b feat/new-edge
# работаем, commit
git push origin feat/new-edge
# merge через PR (или git push origin feat/new-edge:main)

# На Windows: обновление prod
cd C:\bot7
git pull
# (если нужно — рестарт)
python app_runner.py  # или kill + restart через Task Scheduler
```

### Что **только** на Windows

- Live прогон бота (`app_runner.py`)
- Live сбор данных (`market_collector`, `ginarea_tracker`)
- Watchdog (`scripts/watchdog.py`)
- Trading: BitMEX/GinArea credentials активны только в .env.local на Windows

### Что **только** на Mac

- Heavy backtests (Mac мощнее? решает оператор)
- R&D скрипты с большими данными
- Документация и stratagy planning

### Что **на обеих**

- Pytest baseline (после pull)
- IDE work (VS Code / PyCharm)
- Claude Code сессии (оба клиента имеют доступ к одному repo через git)

---

## Первый запуск на Mac — checklist

- [ ] `python3.10 --version` → 3.10.x
- [ ] `python3.10 -m venv .venv` + `source .venv/bin/activate`
- [ ] `pip install -r requirements.txt` без ошибок
- [ ] Скопировать `.env.local` с Windows (через scp / secure copy / 1Password)
- [ ] `python -m pytest tests/services/ -q` → 1100+ passed (28 errors в ginarea_api допустимы — это `pytest-httpx` missing)
- [ ] `pip install pytest-httpx` если хочешь полный test pass
- [ ] **НЕ запускать** `app_runner.py` если на Windows уже работает prod (две инстанции = двойные TG-алерты и race conditions с GinArea API)
- [ ] Для dev: открыть проект в VS Code, проверить что Claude Code видит контекст
- [ ] Прочитать `README.md`, `docs/MASTER.md`, `docs/PLAYBOOK.md`

---

## Архитектура (краткая шпаргалка)

```
app_runner.py            ← main entrypoint (asyncio loop)
├── services/cascade_alert/        — caskade liq alerts + KPI tracker
├── services/pre_cascade_alert/    — Phase-1/2 pre-cascade signal
├── services/setup_detector/       — RSI/MFI/exhaustion детекторы
├── services/exit_advisor/         — honest_renderer для выходов
├── services/grid_coordinator/     — grid alignment monitor
├── services/decision_layer/       — R-2/R-3 regime events
├── services/paper_trader/         — paper-trade simulation
├── services/ginarea_api/          — REST к GinArea
├── services/bitmex_account/       — BitMEX margin poller
├── services/reports/              — weekly self-report
├── services/telegram/             — channel_router + severity_prefix
├── market_collector/              — WS streams (Bybit/Binance/OKX) + OHLCV
├── ginarea_tracker/               — снапшоты ботов в snapshots.csv
└── scripts/watchdog.py            — process watchdog, рестарт при крэше
```

---

## Полезные команды

| Что | Команда |
|---|---|
| Запуск | `python app_runner.py` |
| Тесты services | `python -m pytest tests/services/ -q` |
| Lint | `python -m ruff check .` (если есть в requirements) |
| Restart на Win | Stop pythonw процессы + `bot7_start.bat` |
| Запустить collector отдельно | `python -m market_collector.collector` |
| Restart watchdog | `python scripts/watchdog.py` |
| TG notify | `python scripts/done.py "сообщение"` |
| Backtest sweep | `python tools/_backtest_<name>.py` |

---

## Что делать если...

- **Бот не пишет в TG**: проверь `BOT_TOKEN`, `ALLOWED_CHAT_IDS`, `ENABLE_TELEGRAM=1`, что чат начат с ботом (написать ему `/start`).
- **GinArea auth fails**: TOTP мог сбиться по времени. Проверь системное время. Иначе перегенерируй TOTP secret в GinArea UI.
- **Tests падают по `httpx_mock`**: `pip install pytest-httpx` — это dev-dependency.
- **`No module named 'X'`**: убедись что virtualenv активирован и `pip install -r requirements.txt` прошёл без warnings.
- **Множественные процессы**: на Windows бывает 2 pythonw — system Python и .venv Python. Один из них wrapper, другой реальный (по WorkingSetSize видно — большой = реальный).

---

## Контакты / поддержка

- Все ключевые решения и контексты — в `docs/STRATEGIES/*.md`.
- Стратегия Claude — в `CLAUDE.md` (если есть).
- Memory: `~/.claude/projects/c--bot7/memory/MEMORY.md` (на Mac будет другой путь).

---

## Что сейчас работает в проде (snapshot 2026-05-17)

> Полный handoff с архитектурой и edges — см. [docs/HANDOFF_2026-05-17.md](docs/HANDOFF_2026-05-17.md).

**Ключевые новые модули (за последние 2 недели)**:

| Модуль | Назначение | State files |
|---|---|---|
| `services/short_bots_guard/` | Auto-pause SHORT/LONG GinArea ботов при cascade events + smart resume (regime + reversal override) | `state/short_bots_managed.json`, `state/short_bots_auto_pause.json`, `state/short_bots_audit.jsonl` |
| `services/range_hunter/` | Mean-revert TG-emitter, **multi-asset** (BTC/ETH/XRP × 1m+5m = 6 emitters) | `state/range_hunter_signals*.jsonl` |
| `services/manual_levels.py` | VPVR/key-levels store: оператор + TV TG-bridge | `state/manual_levels.json` |
| `services/volume_nodes.py` | Local VPVR (multi-symbol) — auto-refresh каждый час, daily TG digest 00:30 UTC | `state/manual_levels.json` (source `local_vol_profile`) |
| `services/watchlist/confluence.py` + `play_journal.py` | 2+ signal confluence detector + forward-test journal | `state/confluence_*`, `state/watchlist_play_journal.jsonl` |
| `services/reports/daily_self_report.py` | 21:00 UTC TG digest (BitMEX + RH + watchlist + edges) | `state/daily_report_state.json` |
| `/positions` TG command | Просмотр managed bots + open positions | reads `ginarea_live/` + state |

**Managed bots в auto-pause** (см. `state/short_bots_managed.json`):
- 3 SHORT grid bots: T1 (4729923198), T2 (6287583200), T3 (5736281160) — XBTUSD inverse
- 2 LONG hedge bots: LONG-D (5154651487), LONG-V5 (4979458320) — XBTUSDT linear
- Триггеры: `cascade_short_*` paus'ит SHORTs, `cascade_long_*` paus'ит LONGs

**Эджи** (актуальные):
- `cascade_short → +pct_up 4h ~70%` (2024+2026 combined backtest survived)
- `cascade_long → +pct_down 4h ~65%` (2026 INVERSION vs 2024)
- `long_multi_divergence`: 87.7% WR на paper-trader (8–15 May)
- Range Hunter: 68–77% WR на BTC/ETH/XRP (walk-forward 4 folds)

**Disabled detectors** (`state/disabled_detectors.json`, без рестарта — refresh за 60s):
- `short_double_top`, `cascade_long_2btc`, `cascade_long_5btc`, `short_pdh_rejection`, `short_mfi_multi_ga`

**TradingView интеграция**:
- TG-bridge: оператор шлёт `LEVELS BTCUSD 79100 80500 78200` → бот парсит → store. См. [docs/TV_PINE_SCRIPTS.md](docs/TV_PINE_SCRIPTS.md).
- Local VPVR: автоматически обновляет POC/VAH/VAL раз в час (BTC/ETH/XRP). TV-override приоритет 24h.

**Quick verification после restart**:
```bash
launchctl kickstart -k gui/$(id -u)/com.bot7.app-runner
sleep 10
grep -E "loop.*started|\.start interval" logs/app.log | tail -30
grep -E "ERROR|Traceback" logs/app.log | tail -10
grep "volume_nodes.refreshed" logs/app.log | tail -5
```
