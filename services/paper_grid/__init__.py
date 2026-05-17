"""Paper grid bot — live volume-farm grid simulator for ETH/XRP.

Per-symbol async loop runs grid market-maker simulation on LIVE 1m bars.
No real orders placed. Outputs daily PnL to state/paper_grid_<symbol>.jsonl
for empirical comparison vs sweet-spot sweep (docs/RESEARCH_grid_sweet_spot_2026-05-17.md).

Goal: validate that the +$2-5K/day backtest claim holds on actual live data,
without committing real capital. After 7-14 days of paper PnL we have grounded
expectation for live deployment.

Per-symbol state persisted in state/paper_grid_<symbol>_state.json.
"""
from .runner import paper_grid_loop  # noqa: F401
