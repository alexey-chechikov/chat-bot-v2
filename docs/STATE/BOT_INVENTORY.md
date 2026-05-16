# Bot Inventory

**Created:** 2026-05-05 (TZ-BOT-STATE-INVENTORY, P2)
**Source of truth:** `ginarea_live/snapshots.csv` (live tracker) + `ginarea_tracker/bot_aliases.json` + `ginarea_live/params.csv` (live params snapshot)
**Scope:** Inventory only. No config changes, no calibration touch.

> **2026-05-17 addendum**: Auto-pause guard introduced. См. §1z для managed bots subset (5 ботов).

---

## §1z Managed bots — `services/short_bots_guard/` (2026-05-17)

5 ботов под автоматическим управлением guard'а (`state/short_bots_managed.json`):

| Bot ID | Tier | Alias | Side | Контракт | Trigger paus'ает |
|---|---|---|---|---|---|
| 4729923198 | T1 | SHORT-T1 | short | XBTUSD inverse | `cascade_short_5.0`, `cascade_short_2.0` |
| 6287583200 | T2 | SHORT-T2 | short | XBTUSD inverse | `cascade_short_5.0`, `cascade_short_2.0` |
| 5736281160 | T3 | SHORT-T3 | short | XBTUSD inverse | `cascade_short_5.0` |
| 5154651487 | LONG-D | BTC-LONG-D-хедж | long | XBTUSDT linear | `cascade_long_5.0`, `cascade_long_2.0` |
| 4979458320 | LONG-V5 | BTC-LONG-хедж V5 | long | XBTUSDT linear | `cascade_long_5.0`, `cascade_long_2.0` |

**Поведение**:
- Cascade fire → pause 2–4h в зависимости от severity
- Resume — НЕ по timer'у, а **smart**: 1h/4h regime check + fresh cascade check + vol regime + **reversal override** (🔝/🔻 ИСТОЩАЕТСЯ score≥4)
- Если adverse при resume — extend +60min, max 12h total
- TG-нотификации через `MARGIN_ALERT` channel: pause / extend / resume

**Live runtime state**: `state/short_bots_auto_pause.json` — текущие paused + triggers history.
**Audit log**: `state/short_bots_audit.jsonl` — append-only все pause/resume actions с reasons.

См. полную архитектуру в [HANDOFF_2026-05-17.md §1.1](../HANDOFF_2026-05-17.md).

---

## §1 Active GinArea bot fleet (22 unique bot IDs in tracker)

Status mapping: snapshot `status=2` = running, `status=12` = paused, `status=0` = off / draft. (Determined from observed transitions in `ginarea_live/events.csv` and per-bot trade volumes in snapshots.csv.)

### 1a — BTC LONG bots

| Bot ID | Name | Alias | Status | Position | Profit | Notes |
|--------|------|-------|--------|----------|--------|-------|
| 6075975963 | `😎 ЛОНГ_БТС_КЛОД ИМПУЛЬС` | `КЛОД_ИМПУЛЬС` | running | 0 | 0.0 | Aliased; impulse-style LONG |
| 5427983401 | `BTC-LONG-B` | `LONG_B` (informal) | running | 900 | +0.0048 | Recent activity |
| 5312167170 | `BTC-LONG-C` | `LONG_C` (informal) | running | 900 | +0.0058 | Recent activity |
| 5154651487 | `BTC-LONG-D-volume✨` | `LONG_D` (informal) | running | 900 | +0.0011 | Volume-weighted variant |
| 4651067955 | `BTC-LONG-B_c` | – | off (draft) | 0 | 0.0 | Trade count 0 — draft |
| 4874082917 | `бектест ЛОНГ таргет - 0.50` | – | off (backtest) | 0 | 0.0 | Backtest-only, never deployed |
| 6256800305 | `😎😎 ЛОНГ_1%` | `ЛОНГ_1%` | paused | 0 | 0.0 | status=12 |

### 1b — BTC SHORT bots

| Bot ID | Name | Alias | Status | Position | Profit | Notes |
|--------|------|-------|--------|----------|--------|-------|
| 6399265299 | `🐉GPT🐉% SHORT 1.1%` | `SHORT_1.1%` | running | 2 | −0.606 | **Live SHORT** — losing today. **P-16 Post-impulse SHORT booster** (manual activation): включается когда impulse рост остановился и цена в зоне ликвидаций. Активация: 1) detect impulse exhaustion (operator judgement) 2) check price у resistance/liq cluster 3) set hard `border.top` чуть выше recent high 4) включить. Связан с Q-4 (booster bot triggers) в OPERATOR_QUESTIONS.md. Источник: ex-CANON/CUSTOM_BOTS_REGISTRY. |
| 5436680540 | `🐉🐉% SHORT 1%` | `SHORT_1%` | paused | 12 | 0.0 | status=12 — recently paused |
| 4539437207 | `🐉GPT🐉% SHORT выходной` | `SHORT_ВЫХ` | paused | 12 | 0.0 | Weekend-only variant |
| 4516992123 | `STOP✨5M_BTC_SHORT_BTC_5m` | `SHORT_5M` | paused | 12 | 0.0 | 5m timeframe SHORT |
| 5629971258 | `БЕктест индикатор шорт` | – | off (backtest) | 0 | 0.0 | Backtest-only |
| 6161205316 | `бектест ШОРТ таргет - 0.6` | – | off (backtest) | 0 | 0.0 | Backtest-only |

### 1c — XRP bots

| Bot ID | Name | Alias | Status | Position | Profit | Notes |
|--------|------|-------|--------|----------|--------|-------|
| 4826691675 | `💎 XRP ШОРТ 2.5 КЛОД + ЖПТ` | `XRP_ШОРТ` | running | 2 | 0.0 | XRP SHORT live |
| 5257298144 | `💎 XRP_ЛОНГ 2.5_ КЛОД` | `XRP_ЛОНГ` | running | 2 | 0.0 | XRP LONG live |
| 5478969754 | `💎 XRP_ЛОНГ ИМПУЛЬС 3.3_ КЛОД_c` | `XRP_ИМП` | running | 2 | 0.0 | XRP LONG impulse |

### 1d — Spot / hedge / other

| Bot ID | Name | Alias | Status | Position | Profit | Notes |
|--------|------|-------|--------|----------|--------|-------|
| 4361055038 | `spot btc Новый` | `SPOT_BTC` | paused | 12 | +0.0025 | Spot accumulation, not derivatives |

### 1e — Test/research bots (TEST_1/2/3 family)

| Bot ID | Name | Alias | Status | Position | Profit | Notes |
|--------|------|-------|--------|----------|--------|-------|
| 5196832375 | `🐉GPT🐉TEST 1` | `TEST_1` | running | 2 | −0.22 | Active loss today |
| 5017849873 | `🐉GPT🐉TEST 2` | `TEST_2` | running | 2 | −0.22 | Active loss today |
| 4524162672 | `🐉GPT🐉TEST 3` | `TEST_3` | running | 2 | −0.22 | Active loss today |

### 1f — Unidentified / orphan candidates

| Bot ID | Name | Status | Notes |
|--------|------|--------|-------|
| 5142606207 | `🌿 Щёлкающий_Холм_N7` | off | Codename style, function unclear |
| 5522444824 | `✨ Хихикающий_Путник_V` | off | Codename style |

---

## §2 Source of truth map

| Aspect | Where it lives | How to read |
|--------|----------------|-------------|
| Bot list (live) | `ginarea_live/snapshots.csv` | Latest row per `bot_id` |
| Aliases (formal) | `ginarea_tracker/bot_aliases.json` | Only 3 of ~22 bots have formal aliases |
| Bot config (params) | `ginarea_live/params.csv` | Per-bot parameter snapshots (not inspected this TZ) |
| Bot lifecycle events | `ginarea_live/events.csv` | Start/pause/resume/edit events |
| Tracker process | `ginarea_tracker/tracker.py` | Periodic snapshot writer |
| Paper journal entries | `state/advise_signals.jsonl` | Phase 1, Day 5/14 — separate from GinArea fleet |
| Virtual trader | `data/virtual_trader/positions_log.jsonl` | Empty currently — created today, no live signals yet |

**Key gap:** only 3 of ~22 GinArea bots have formal aliases (`TEST_1`, `TEST_2`, `КЛОД_ИМПУЛЬС`). Most operator references like "SHORT_1.1%" or "LONG_B" are **informal names from the bot's display string**, not stable identifiers. P8 ensemble design needs stable role labels — current state is brittle.

---

## §3 Bot deployment platforms

| Platform | Bots | Real money? | Coordination |
|----------|------|-------------|--------------|
| **GinArea (Binance USDT-M futures via API)** | All 22 | YES (TEST_1/2/3 likely also real, judging by non-zero losses) | Each bot independent; no central coordinator |
| **Manual operator** | (operator's own ad-hoc trades) | YES | Operator self-coordinates |
| **Paper journal** | (advise_signals — Phase 1 evaluation) | NO | Sequential daily signals, Day 5/14 |
| **Virtual trader** | (forecast pipeline output) | NO | Bot-internal log, empty so far |

---

## §4 Gap analysis vs P8 ensemble roles

P8 (regime-driven multi-bot ensemble) calls for these roles. Mapping current fleet:

| P8 Role | Definition | Current bot covering it? | Gap |
|---------|-----------|--------------------------|-----|
| **Range LONG** (small grid, fires in RANGE) | Tight grid 1–2%, low target, mean reversion | Possibly `BTC-LONG-D-volume` — small position, frequent trades. Not formally classified. | Bot exists but not regime-gated. |
| **Range SHORT** (small grid, fires in RANGE) | Tight grid, low target | `🐉GPT🐉% SHORT 1.1%` (`SHORT_1.1%`) — currently the live SHORT, target 1.1% | Live but not regime-gated. |
| **Trend LONG** (large grid, MARKUP only) | Wider grid, larger target, follows up-trend | `КЛОД_ИМПУЛЬС` (`6075975963`) is impulse-styled LONG → closest match | No regime gating. Operator manually pauses/runs. |
| **Trend SHORT** (large grid, MARKDOWN only) | Wider grid, larger target | None obvious. `SHORT_ВЫХ` is weekend-only. `SHORT_5M` is timeframe variant. | **MISSING** — no dedicated MARKDOWN trend SHORT. |
| **Hedge baseline** (LONG + SHORT in RANGE simultaneously, market-neutral) | Both `Range LONG` + `Range SHORT` together | Partially covered if `LONG_D` + `SHORT_1.1%` happen to run simultaneously | **No formal hedge structure.** Just happens that some run together. |

**Critical findings:**
- **No MARKDOWN-trend bot.** P8 needs one; doesn't exist.
- **No regime gating anywhere.** Operator decides which bots to run/pause manually based on market read.
- **TEST_1/2/3 trio is opaque** — three bots with identical losses today (−0.22 each), grid step probably small, position 2 → all running. Function unknown beyond "test".
- **2 bot IDs have only codenames** (#5142606207, #5522444824) — codebase has no documentation of what they do.

---

## §5 Coordination state

| Question | Answer |
|----------|--------|
| Is there a central coordinator that knows all bots? | **No.** GinArea API gives per-bot status; tracker reads it and writes snapshots. No code holds "ensemble state". |
| Does any service decide "regime is X, therefore enable bots [A,B] and pause [C,D]"? | **No.** Closest: `services/adaptive_grid_manager.py`, `boundary_expand_manager.py`, `counter_long_manager.py` — but each operates per-bot via local rules, not regime-conditional ensemble. |
| Does GinArea API support remote start/pause? | Yes (per `services/ginarea_api/bots.py`), but no orchestrator code uses it. |
| Where would an ensemble coordinator live? | New module needed (`services/ensemble/coordinator.py` or similar) — **doesn't exist yet**. |
| Snapshot/state for ensemble decisions? | None. Would need a new `data/ensemble/state.json`. |

**This is the largest structural gap for P8.** The whole ensemble idea presupposes a coordinator that this codebase doesn't have. P8-DUAL-MODE-DESIGN must include a coordinator design from scratch, not a wiring-up of existing infra.

---

## §6 Summary for downstream TZs

Three takeaways that should drive the next P2/P8 TZs:

1. **Alias hygiene needed first.** Of 22 bots, only 3 have stable aliases. Before P8 can name "the trend LONG bot", we need stable role-tagged aliases on at least 5 bots. Cheap fix (operator updates `bot_aliases.json` + restart tracker).

2. **MARKDOWN-trend SHORT is a deployment gap.** `SHORT_1.1%` is range-style. P8 trend-SHORT slot has no candidate. Either repurpose an existing SHORT bot (and document it) or accept that P8 ships LONG-side first.

3. **Ensemble coordinator is greenfield.** No existing module fits. P8-DUAL-MODE-DESIGN must specify a new component with these responsibilities:
   - Read regime from `RegimeForecastSwitcher.state`
   - Read bot inventory (this doc, but as live JSON)
   - Decide activation table (which bot ON / PAUSE per regime)
   - Issue start/pause commands via GinArea API
   - Persist ensemble state for audit

**INVENTORY-ONLY per anti-drift.** No bot configs touched, no calibration changes, no orchestrator wiring. All actions deferred to TZ-RGE-DUAL-MODE-DESIGN and beyond.
