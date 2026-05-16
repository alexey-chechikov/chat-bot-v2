---
name: range-hunter-status
description: Quick status check for the Range Hunter semi-manual trading strategy in bot7. Reports current statistics from state/range_hunter_signals.jsonl — pair_win%, empirical fill rate, decision latency, total PnL, pending decisions. Use this whenever the user asks about Range Hunter performance, "how is range hunter doing", "проверь range hunter", "какие результаты по range_hunter", "сколько сигналов", "сколько fills", or after a fresh restart to verify the strategy is collecting data. Also use when the user mentions empirical_fill_rate, pair_win, decision_latency, or anything else from the Range Hunter journal.
---

# Range Hunter Status

Quick health-check for the Range Hunter strategy. Reads `state/range_hunter_signals.jsonl` and reports the key live metrics.

## When to use

- User asks "как там range hunter", "range hunter status", "сколько сигналов было"
- After a restart of `app_runner` — verify the strategy is emitting signals
- Before live-trade decisions — see if recent fill rate is healthy (≥ 0.65)
- During weekly review — compare empirical metrics with backtest baseline (WR 68.5%, fill rate 1.0)

## What to do

1. Run the bundled script to compute stats from the journal:
   ```bash
   cd c:/bot7   # or wherever the project root is
   python C:/Users/Kemper/.claude/skills/range-hunter-status/scripts/rh_status.py
   ```
   On Mac the script path is:
   ```bash
   python ~/.claude/skills/range-hunter-status/scripts/rh_status.py
   ```

2. The script outputs a structured summary. Format it for the user as a short report with:
   - **Total signals** / placed / skipped / pending decision
   - **Pair-win rate** (target: ≈68.5% from backtest)
   - **Empirical fill rate** (target: ≥ 0.65 — below this edge is broken)
   - **Total PnL** since start
   - **Avg decision latency** (manual mode: ideally < 30 sec)
   - **Last signal** timestamp

3. If empirical fill rate has dropped below 0.65 — **flag this** to the user. Edge may be dying. Recommend pausing manual execution until investigated.

4. If no signals fired in last 24h — that's normal (avg ~3/day, can have gaps in trending markets). Just note the gap.

## What NOT to do

- Don't generate fake numbers if the journal is empty — say "no data yet"
- Don't recommend specific trades based on this status (that's the live-trade-decision skill)
- Don't try to "fix" old records — read-only inspection

## Reference: backtest baseline

For comparison when reporting:

| Metric | Backtest baseline | Healthy live range |
|---|---:|---:|
| Pair win % | 68.3-68.5% | 60-75% |
| Empirical fill rate | 1.0 (theoretical) | 0.65-0.85 |
| Avg PnL pair_win | +$24.0 | ±10% |
| Avg PnL single-leg SL | -$25.5 | ±10% |
| Signals/day | 2.89 | 2-5 |
| Walk-forward DD | -$222 (worst fold) | < -$500 |

If live metrics drift outside healthy range → flag, don't ignore.
