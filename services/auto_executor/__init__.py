"""Auto-executor: live BitMEX trading for selected setup_detector setups.

Architecture (2026-05-24):

  setup_detector → setups.jsonl → auto_executor.loop reads new entries
                                  ↓
                                  gates.can_open(setup, state)
                                    - setup_type in allow-list
                                    - pair == BTCUSDT
                                    - max_parallel = 1
                                    - paper_wr_gate.should_emit OK
                                    - 7d kill-switch not frozen
                                    - daily_pnl > -$3
                                    - balance > $40 floor
                                    - <5 consecutive losses (or freeze expired)
                                  ↓ if allowed
                                  bitmex_client.place_limit_buy
                                  ↓ TG notify OPEN
                                  monitor loop: poll price/position every tick
                                    - if last_price <= sl_price  → market exit + SL card
                                    - if last_price >= tp1_price → market exit + TP1 card
                                    - if now >= expires_at        → market exit + EXPIRE card

State files:
  state/auto_executor_state.json        — current open positions + daily counters
  state/auto_executor_outcomes.jsonl   — closed-trade log (feeds 7d kill-switch)
  state/auto_executor_offset.json       — last-seen byte offset in setups.jsonl

Allow-list (2026-05-24 audit per paper_trades.jsonl):
  long_pdl_bounce       — n=16 WR 50% +$1619, 14d WR 33% n=12
  long_multi_divergence — n=60 WR 88% +$5925, 14d WR 46% n=13, dormant since 05-20
"""
