---
name: live-trade-decision
description: Help the bot7 operator decide whether to manually execute a live trading signal (Range Hunter, cascade-followup, or other Phase-D setups) based on recent live performance vs backtest baselines. Use whenever the user asks "стоит ли открывать", "брать ли этот сигнал", "should I take this trade", "какая рекомендация по signal X", or pastes a TG-card from the bot and wants a sanity-check before placing manual orders on BitMEX. Also use when the user explicitly mentions Phase D, manual execution, semi-manual strategy, or decision support.
---

# Live Trade Decision Support

The bot7 operator runs semi-manual trading (Phase D): bot emits signal cards in TG, operator decides whether to place orders manually on BitMEX. This skill helps make that decision by comparing the current signal's profile to **recent live performance** and **backtest baselines**.

## When to use

- Operator pastes a TG-card (Range Hunter, cascade setup, etc) and asks for assessment
- "стоит ли брать этот сигнал?" / "should I trade this one?"
- "какая рекомендация" before placing orders
- Phase-D execution context — semi-manual decision support
- After a TG signal — quick health check before committing

## What this skill does NOT do

- Does **not** place orders on BitMEX (no trade API connected yet)
- Does **not** override the user's judgment — only provides data-grounded recommendation
- Does **not** apply to GinArea grid bots (those run automatically, no manual decisions)

## What to do

1. **Identify signal type** from user input:
   - Range Hunter (BUY+SELL limits with 0.10% spread, mention of mid/buy_level/sell_level)
   - Cascade-followup (LONG/SHORT after liquidations >X BTC)
   - Mega-setup (dump_reversal + pdl_bounce confluence)
   - P-15 cycle (HARVEST/REENTRY/CLOSE)
   - Other (ask user to clarify or skip recommendation)

2. **Run recommendation script** for context:
   ```bash
   python C:/Users/Kemper/.claude/skills/live-trade-decision/scripts/recommend.py --signal-type range_hunter
   ```
   Or on Mac:
   ```bash
   python ~/.claude/skills/live-trade-decision/scripts/recommend.py --signal-type range_hunter
   ```
   Pass `--signal-type` from step 1.

3. **Read live history** of similar signals (script outputs recent N records).

4. **Compose recommendation** for the user:
   - **GO** — if recent WR is in line with backtest, no health warnings
   - **CAUTION** — if some metrics off but not catastrophic; advise smaller size
   - **SKIP** — if edge_drift flag is on, or recent WR < 50%, or pending overload

5. **Quote the data** — never recommend without numbers. Example format:
   ```
   📊 Range Hunter signal review
   
   Recent live (7d): pair_win 65%, fill_rate 0.72 — within healthy range
   Backtest baseline: pair_win 68.5%, fill_rate 1.0
   Decision latency avg: 28s — fast enough
   
   ✅ GO recommendation: размер из карточки ($10k/leg), execute now
   ```

## Reference: signal-type → metric mapping

| Signal | Backtest WR | Healthy live WR | Source journal |
|---|---:|---:|---|
| Range Hunter pair-win | 68.5% | 60-75% | state/range_hunter_signals.jsonl |
| Cascade LONG bounce | 76% (in-sample only) | use SHORT→LONG version | state/cascade_accuracy.jsonl |
| Cascade SHORT→LONG (out-sample valid) | 71% | 60-75% | state/cascade_accuracy.jsonl |
| Mega-setup confluence | +5.7pp WR boost | check live separately | state/setups.jsonl |
| P-15 cycle | strategy-specific | check live separately | state/p15_equity.jsonl |

## Red flags — always SKIP if any of these

- `state/cascade_edge_drift.json` has a drifted=true entry for the signal's bucket
- Empirical fill rate < 0.65 over last 20+ closed trades
- 3+ consecutive losses on same signal type
- BitMEX margin alert active (check `state/short_t2_cliff_alerts.json`)
- Volatility spike not matching signal regime (e.g. Range Hunter signal but recent 1h move > 1%)

## Yellow flags — reduce size, do not skip outright

- WR drifted 5pp below backtest baseline
- Recent decision latency > 90s (signals getting stale)
- No signals fired in last 24h (regime shift?)
- Operator's portfolio at >50% margin used

## Green light — full size

- Recent WR within ±5pp of backtest
- All health metrics in healthy range
- No active drift flags
- Last 5 signals: ≥3 wins

## Decision template (always present)

```
📋 Signal: <type>
Levels: <entry/SL/TP from TG card>

Recent live (last <N> trades):
  WR: <X>% (vs backtest <Y>%)
  Avg PnL: $<Z>
  Fill rate (if applicable): <F>

Health flags: <none / list>

Recommendation: GO / CAUTION (reduce to $<S>) / SKIP (<reason>)
Action: <concrete next step in 1 sentence>
```
