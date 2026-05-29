# Alt↔BTC decorrelation edge research

2y 1m → resampled. spread_K = altΔ% − btcΔ% over K bars. Event = |spread_K| in top/bottom tercile. Forward = ALT raw return over M bars, fees 0.15% RT. **t** = t-stat of mean net return (|t|>2 ≈ significant). CONT = trade with divergence; REV = against.

## ETHUSDT

| TF | K/M | event | n | CONT WR% | CONT mean% | CONT PF | CONT t | REV mean% | REV t | corr@event |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 25min | 6/4 | alt≫btc (up div) | 14579 | 39.5 | -0.137 | 0.65 | -17.49 | -0.164 | -20.96 | 0.8 |
| 25min | 6/4 | alt≪btc (dn div) | 14579 | 39.4 | -0.148 | 0.65 | -17.02 | -0.152 | -17.56 | 0.81 |
| 25min | 12/8 | alt≫btc (up div) | 14576 | 41.5 | -0.118 | 0.77 | -10.96 | -0.182 | -16.82 | 0.8 |
| 25min | 12/8 | alt≪btc (dn div) | 14576 | 41.7 | -0.125 | 0.78 | -10.0 | -0.175 | -13.96 | 0.82 |
| 1h | 6/4 | alt≫btc (up div) | 6073 | 42.9 | -0.118 | 0.78 | -6.46 | -0.181 | -9.89 | 0.8 |
| 1h | 6/4 | alt≪btc (dn div) | 6073 | 42.0 | -0.125 | 0.79 | -5.95 | -0.175 | -8.35 | 0.82 |
| 1h | 12/6 | alt≫btc (up div) | 6070 | 43.6 | -0.137 | 0.8 | -5.9 | -0.163 | -7.01 | 0.8 |
| 1h | 12/6 | alt≪btc (dn div) | 6070 | 42.3 | -0.138 | 0.81 | -5.42 | -0.162 | -6.34 | 0.83 |

## XRPUSDT

| TF | K/M | event | n | CONT WR% | CONT mean% | CONT PF | CONT t | REV mean% | REV t | corr@event |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 25min | 6/4 | alt≫btc (up div) | 14579 | 40.0 | -0.117 | 0.75 | -10.66 | -0.183 | -16.77 | 0.67 |
| 25min | 6/4 | alt≪btc (dn div) | 14579 | 39.0 | -0.180 | 0.63 | -16.4 | -0.120 | -10.89 | 0.69 |
| 25min | 12/8 | alt≫btc (up div) | 14576 | 43.0 | -0.093 | 0.85 | -6.25 | -0.206 | -13.82 | 0.66 |
| 25min | 12/8 | alt≪btc (dn div) | 14576 | 41.5 | -0.208 | 0.68 | -14.26 | -0.092 | -6.26 | 0.7 |
| 1h | 6/4 | alt≫btc (up div) | 6073 | 43.7 | -0.101 | 0.85 | -4.07 | -0.199 | -8.06 | 0.68 |
| 1h | 6/4 | alt≪btc (dn div) | 6073 | 42.7 | -0.206 | 0.7 | -8.48 | -0.094 | -3.84 | 0.7 |
| 1h | 12/6 | alt≫btc (up div) | 6070 | 44.1 | +0.001 | 1.0 | 0.04 | -0.301 | -9.16 | 0.67 |
| 1h | 12/6 | alt≪btc (dn div) | 6070 | 44.0 | -0.185 | 0.77 | -6.52 | -0.115 | -4.03 | 0.71 |

## How to read

- A real edge = CONT or REV mean% clearly >0 with **|t|>2** and PF>1.2 on large n. If both CONT and REV hover near 0 with |t|<2, decorrelation carries no directional edge at that horizon.
- Low corr@event confirms the signal fired in genuine decoupling.
- Next step depends on the verdict: if CONT wins → momentum-follow the diverging alt; if REV wins → fade the divergence (pairs/mean-revert to BTC).
