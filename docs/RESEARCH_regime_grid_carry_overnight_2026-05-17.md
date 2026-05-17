# Regime-conditional grid (carry-overnight) — Phase 3.6 v2

**Difference from v1:** continuous 2y simulation (position carries over),
instead of daily-isolated. Phase 3.6 v1 had artifact `avg_DD=$0` because each
day reset state. This version captures real cross-day drawdowns.

**Total 2y net:** $+593,458
**Total volume:** $+2,554,088,000
**Max DD (cumulative net):** $-456
**Vol thresholds (ATR %):** LOW < 0.047% < MED < 0.073% < HIGH

## Matrix avg daily net (carry-overnight)

| Regime | LOW | MEDIUM | HIGH |
|---|---|---|---|
| RANGE | $+93 (n=204, neg=23.5%) | $+379 (n=138, neg=6.5%) | $+1,645 (n=89, neg=0.0%) |
| TREND_UP | $+172 (n=24, neg=20.8%) | $+461 (n=57, neg=1.8%) | $+1,793 (n=67, neg=0.0%) |
| TREND_DOWN | $+284 (n=14, neg=0.0%) | $+477 (n=54, neg=3.7%) | $+2,273 (n=86, neg=0.0%) |

## Negative-day % per cell — risk indicator
Days with negative net (loss days) as % of cell's days.

| Regime | LOW | MEDIUM | HIGH |
|---|---|---|---|
| RANGE | 23.5% | 6.5% | 0.0% |
| TREND_UP | 20.8% | 1.8% | 0.0% |
| TREND_DOWN | 0.0% | 3.7% | 0.0% |

## Comparison vs v1 (daily-isolated)

| Cell | v1 avg | v2 avg (carry) | delta |
|---|---|---|---|
| RANGE/LOW | $+90 | $+93 | $+4 |
| RANGE/MEDIUM | $+387 | $+379 | $-9 |
| RANGE/HIGH | $+1,643 | $+1,645 | $+2 |
| TREND_UP/LOW | $+184 | $+172 | $-12 |
| TREND_UP/MEDIUM | $+458 | $+461 | $+2 |
| TREND_UP/HIGH | $+1,796 | $+1,793 | $-3 |
| TREND_DOWN/LOW | $+282 | $+284 | $+2 |
| TREND_DOWN/MEDIUM | $+469 | $+477 | $+8 |
| TREND_DOWN/HIGH | $+2,273 | $+2,273 | $+0 |

## Применение

Use `state/bot_brain_regime_grid_config_v2.json` for sizing decisions.
`neg_day_pct` is the risk-side companion to `avg_net` — cell with 70% +days
and low DD is safer than cell with 50% +days even if average higher.

⚠ Real-world deviations:
- BitMEX slippage (not modeled)
- Funding payments accumulation (not modeled)
- Exchange outages / data gaps
- Simulator uses fixed sweet-spot params; live bot may be tuned differently