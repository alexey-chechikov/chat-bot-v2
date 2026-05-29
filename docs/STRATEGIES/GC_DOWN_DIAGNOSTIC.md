# GC DOWN-exhaustion fade — diagnostic backtest

**Window:** 2026-05-07 12:45:26+00:00 -> 2026-05-29 10:06:26+00:00  (21.9d, live-faithful)
**Feed:** state/deriv_live_history.jsonl (6057 snapshots, ~5min)
**Trade modeled:** LONG entry@close, stop -0.5%, tp +0.75%, hold 4h, fees 0.165% RT

`ev` = net expectancy %/trade after fees. `sum` = total net %. **Deduped** = non-overlapping 4h trades (independent edge); **raw** = every qualifying 5-min snapshot.

## 15m intraday (live: score>=4)

**Baseline (score>=4):** raw n=337 WR=32.9% EV=-0.258% PF=0.283 | **deduped n=22 WR=27.3% EV=-0.342% PF=0.235 sum=-7.5%**

| slice | n(ded) | WR% | EV% | PF | sum% |
|---|---:|---:|---:|---:|---:|
| score == 3 | 28 | 21.4 | -0.298 | 0.172 | -8.3 |
| score == 4 | 20 | 25.0 | -0.330 | 0.223 | -6.6 |
| score == 5 | 13 | 15.4 | -0.495 | 0.063 | -6.4 |
| score == 6 | 7 | 14.3 | -0.560 | 0.018 | -3.9 |
| — regime — | | | | | |
| ADX < 20 (range) | 4 | 25.0 | -0.467 | 0.064 | -1.9 |
| ADX 20-25 | 5 | 0.0 | -0.506 | 0.0 | -2.5 |
| ADX >= 25 (trend) | 15 | 33.3 | -0.297 | 0.329 | -4.5 |
| downtrend (ret24h<-1%) | 12 | 16.7 | -0.499 | 0.099 | -6.0 |
| ADX>=25 AND downtrend | 9 | 22.2 | -0.444 | 0.141 | -4.0 |
| NOT(ADX>=25 & downtrend) | 16 | 25.0 | -0.345 | 0.231 | -5.5 |
| — corr — | | | | | |
| corr > 0.95 | 12 | 8.3 | -0.593 | 0.01 | -7.1 |
| corr <= 0.95 | 17 | 29.4 | -0.291 | 0.313 | -4.9 |
| — core signal — | | | | | |
| core present (mfi_low|vol) | 20 | 25.0 | -0.372 | 0.189 | -7.5 |
| core ABSENT | 3 | 33.3 | -0.061 | 0.762 | -0.2 |

## 1h main (live: score>=3)

**Baseline (score>=3):** raw n=994 WR=25.6% EV=-0.282% PF=0.25 | **deduped n=27 WR=14.8% EV=-0.396% PF=0.116 sum=-10.7%**

| slice | n(ded) | WR% | EV% | PF | sum% |
|---|---:|---:|---:|---:|---:|
| score == 3 | 19 | 10.5 | -0.396 | 0.102 | -7.5 |
| score == 4 | 17 | 17.6 | -0.435 | 0.047 | -7.4 |
| score == 5 | 9 | 0.0 | -0.598 | 0.0 | -5.4 |
| score == 6 | 4 | 0.0 | -0.550 | 0.0 | -2.2 |
| — regime — | | | | | |
| ADX < 20 (range) | 4 | 25.0 | -0.431 | 0.135 | -1.7 |
| ADX 20-25 | 5 | 0.0 | -0.665 | 0.0 | -3.3 |
| ADX >= 25 (trend) | 22 | 18.2 | -0.369 | 0.106 | -8.1 |
| downtrend (ret24h<-1%) | 26 | 19.2 | -0.343 | 0.182 | -8.9 |
| ADX>=25 AND downtrend | 22 | 22.7 | -0.319 | 0.181 | -7.0 |
| NOT(ADX>=25 & downtrend) | 11 | 18.2 | -0.499 | 0.083 | -5.5 |
| — corr — | | | | | |
| corr > 0.95 | 18 | 22.2 | -0.294 | 0.198 | -5.3 |
| corr <= 0.95 | 10 | 10.0 | -0.530 | 0.048 | -5.3 |
| — core signal — | | | | | |
| core present (mfi_low|vol) | 25 | 12.0 | -0.428 | 0.076 | -10.7 |
| core ABSENT | 3 | 33.3 | -0.190 | 0.507 | -0.6 |

## Gate search — 15m (find best filter, n>=12 deduped)

| gate | n | WR% | EV% | PF | sum% |
|---|---:|---:|---:|---:|---:|
| score>=4 (baseline) | 22 | 27.3 | -0.342 | 0.235 | -7.5 |
| score>=5 | 13 | 15.4 | -0.495 | 0.063 | -6.4 |
| score>=6 | 7 | 14.3 | -0.560 | 0.018 | -3.9 |
| score>=4 + core | 20 | 25.0 | -0.372 | 0.189 | -7.5 |
| score>=4 + NOT trend | 16 | 25.0 | -0.345 | 0.231 | -5.5 |
| score>=4 + corr<=0.95 | 17 | 29.4 | -0.291 | 0.313 | -4.9 |
| score>=5 + core | 13 | 15.4 | -0.495 | 0.063 | -6.4 |
| score>=5 + NOT trend | 9 | 11.1 | -0.501 | 0.075 | -4.5 |
| score>=4 + core + NOT trend | 15 | 20.0 | -0.407 | 0.15 | -6.1 |
| score>=5 + core + NOT trend | 9 | 11.1 | -0.501 | 0.075 | -4.5 |

## Continuation test — does the signal predict MORE downside?

Raw BTC move after a down-fire (no TP/SL). If consistently negative, the card's *'close LONG grids'* advice is sound even though FADING (going long) loses. Deduped 4h, mean raw % move.

| set | n | mean +1h% | mean +4h% | mean +8h% | %down@4h |
|---|---:|---:|---:|---:|---:|
| 15m score>=4 | 22 | -0.278 | -0.275 | -0.373 | 72.7 |
| 15m score>=5 | 13 | -0.506 | -0.507 | -0.526 | 76.9 |
| 15m score>=6 | 7 | -0.486 | -0.470 | -0.490 | 85.7 |
| 1h score>=3 | 27 | -0.205 | -0.420 | -0.483 | 74.1 |
| 1h score>=5 | 9 | -0.745 | -0.643 | -0.602 | 88.9 |

### SHORT-continuation trade (mirror: short@close, stop +0.5%, tp -0.75%, 4h) — deduped

| set | n | WR% | EV% | PF | sum% |
|---|---:|---:|---:|---:|---:|
| 15m score>=4 | 22 | 63.6 | +0.146 | 1.885 | +3.2 |
| 15m score>=5 | 13 | 69.2 | +0.263 | 2.855 | +3.4 |
| 15m score>=6 | 7 | 85.7 | +0.353 | 4.72 | +2.5 |
| 1h score>=3 | 27 | 55.6 | +0.126 | 1.687 | +3.4 |
| 1h score>=4 | 19 | 73.7 | +0.349 | 5.239 | +6.6 |
| 1h score>=5 | 9 | 77.8 | +0.375 | 10.729 | +3.4 |

## Baseline control — unconditional SHORT (every hour, no signal)

Same short trade fired on a regular hourly grid across the window, ignoring the signal. This is the regime base rate; the signal must beat it to have real edge (not just 'it was a bear month').

**Unconditional short (deduped n=132):** WR=39.4%, EV=-0.067%, PF=0.738, %down@4h=51.9.

Signal lift (1h score>=5 vs baseline): WR +38.4pp is illustrative — see tables above. Monotonic rise of WR/PF with score is the key tell of real edge.

## Verdict

**The signal is predictive — but of CONTINUATION, not reversal.** Fading (LONG) loses in every slice and gets *worse* as score rises (score 6 WR ~14%). The mirror SHORT trade is +EV and WR/PF rise monotonically with score (1h score>=5: WR 78%, PF 10.7). `🔻 НИЗ ИСТОЩАЕТСЯ` is mislabeled: it is a downside-momentum / continuation signal, not an exhaustion/reversal one.

**Action:** (1) re-label + re-frame the card as 'downside continues -> protect/close LONG grids or short', (2) flip paper-emit from the disabled LONG fade to SHORT continuation, (3) raise conviction with score (>=5 strongest), (4) keep flicker-dedup. The original 2026-05-23 audit was right to kill the LONG side — it had the polarity inverted, not a dead signal.

**Caveat:** 22d, deduped n~20-27 per cell, and the window was net-bearish — continuation edge is partly regime-contingent. Re-validate after a ranging/bullish stretch and on accumulating live paper-SHORT outcomes.
