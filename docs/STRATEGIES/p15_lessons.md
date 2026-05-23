# p15 strategy — postmortem (2026-05-23)

**Status:** DISABLED via `state/disabled_detectors.json` token `p15`
(substring match → both `detect_p15_long` and `detect_p15_short`).
Code retained (`services/setup_detector/p15_rolling.py`,
`services/paper_trader/p15_handler.py`) for reference — do NOT
re-enable without reading this file first.

**Evidence:** `state/p15_paper_trades.jsonl` (107 OPEN / 56 HARVEST /
59 CLOSE over ~2 weeks). **Closing WR: 0/59 = 0%**. Cumulative
paper PnL: **−$1334.15** (LONG −$1125 / SHORT −$209).

Forensic script: `scripts/pump_research/_p15_forensic.py` — re-run
any time to refresh numbers.

---

## What p15 was supposed to do

Phase-15 rolling layered strategy:
- `OPEN`  — first layer ($1000 notional).
- `HARVEST` — close 50% of position when price moves favourably.
- `REENTRY` — add another $1000 layer at a price offset (avg-down).
- `CLOSE` — full exit on trend-filter flip / dd_cap breach / time-stop.

Idea: contrarian averaging on mean-reverting moves; trend filter
keeps you from compounding in a sustained trend.

## Why it doesn't work — three conflicting mechanics

| # | Mechanic | Conflict |
|---|---|---|
| 1 | Avg-down (Martingale-class) | Adds inventory **against** the price move — concept needs mean-reverting market |
| 2 | EMA50/EMA200 trend-filter EXIT | **Lagging** indicator — crosses **after** price has already moved 1.5-3% adverse → close at the worst point |
| 3 | 3% drawdown cap | Hard-stop on unrealised loss. By layer 6 (notional ~$6k), 3% = $180 — trivially achievable in normal vol → forced close |

These three mechanics fight each other. Either you let avg-down run
(loosen dd_cap, drop trend exit) and accept catastrophic tail risk,
or you keep dd_cap and the avg-down never gets to recover.

## Smoking-gun numbers

CLOSE reason distribution (n=59):

| reason | n | sum PnL | % of total loss |
|---|---|---|---|
| `dd_cap 3.0% breached` | 26 | −$955 | **72%** |
| `trend gate flipped (EMA50<EMA200)` | 21 | −$266 | 20% |
| `trend gate flipped (EMA50>EMA200)` | 11 | −$112 | 8% |
| `time-stop 48h held` | 1 | −$1 | — |

**Zero TP-based exits.** The strategy never closed in profit on the
full-position exit path. All wins were micro-partials on HARVEST.

HARVEST (partials): n=56, WR 50%, total **+$18.50** (mean +$0.33).
The strategy CAPTURES tiny upside, then the full-position CLOSE drains
it ~70× over. Asymmetric R:R: +$0.33 win vs −$22.60 mean loss.

Layer count at CLOSE — 44% of closes happen at layer 6 (out of typical
1-9). 56% of all losses ($749) come from layer-6 closes. Avg-down
ratchets up to 6 layers before dd_cap forces close.

Slippage at CLOSE relative to avg_entry — median −1.64%, p10 −3.33%.
Closes happen ~1.5-3% adverse from average entry.

## What would need to change to revive (don't, but if you must)

Each is necessary; none is sufficient alone.

1. Replace EMA50/EMA200 trend exit with TP-based exit (e.g. close
   full when avg_entry +0.5% reached). The trend filter exit is the
   single biggest design flaw.
2. Tighten layer cap from 9+ to 3. Limits notional explosion.
3. Loosen dd_cap from 3% to 5-7%. With layer cap 3, total exposure
   $3000 — 5% = $150, still tolerable.
4. Add regime filter ON ENTRY (not exit) — only fire p15-LONG in
   `range_wide` or `consolidation` regimes; never in `trend_down`.
   The trend-filter belongs at the ENTRY decision, not the EXIT.

After all four — paper-test 2+ weeks. Expect WR ~50-55% with
tighter losses; not obvious that's tradeable either. The underlying
"avg-down in crypto" thesis is fragile — one ETH/BTC trend day wipes
weeks of micro-profits (the May-22 dump is a recent example).

## Cross-references

- Decision audit: `_paper_perf_audit.py` ran 2026-05-23 — p15 0/59.
- Disable record: `state/disabled_detectors.json` (`"p15"` token,
  note dated 2026-05-23).
- Code paths kept (disabled): `services/setup_detector/p15_rolling.py`,
  `services/paper_trader/p15_handler.py`.
- Universal `paper_wr_gate` (services/common/paper_wr_gate.py) also
  flags `p15::long` and `setup_detector::p15_long_close` as
  unhealthy — independent confirmation.

## Decision summary

- 2026-05-23: disabled via runtime token (hot-reload).
- Code NOT deleted — kept for lesson reference. If you reach for p15
  again, READ THIS FILE FIRST.
