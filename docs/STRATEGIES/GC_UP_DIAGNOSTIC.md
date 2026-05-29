# GC UP-exhaustion — diagnostic backtest

**Window:** 2026-05-07 12:45:26+00:00 -> 2026-05-29 10:26:52+00:00  (21.9d, live-faithful)
**Feed:** state/deriv_live_history.jsonl (6061 snapshots, ~5min)
**Window net BTC drift:** -8.9%  (regime context — see caveat)
**FADE trade (current live emit):** SHORT entry@close, stop +0.5%, tp -0.75%, hold 4h, fees 0.165% RT
**CONTINUATION trade (proposed mirror):** LONG entry@close, stop -0.5%, tp +0.75%, hold 4h, fees 0.165% RT

`ev` = net expectancy %/trade after fees. `sum` = total net %. **Deduped** = non-overlapping 4h trades (independent edge). UP fires on the **1h main loop only** (score>=3); the 15m intraday loop is downside-only, so there is no 15m UP path. Mirror of `GC_DOWN_DIAGNOSTIC.md`.

## Fade (current SHORT) vs Continuation (LONG) — by score, deduped

| score | n | FADE WR% | FADE EV% | FADE PF | CONT WR% | CONT EV% | CONT PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| >=3 | 12 | 16.7 | -0.397 | 0.113 | 41.7 | +0.042 | 1.207 |
| >=4 | 4 | 50.0 | -0.040 | 0.88 | 50.0 | -0.151 | 0.544 |
| >=5 | 3 | 33.3 | -0.248 | 0.44 | 66.7 | +0.020 | 1.089 |
| >=6 | 1 | 100.0 | +0.585 | 999.0 | 0.0 | -0.665 | 0.0 |

## Slices (score>=3, deduped) — regime / corr / core signal

Same slicing the DOWN diagnostic used. FADE = current SHORT emit; CONT = LONG mirror. A continuation edge shows CONT beating FADE (and ideally the baseline) within each favorable slice.

| slice | n | FADE WR% | FADE EV% | CONT WR% | CONT EV% | CONT PF |
|---|---:|---:|---:|---:|---:|---:|
| ADX < 20 (range) | 1 | 0.0 | -0.665 | 0.0 | -0.151 | 0.0 |
| ADX 20-25 | 0 | — | — | — | — | — |
| ADX >= 25 (trend) | 11 | 18.2 | -0.372 | 45.5 | +0.059 | 1.287 |
| uptrend (ret24h>+1%) | 10 | 10.0 | -0.502 | 50.0 | +0.073 | 1.417 |
| ADX>=25 AND uptrend | 9 | 11.1 | -0.484 | 55.6 | +0.098 | 1.551 |
| NOT(ADX>=25 & uptrend) | 4 | 25.0 | -0.267 | 25.0 | -0.060 | 0.709 |
| corr > 0.95 | 7 | 14.3 | -0.303 | 28.6 | +0.011 | 1.071 |
| corr <= 0.95 | 5 | 20.0 | -0.415 | 60.0 | +0.085 | 1.32 |
| core present (mfi_high|vol) | 10 | 40.0 | -0.137 | 30.0 | -0.292 | 0.2 |
| core ABSENT | 3 | 0.0 | -0.550 | 66.7 | +0.387 | 131.977 |

## Gate search — can the FADE (SHORT) be salvaged? (deduped)

| gate | n | WR% | EV% | PF | sum% |
|---|---:|---:|---:|---:|---:|
| score>=3 (baseline) | 12 | 16.7 | -0.397 | 0.113 | -4.8 |
| score>=4 | 4 | 50.0 | -0.040 | 0.88 | -0.2 |
| score>=5 | 3 | 33.3 | -0.248 | 0.44 | -0.8 |
| score>=3 + core | 10 | 40.0 | -0.137 | 0.565 | -1.4 |
| score>=3 + uptrend | 10 | 10.0 | -0.502 | 0.005 | -5.0 |
| score>=3 + corr<=0.95 | 5 | 20.0 | -0.415 | 0.22 | -2.1 |
| score>=4 + core | 4 | 50.0 | -0.040 | 0.88 | -0.2 |

## Continuation test — raw BTC move after up-fire (deduped 4h)

If consistently POSITIVE, the signal is continuation (LONG correct); if negative, the fade (SHORT) advice is sound. `%UP@4h` = share of fires higher 4h later.

| score | n | mean +1h% | mean +4h% | mean +8h% | %UP@4h |
|---|---:|---:|---:|---:|---:|
| >=3 | 12 | +0.374 | +0.260 | +0.260 | 58.3 |
| >=4 | 4 | +0.369 | +0.388 | +0.244 | 75.0 |
| >=5 | 3 | +0.398 | +0.737 | +0.607 | 100.0 |
| >=6 | 1 | +0.075 | -0.721 | +0.006 | 0.0 |

## Baseline control — unconditional LONG (every hour, no signal)

Same LONG trade fired on a regular hourly grid, ignoring the signal — the regime base rate. The continuation LONG must BEAT it to have real edge. NB: the net-bearish window makes this base rate poor by construction, so beating it is a high bar.

**Unconditional LONG (deduped n=132):** WR=30.3%, EV=-0.235%, PF=0.285, %UP@4h=48.1.

## Verdict

**UP looks like continuation too, but the edge is WEAK / regime-contingent.** The LONG mirror is +EV and beats the (bearish-window) base rate, and the SHORT fade is no better, but the margin is thin and/or non-monotone (top cell WR=50.0%, EV=-0.151%, PF=0.544, n=4; FADE base EV=-0.397%; unconditional-LONG base EV=-0.235%, WR=30.3%). Given the net-bearish window (-8.9%), up-continuation is the hard direction and is likely understated here. Lean LONG-continuation but treat as provisional.

**Action (provisional):** re-label «🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ» and flip paper-emit to LONG to start collecting live-faithful continuation outcomes, flagging low conviction until a ranging/bullish window confirms.

**Caveat (regime):** 22d, deduped n small per cell, window net BTC drift -8.9% (net-bearish). An up-continuation edge must swim against that drift, so it reads weaker / more regime-contingent than the down side. Re-validate after a ranging/bullish stretch and on accumulating live paper outcomes before trusting it.
