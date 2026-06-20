# Range Hunter shadow-validation

Auto-filled every recorded RH signal against 1m price (the operator acted on ~1/78). Tests the strategy's assumed **68.5% pair-win** empirically. pair_win = both straddle legs touched within hold; single-leg fills can stop out at stop_loss_pct.

| symbol | signals | simd | pair_win% | stopped% | timeout% | no_fill% | net PnL$ | $/sig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 78 | 77 | 53.2 | 44.2 | 2.6 | 0.0 | +43.5 | +0.56 |
| ETHUSDT | 40 | 39 | 46.2 | 51.3 | 2.6 | 0.0 | -69.4 | -1.78 |
| XRPUSDT | 25 | 25 | 52.0 | 48.0 | 0.0 | 0.0 | -64.1 | -2.56 |

## Verdict

- **All symbols: n=141, empirical pair_win=51.1%** (strategy assumed 68.5%).
- Net PnL **-90.0$** over 141 sims, -0.64$/signal; win-share 51.8%; of 141 that filled ≥1 leg, net -90.0$.
- **NO/WEAK EDGE — do not promote; investigate level quality.**
