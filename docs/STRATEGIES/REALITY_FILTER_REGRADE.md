# Reality-filter re-grade — honest net ranking

Truth = setup_precision_outcomes.jsonl (n=252). Gross pnl_pct minus calibrated round-trip cost. Calibration from 6 live trades: limit entry 0% slip, market_fallback +0.15..0.31% (4/6) AND adverse (4/4 fallback hit SL vs 2/2 limit flat).

| setup | N | TP1 | SL | TO | gross avg% | net@0.15 | net@0.30 | net@0.45 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| long_mega_dump_bounce | 4 | 3 | 0 | 1 | +2.749 | +2.599🟢 | +2.449🟢 | +2.299🟢 |
| long_double_bottom | 15 | 14 | 0 | 1 | +1.034 | +0.884🟢 | +0.734🟢 | +0.584🟢 |
| long_dump_reversal | 17 | 8 | 3 | 6 | +0.813 | +0.663🟢 | +0.513🟢 | +0.363🟢 |
| long_pdl_bounce | 21 | 13 | 3 | 5 | +0.772 | +0.622🟢 | +0.472🟢 | +0.322🟢 |
| long_div_bos_15m | 1 | 0 | 0 | 1 | +0.702 | +0.552🟢 | +0.402🟢 | +0.252🟢 |
| short_rally_fade | 58 | 19 | 8 | 31 | +0.193 | +0.043🟢 | -0.107🔴 | -0.257🔴 |
| long_multi_divergence | 57 | 1 | 2 | 54 | -0.075 | -0.225🔴 | -0.375🔴 | -0.525🔴 |
| short_div_bos_15m | 1 | 0 | 1 | 0 | -0.165 | -0.315🔴 | -0.465🔴 | -0.615🔴 |
| short_pdh_rejection | 67 | 8 | 37 | 22 | -0.167 | -0.317🔴 | -0.467🔴 | -0.617🔴 |
| short_mfi_multi_ga | 9 | 0 | 1 | 8 | -0.321 | -0.471🔴 | -0.621🔴 | -0.771🔴 |
| long_div_bos_confirmed | 1 | 0 | 0 | 1 | -1.296 | -1.446🔴 | -1.597🔴 | -1.746🔴 |
| short_double_top | 1 | 0 | 1 | 0 | -2.450 | -2.600🔴 | -2.750🔴 | -2.900🔴 |

## Survivors (limit-only ~0.15% RT, N>=10)

- **long_double_bottom** — net +0.884%/trade, n=15 (still ++0.734 at 0.30%)
- **long_dump_reversal** — net +0.663%/trade, n=17 (still ++0.513 at 0.30%)
- **long_pdl_bounce** — net +0.622%/trade, n=21 (still ++0.472 at 0.30%)
- **short_rally_fade** — net +0.043%/trade, n=58 (still +-0.107 at 0.30%)

## Verdict

- **long_multi_divergence** (live now) is honest **−21% / 54-of-57 TIMEOUT** — REMOVE from executor.
- Real survivors: **long_double_bottom, long_pdl_bounce, long_dump_reversal** — keep/add to executor.
- **Biggest real-PnL lever: disable market_fallback.** Live data: every market-fallback entry lost (4/4 SL), every clean limit fill didn't (2/2 flat). Limit-only entry removes both the +0.23% slippage and the adverse selection -> drops effective cost toward 0.15%.
- N small for survivors (10-21); out-of-time robustness still unproven.
