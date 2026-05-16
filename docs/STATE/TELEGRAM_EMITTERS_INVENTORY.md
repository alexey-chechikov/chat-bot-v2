# Telegram Emitters Inventory

**Created:** 2026-05-05 (TZ-TELEGRAM-INVENTORY, P7)
**Scope:** Inventory only — recommendations included but no code changes.
**Method:** grep-trace through `core/`, `services/` for `send_message`, `send_telegram_alert`, `send_alert`, `notify`, direct `telebot` usage, and producer-loops.

> **2026-05-17 addendum**: 7 новых emitters добавлены. См. §1z ниже.

---

## §1z New emitters (2026-05-07 → 2026-05-17)

Все используют `services/telegram/channel_router.build_send_fn(telegram_app, "<CHANNEL>")` для маршрутизации:

| Emitter (loop) | Channel | Cadence | Что шлёт |
|---|---|---|---|
| `range_hunter_signal_btc/eth/xrp` × 1m + 5m | `RH_BTC` / `RH_ETH` / `RH_XRP` | At-signal | Per-symbol mean-revert карточки с VAL/VAH snap и paired-fill instructions. `[ETH]/[XRP]` префикс для не-BTC. |
| `confluence_loop` | `SETUP_ON` | At-event (dedup 30 min/direction) | High-conviction карточка когда 2+ сигнала одну сторону за 5 мин (из RH + cascade + watchlist + setup) с 2× size hint |
| `daily_self_report` | `ENGINE_ALERT` | 21:00 UTC | 24h digest: BitMEX margin, RH PnL per-symbol, watchlist outcomes, confluence fires, vol regime, edge drift |
| `volume_nodes` daily_digest | `ENGINE_ALERT` | 00:30 UTC | POC/VAH/VAL/width% для BTC/ETH/XRP, source label (`local_vol_profile` или `tv_*`) |
| `short_bots_guard` pause | `MARGIN_ALERT` | At-trigger | `⚠️ SHORT/LONG-BOTS AUTO-PAUSE` — affected aliases, до какого ts, эдж reasoning |
| `short_bots_guard` extend | `MARGIN_ALERT` | At-extend (60 min блоки) | `⏸ AUTO-PAUSE EXTENDED` — alias, причины (1h regime / cascade / vol / reversal absence) |
| `short_bots_guard` resume | `MARGIN_ALERT` | At-resume (safe или max-cap) | `✅ AUTO-RESUME` — alias, либо reversal override, либо max-cap hit (12h) |
| `pre_cascade_alert` | `SETUP_ON` | At-prefire | Pre-cascade entry plan карточка (с manual_levels POC context) |
| `weekly_audit_loop` | `ENGINE_ALERT` | Mon 10:00 UTC | Paper trader filter audit (gainers/losers) |
| `cascade_alert` (extended) | `SETUP_ON` | At-trigger | Cascade card + entry plan (с manual_levels POC, stop placement vs HVN) |

**TG receive handlers** (read-only, не emitters):
- `/levels [SYMBOL] [...]` — manual_levels.py CRUD
- `/positions` — managed bots + BitMEX positions snapshot
- `handle_text` TV-bridge: `LEVELS BTCUSD ...` / `TV:LEVELS ...` / `VPVR ...` → auto-parse → manual_levels store

См. полный snapshot в [HANDOFF_2026-05-17.md §2.3](../HANDOFF_2026-05-17.md).

---

## §1 Architecture (delivery layers)

```
                 ┌──────────────────────────────────────────────┐
                 │  TelegramAlertClient (services/telegram_     │
                 │  alert_client.py)                            │
                 │  Singleton. .send(text) → telebot.send_      │
                 │  message() to all configured chat_ids.       │
                 │  THIS IS THE BOTTLENECK — every alert        │
                 │  ultimately funnels through here.            │
                 └─────────────────▲────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────┐
        │                          │                      │
   send_telegram_alert()      ad-hoc bot.send_message()   sendBriefDelivery
   (services/                 (auto_edge_alerts,          (services/market_
   telegram_alert_service)    telegram_runtime,           forward_analysis/
                              claude_bot)                 delivery.py)
```

**Key finding:** there are **two** producer paths:
1. **Async / orchestrator path**: `send_telegram_alert(text)` → splits into chunks → calls `client.send()`. Used by orchestrator loop, protection alerts, grid managers.
2. **Sync / direct-bot path**: callers grab `bot` (telebot instance) and call `bot.send_message(chat_id, text)` directly. Used by `auto_edge_alerts`, command handlers, `claude_bot`.

The two paths do **not share dedup state**. This is the primary reason for the duplicate-RSI / duplicate-LEVEL_BREAK noise the operator complains about.

---

## §2 Emitter inventory table

| # | Emitter | File:line | Message kind | Trigger | Re-emit rule | Status |
|---|---------|-----------|--------------|---------|--------------|--------|
| 1 | **Orchestrator change alerts** | `core/orchestrator/orchestrator_loop.py:59` | "🔄 ОРКЕСТРАТОР: ИЗМЕНЕНИЕ" / regime/category change | every loop tick where `dispatch_orchestrator_decisions` returns `changed` | One-shot per change object (no own dedup; relies on dispatcher's `changed` semantics) | **ACTIVE** — primary synthesizer |
| 2 | **Orchestrator action alerts** | `core/orchestrator/orchestrator_loop.py:61` | Free-form alert text | every loop tick where `result.alerts` non-empty | One-shot per alert object | **ACTIVE** |
| 3 | **Daily orchestrator report** | `core/orchestrator/orchestrator_loop.py:102` | Daily summary (calibration log) | once/day at `ORCHESTRATOR_DAILY_REPORT_TIME` | Date-keyed (`_last_daily_report_date`) | **ACTIVE — well-bounded** |
| 4 | **Auto edge alerts (RSI/EXTREME/LEVEL_BREAK)** | `core/auto_edge_alerts.py:442` | RSI extremes + 1h/15m level events | Polling: 60s interval, runs `build_auto_edge_alert` per timeframe | Cooldown 180s (key = `{chat_id}:{timeframe}`); hysteresis on price+RSI threshold | **ACTIVE — noisy** (suspect for op's dup-RSI complaints) |
| 5 | **Setup detector cards** | `services/setup_detector/loop.py:154-159` | Per-setup card (LONG_PDL_BOUNCE, SHORT_RALLY_FADE, etc) via `format_telegram_card()` | 5min loop, when detector + combo filter + min_strength pass | One-shot per `Setup` record stored to `SetupStorage` (idempotent on `setup_id`) | **ACTIVE — gated, low-noise** |
| 6 | **Protection alerts** | `services/protection_alerts.py:172` | `BTC_FAST_MOVE_*`, `POSITION_STRESS_*`, `LIQ_DANGER_*` | Each `tick()` evaluates thresholds | `_should_send(key, debounce_min)` — N-min cooldown per (alert_kind, alias, level) | **ACTIVE — debounced** |
| 7 | **Adaptive grid manager** | `services/adaptive_grid_manager.py:587` | Grid `_tighten` / `_release` notifications | Per-bot tick when state transitions cross config thresholds | Implicit — only emits on state transition (not every tick) | **ACTIVE — state-change gated** |
| 8 | **Boundary expand manager** | `services/boundary_expand_manager.py:470` | "Boundaries expanded for bot X" | When eligibility check + cooldown pass | Per-alias state file + cooldown | **ACTIVE — state-change gated** |
| 9 | **Counter-long manager** | `services/counter_long_manager.py:406` | Counter-long position adjustments | Each tick where direction-flip rule fires | Per-alias state file | **ACTIVE — state-change gated** |
| 10 | **market_forward_analysis briefs** | `services/market_forward_analysis/loop.py:110-145` + `delivery.py:82` | SESSION BRIEF / PHASE_CHANGE / FORECAST_SHIFT (3 trigger types from `delivery.should_send`) | Morning 08:00 UTC + regime change + 1h prob shift > 0.15 | DeliveryState in-memory: last_brief_time / last_regime / last_prob_up_1h | **ACTIVE — well-bounded** (built today) |
| 11 | **claude_bot conversational** | `services/claude_bot/bot.py:108` | Free-form replies to operator commands | On `@bot` mention or DM | None (interactive) | **ACTIVE — request-driven, not periodic** |
| 12 | **telegram_runtime command handlers** | `core/services/telegram_runtime.py:247-382` | Replies to /handoff, /status, /queue, button presses | On user input | None (interactive) | **ACTIVE — request-driven** |
| 13 | **scripts/done.py** | `scripts/done.py` | Worker completion ping (informal) | When worker calls done.py from CLI after a TZ | None | **ACTIVE — manual** |
| 14 | **scripts/state_snapshot.py** | `scripts/state_snapshot.py` | State snapshot ping | On schedule | Schedule-driven | **LEGACY?** — needs verification (separate from dashboard JSON refresh) |
| 15 | **scripts/watchdog.py** | `scripts/watchdog.py` | Process-up watchdog | On detection of process death | Each event triggers one alert | **LEGACY?** — overlaps orchestrator health monitoring |
| 16 | **core/handlers/command_actions.py** | `core/handlers/command_actions.py` | Replies to operator commands | On user input | None (interactive) | **ACTIVE — request-driven** |
| 17 | **core/integration_decision.py** | `core/integration_decision.py` | Legacy decision pings | Likely from older advise_v1 path | Unclear | **ORPHAN suspect** — likely superseded by orchestrator |
| 18 | **core/btc_elite_plus_fast.py** | `core/btc_elite_plus_fast.py` | Fast-track BTC alerts | Older detector path | Unclear | **ORPHAN suspect** — predates phase classifier |

---

## §3 Dedup gaps

| Emitter | State-change check? | Cluster-aware? | Cooldown/throttle? | Gap severity |
|---------|--------------------|-----------------|--------------------|--------------|
| 1. Orchestrator change | ✅ via `dispatcher.changed` | ❌ no — each change → own alert | ❌ none | LOW (changes are real events) |
| 4. Auto edge alerts | ⚠️ partial (hysteresis) | ❌ no — same RSI extreme on 15m+1h emits twice | ✅ 180s cooldown per (chat, tf) | **HIGH** — primary suspect for dup-RSI |
| 5. Setup detector | ✅ stored by setup_id | ❌ no — multiple setups same bar → multiple cards | ❌ none beyond combo filter | MEDIUM |
| 6. Protection alerts | ✅ via `_should_send` | ❌ no — same threshold breach on multiple bots → multiple alerts | ✅ debounce_min per key | LOW (debounce works) |
| 7-9. Grid managers | ✅ state files | ❌ N/A (per-bot scope) | ✅ implicit per-bot | LOW |
| 10. market_forward briefs | ✅ DeliveryState | ❌ N/A (single brief) | ✅ 3 trigger types only | LOW (well-bounded) |
| 14-15. Legacy scripts | ❌ unclear | ❌ N/A | ❌ unclear | UNKNOWN — needs trace |
| 17-18. Orphan suspects | ❌ unclear | ❌ N/A | ❌ unclear | UNKNOWN — needs trace |

**Cross-emitter gap:** no global dedup. Auto edge alerts and orchestrator both can fire on the same regime/RSI shift if they happen on overlapping ticks. Setup detector card + orchestrator change alert can both reference the same level break. **Nothing in the codebase coordinates between the two producer paths** (async `send_telegram_alert` vs direct `bot.send_message`).

---

## §4 Concrete examples (from operator-reported patterns)

The operator's brief named four specific examples seen in the live channel. Mapping each to the most likely emitter:

### 4.1 Duplicated RSI 06:09 / 06:40 / 07:10 / 07:40

**Cadence:** ~30 minutes between repetitions. **Likely emitter: #4 Auto edge alerts.**

Mechanism: `core/auto_edge_alerts.py` polls `15m` and `1h` timeframes at 60s intervals. Cooldown is 180s (3 min). Hysteresis check (`_passes_hysteresis`) requires a price+RSI threshold cross; if RSI hovers around the extreme line for hours, every threshold cross past 180s emits a fresh alert.

The 30-min cadence in the operator's screenshots matches **N×180s (cooldown) + the time RSI takes to drift back-and-forth across the threshold band**. This is exactly the noisy-hysteresis pattern.

### 4.2 Cluster LEVEL_BREAK 12:19 at 78523/78494

Two LEVEL_BREAK alerts within 30 seconds at very close prices (Δ=29). **Likely emitter: #4 Auto edge alerts** firing on the 15m AND 1h timeframe simultaneously, OR Setup detector firing two LIQ_MAGNET/PDL setups at the same 1m bar.

Mechanism: no cluster-aware grouping in any emitter. The "if two levels are within 0.05% of each other, emit one consolidated message" logic does not exist anywhere in the code.

### 4.3 Whipsaw 78862 (12:33 up) → 78862 (12:57 down)

Two opposite-direction LEVEL_BREAKS at the **same price** within 24 minutes. **Likely emitter: #4 Auto edge alerts.**

Gap: no level-rejection / fake-breakout marker. The emitter treats each crossing of a price level as an independent event; it does not record that the level was "tested and rejected" and downgrade subsequent crossings.

### 4.4 Broken ASCII in metrics block

This is a **render** bug, not an emit-frequency bug. Most likely candidates:
- `core/renderers/telegram_renderers.py` — formats orchestrator output
- `core/telegram_formatter.py` — generic formatter
- `services/setup_detector/telegram_card.py` — setup card rendering

Without an actual screenshot showing which message kind has broken ASCII, the inventory cannot pinpoint further. **Recommendation:** when operator next sees broken ASCII, screenshot + paste — a single line of bad output usually identifies the renderer.

---

## §5 Recommendations

| # | Emitter | Action | Reasoning |
|---|---------|--------|-----------|
| 1 | Orchestrator change | **PROMOTE** to PRIMARY | Already the synthesizer; should be the canonical operator-facing channel for state changes. |
| 2 | Orchestrator action alerts | **OK as-is** | Bounded; keep |
| 3 | Daily report | **OK as-is** | Date-keyed, well-bounded |
| 4 | Auto edge alerts | **DEDUP-WRAP** + consider DEPRECATE | Highest noise source. Either (a) wrap with cluster-aware dedup AND make cooldown ≥30 min on flapping signals, or (b) decommission entirely and let orchestrator change alerts subsume the role. Operator sees no clear value the orchestrator alerts don't already cover. |
| 5 | Setup detector | **DEDUP-WRAP** | Add per-bar dedup (one card per bar regardless of N detectors firing) and a `setup_class` cluster (e.g. all `*_PDL_*` collapse into one card). |
| 6 | Protection alerts | **OK as-is** | Debounce works; categories are critical |
| 7-9 | Grid managers | **OK as-is** | State-change gated, low volume |
| 10 | market_forward briefs | **OK as-is + extend** | Well-bounded; right place to plug in sizing decisions when P7-Telegram-output is ready (replaces blocked sizing channel from block 3) |
| 11-12 | claude_bot / runtime cmds | **OK as-is** | Request-driven |
| 13 | done.py | **OK as-is** | Manual, low-frequency |
| 14 | state_snapshot.py | **VERIFY then DEPRECATE** | Likely overlaps with dashboard JSON refresh + orchestrator daily |
| 15 | watchdog.py | **VERIFY then likely DEPRECATE** | Process-health is orchestrator's job |
| 16 | command_actions | **OK as-is** | Request-driven |
| 17 | integration_decision | **TRACE → likely DEPRECATE** | Suspect orphan from advise_v1 |
| 18 | btc_elite_plus_fast | **TRACE → likely DEPRECATE** | Predates phase classifier |
| – | Broken ASCII rendering | **FIX** (separate TZ) | Need screenshot to localize the renderer |

### Strategic recommendation: collapse to two channels

Long-term direction (NOT this TZ — for TZ-ALERT-DEDUP-LAYER and TZ-SYNTH-PROMOTE):

```
PRIMARY channel (default):
  - Orchestrator change alerts
  - Orchestrator daily report
  - market_forward briefs (morning + regime change + forecast shift)
  - Sizing decision deliveries (currently blocked, will join here)

VERBOSE channel (/verbose toggle, off by default):
  - Auto edge alerts (after dedup-wrap)
  - Setup detector cards (after per-bar dedup)
  - Protection alerts (already debounced — fine)
```

Deprecating emitters #14, #15, #17, #18 likely cuts daily volume by 30-50% on its own (assuming they fire periodically — needs trace verification before deletion).

---

## §6 Trace-verification next steps (NOT this TZ)

For TZ-ALERT-DEDUP-LAYER prep, the orphan suspects need confirmation:

1. **#14 state_snapshot.py** — when last invoked? Check `docs/STATE/ohlcv_ingest_log.jsonl` and process logs for last call.
2. **#15 watchdog.py** — same.
3. **#17 integration_decision.py** — grep for callers of its public functions; if no callers in active code path → orphan confirmed.
4. **#18 btc_elite_plus_fast.py** — same.

Each verification is a 5-min trace. Total ~20 min before any deprecation can be safely scheduled.

---

## §7 Summary

- **18 emitters mapped**, of which **5 are well-bounded** (orchestrator change/daily, market_forward briefs, protection alerts, request-driven handlers).
- **2 emitters are major noise sources**: #4 auto_edge_alerts (RSI flap), and to a lesser degree #5 setup_detector (multiple cards/bar).
- **4 suspect orphans** (#14, #15, #17, #18) need trace verification before deprecation.
- **Cross-emitter coordination** is the structural gap: no shared dedup state between async and direct-bot paths.
- **Operator pain examples** map cleanly to the noise sources identified — the inventory is consistent with the lived experience.
- **No emitters were edited or deprecated in this TZ.** All actions deferred to TZ-ALERT-DEDUP-LAYER, TZ-SYNTH-PROMOTE, TZ-METRICS-RENDER-FIX.
