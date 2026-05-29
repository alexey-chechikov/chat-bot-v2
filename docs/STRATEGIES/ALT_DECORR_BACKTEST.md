# Alt decorrelation-divergence — backtest (live detector logic)

Divergence engine run ON the alt; bull→LONG, bear→SHORT; stop 1.0% tp 2.0% fees 0.15% RT. Gate = alt↔BTC 30-bar corr < 0.7. Shows WITH vs WITHOUT the decorrelation gate, plus OOS halves.

| alt | TF | gate | seg | n | WR% | mean% | PF | t | sum% |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | 25min | no-gate | FULL | 651 | 37.6 | -0.190 | 0.69 | -4.26 | -123.5 |
| ETHUSDT | 25min | no-gate | y1 | 325 | 38.8 | -0.134 | 0.78 | -2.07 | -43.6 |
| ETHUSDT | 25min | no-gate | y2 | 326 | 36.5 | -0.245 | 0.61 | -4.01 | -79.9 |
| ETHUSDT | 25min | corr<0.7 | FULL | 87 | 31.0 | -0.356 | 0.45 | -3.31 | -31.0 |
| ETHUSDT | 25min | corr<0.7 | y1 | 43 | 37.2 | -0.200 | 0.66 | -1.21 | -8.6 |
| ETHUSDT | 25min | corr<0.7 | y2 | 44 | 25.0 | -0.509 | 0.29 | -3.72 | -22.4 |
| ETHUSDT | 1h | no-gate | FULL | 239 | 40.6 | -0.124 | 0.78 | -1.67 | -29.6 |
| ETHUSDT | 1h | no-gate | y1 | 119 | 45.4 | -0.034 | 0.94 | -0.31 | -4.0 |
| ETHUSDT | 1h | no-gate | y2 | 120 | 35.8 | -0.213 | 0.64 | -2.13 | -25.6 |
| ETHUSDT | 1h | corr<0.7 | FULL | 33 | 36.4 | -0.204 | 0.68 | -0.98 | -6.7 |
| ETHUSDT | 1h | corr<0.7 | y1 | 16 | 50.0 | -0.048 | 0.91 | -0.15 | -0.8 |
| ETHUSDT | 1h | corr<0.7 | y2 | 17 | 23.5 | -0.350 | 0.5 | -1.27 | -6.0 |
|  |  |  |  |  |  |  |  |  |  |
| XRPUSDT | 25min | no-gate | FULL | 639 | 36.5 | -0.183 | 0.71 | -3.9 | -117.2 |
| XRPUSDT | 25min | no-gate | y1 | 319 | 36.1 | -0.236 | 0.65 | -3.56 | -75.2 |
| XRPUSDT | 25min | no-gate | y2 | 320 | 36.9 | -0.131 | 0.78 | -1.96 | -42.0 |
| XRPUSDT | 25min | corr<0.7 | FULL | 238 | 39.9 | -0.123 | 0.8 | -1.55 | -29.4 |
| XRPUSDT | 25min | corr<0.7 | y1 | 119 | 37.0 | -0.234 | 0.65 | -2.16 | -27.8 |
| XRPUSDT | 25min | corr<0.7 | y2 | 119 | 42.9 | -0.013 | 0.98 | -0.12 | -1.6 |
| XRPUSDT | 1h | no-gate | FULL | 265 | 42.6 | -0.064 | 0.89 | -0.84 | -16.9 |
| XRPUSDT | 1h | no-gate | y1 | 132 | 40.2 | -0.087 | 0.86 | -0.79 | -11.6 |
| XRPUSDT | 1h | no-gate | y2 | 133 | 45.1 | -0.040 | 0.93 | -0.39 | -5.4 |
| XRPUSDT | 1h | corr<0.7 | FULL | 112 | 42.9 | -0.034 | 0.94 | -0.28 | -3.8 |
| XRPUSDT | 1h | corr<0.7 | y1 | 56 | 39.3 | -0.082 | 0.86 | -0.48 | -4.6 |
| XRPUSDT | 1h | corr<0.7 | y2 | 56 | 46.4 | +0.015 | 1.03 | 0.09 | +0.8 |
|  |  |  |  |  |  |  |  |  |  |

Edge = the `corr<gate` rows beating the `no-gate` rows AND positive in both y1 & y2. If the gate doesn't lift the divergence edge, decorrelation adds nothing and we run plain alt-divergence instead.