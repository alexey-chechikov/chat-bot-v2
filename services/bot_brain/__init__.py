"""Bot Brain — adaptive engine for managed GinArea bots + manual-trade decision support.

Three layers:
  - Phase 1 (state.py): perception — snapshot market + bot state every minute
  - Phase 2 (actions.py, rules.py): action vocabulary + decision rules (TODO)
  - Phase 3 (research): backtests feeding rule calibration (TODO)

Risk tier:
  - Production bots (5 managed, see state/short_bots_managed.json): only safe actions
    in auto mode (pause/resume already in short_bots_guard, auto-recenter planned)
  - Testbed bot (tier="TB", testbed=true): aggressive actions (resize, close_flat,
    fix_partial, tighten/widen grid) run in auto mode here only

All output flows through state/bot_brain_state.jsonl — single perception stream
consumed by rules, manual decision support, and backtest research.
"""
