# cascade_alert SHORT — parameter optimization

Re-simulated **39** recorded SHORT signals from real entry/ts against 1m BTC. Current live: tp 0.75 / stop 0.5 / hold 4h. Fees 0.15% RT, size $1000 (usd = %·10).

**Baseline (live params, all SHORT):** n=39 WR=53.8% EV=-0.001% PF=1.0 PnL=-0.3$

## Top (tp/stop/hold) configs — all SHORT, ranked by PF·EV

| tp | stop | hold | n | WR% | EV% | PF | PnL$ |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | 0.4 | 8 | 39 | 53.8 | +0.157 | 1.62 | +61.4 |
| 1.5 | 0.4 | 6 | 39 | 53.8 | +0.129 | 1.51 | +50.2 |
| 1.0 | 0.4 | 6 | 39 | 53.8 | +0.126 | 1.5 | +49.1 |
| 1.25 | 0.4 | 6 | 39 | 53.8 | +0.125 | 1.49 | +48.7 |
| 1.0 | 0.5 | 8 | 39 | 53.8 | +0.111 | 1.37 | +43.4 |
| 1.5 | 0.4 | 8 | 39 | 51.3 | +0.106 | 1.4 | +41.5 |
| 1.25 | 0.4 | 8 | 39 | 51.3 | +0.102 | 1.39 | +39.9 |
| 1.5 | 0.5 | 6 | 39 | 53.8 | +0.083 | 1.27 | +32.2 |
| 1.0 | 0.5 | 6 | 39 | 53.8 | +0.080 | 1.27 | +31.1 |
| 1.25 | 0.5 | 6 | 39 | 53.8 | +0.079 | 1.26 | +30.7 |

## Filter effect @ best region (tp 1.0/stop 0.4/hold 8)

| filter | n | WR% | EV% | PF | PnL$ |
|---|---:|---:|---:|---:|---:|
| all SHORT | 39 | 53.8 | +0.157 | 1.62 | +61.4 |
| liq>=5 | 24 | 66.7 | +0.350 | 2.91 | +83.9 |
| liq>=10 | 7 | 71.4 | +0.450 | 3.86 | +31.5 |
| ADX<25 | 20 | 70.0 | +0.372 | 3.25 | +74.4 |
| liq>=5 & ADX<25 | 12 | 83.3 | +0.549 | 6.99 | +65.9 |

## Verdict

Baseline live EV -0.001%/trade (-0.3$). Best stable grid cell: tp 1.0/stop 0.4/hold 8 (EV +0.157%, PF 1.62, n=39). Apply the liq>=5 gate (drops 2 BTC noise) regardless. n is small — treat param change as provisional, confirm on accumulating live SHORT.
