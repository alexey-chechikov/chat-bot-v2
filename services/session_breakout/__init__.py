"""Session Breakout live emitter — semi-manual breakout стратегии.

Backtest: docs/STRATEGIES/SESSION_BREAKOUT_BACKTEST.md
  - 2y BTC 1m, 1833 trades, PF 1.85, WR 56%, 4/4 folds positive
  - Best params: all transitions, entry_window=15min, buffer=0%, hold=2-3h
  - Per-transition: ny_pm→asia PF 2.57, ny_am→ny_lunch PF 1.86

Live flow по образцу range_hunter:
  signal_loop (60s):
    - в первые 15 минут НОВОЙ сессии (asia/london/ny_am/ny_lunch/ny_pm)
    - если recent 1m high break PRIOR session high → LONG signal
    - если recent 1m low  break PRIOR session low  → SHORT signal
    - 1 signal на boundary (dedup через journal)
  outcome_loop (60s):
    - оценивает placed signals: TP / SL / timeout

Self-contained: session OHLC считается из live df_1m (НЕ зависит от ict_levels
parquet который stale 70h+).
"""
