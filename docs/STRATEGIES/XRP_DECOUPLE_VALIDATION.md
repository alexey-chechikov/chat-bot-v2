# XRP decoupling-continuation — robustness validation

Signal: 1h, beta cw=30, cum residual K=12, hold M=6, event = |cum_resid| top/bottom 10% AND rolling corr<0.5, CONT = follow divergence sign. pair=beta-neutral (0.30% fee), dir=XRP-only (0.15% fee).

Window: 2024-05-16 19:00:00+00:00 → 2026-05-29 08:00:00+00:00

| segment | variant | n | WR% | mean% | PF | t | sum% |
|---|---|---:|---:|---:|---:|---:|---:|
| FULL | pair | 935 | 43.6 | +0.288 | 1.28 | 2.5 | +268.9 |
| FULL | dir | 935 | 46.5 | +0.354 | 1.33 | 2.83 | +331.0 |
| 1st half (OOS-A) | pair | 800 | 45.8 | +0.387 | 1.37 | 2.95 | +309.5 |
| 1st half (OOS-A) | dir | 800 | 49.0 | +0.467 | 1.43 | 3.29 | +373.9 |
| 2nd half (OOS-B) | pair | 135 | 31.1 | -0.300 | 0.66 | -1.73 | -40.5 |
| 2nd half (OOS-B) | dir | 135 | 31.9 | -0.318 | 0.67 | -1.65 | -43.0 |
| last ~120d | pair | 8 | 0.0 | -2.117 | 0.0 | -5.0 | -16.9 |
| last ~120d | dir | 8 | 0.0 | -2.183 | 0.0 | -4.58 | -17.5 |

## Verdict guide

Robust if BOTH halves show positive mean with t>~1.5 and the recent 120d hasn't gone negative. If the edge lives in only one half or has died recently, it's a regime artifact — do NOT build a live signal; at most paper-track. If the `dir` (XRP-only) variant also holds, the edge is executable without a short-BTC leg.
