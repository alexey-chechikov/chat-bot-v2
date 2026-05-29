# Edge hunt — out-of-sample (3 families)

Fees 0.15% RT. Edge = positive mean with |t|>2 in BOTH y1 & y2 and not dead in last120d. **t**=t-stat of mean net return.

## A) Session / hour-of-day (BTC 1h, forward 4h, LONG bias)

Per UTC entry-hour: go LONG, hold 4h. Looking for hours with a persistent directional bias across both halves.

| hour | seg | n | WR% | mean% | PF | t |
|---|---|---:|---:|---:|---:|---:|
| 03h UTC | FULL | 745 | 37.4 | -0.172 | 0.5 | -6.45 |
| 03h UTC | y1 | 372 | 39.5 | -0.157 | 0.56 | -3.92 |
| 03h UTC | y2 | 373 | 35.4 | -0.187 | 0.44 | -5.31 |
| 03h UTC | last120d | 121 | 39.7 | -0.199 | 0.47 | -2.75 |
| 02h UTC | FULL | 745 | 37.9 | -0.168 | 0.52 | -5.88 |
| 02h UTC | y1 | 372 | 39.2 | -0.165 | 0.54 | -3.72 |
| 02h UTC | y2 | 373 | 36.5 | -0.172 | 0.48 | -4.72 |
| 02h UTC | last120d | 121 | 38.0 | -0.238 | 0.41 | -3.21 |
| 09h UTC | FULL | 745 | 36.9 | -0.174 | 0.56 | -5.65 |
| 09h UTC | y1 | 372 | 39.8 | -0.166 | 0.6 | -3.67 |
| 09h UTC | y2 | 373 | 34.0 | -0.182 | 0.52 | -4.35 |
| 09h UTC | last120d | 121 | 33.1 | -0.262 | 0.53 | -2.58 |
| 04h UTC | FULL | 745 | 39.3 | -0.152 | 0.56 | -5.4 |
| 04h UTC | y1 | 372 | 40.3 | -0.135 | 0.6 | -3.31 |
| 04h UTC | y2 | 373 | 38.3 | -0.169 | 0.51 | -4.36 |
| 04h UTC | last120d | 121 | 41.3 | -0.164 | 0.56 | -2.03 |

## B) Lead-lag — does the alt lead BTC? (1h)

At each bar, if the ALT had a big move over last 3h (top/bottom decile), trade BTC in the SAME direction for next M=3h. Edge => alt leads BTC.

| pair | seg | n | WR% | mean% | PF | t |
|---|---|---:|---:|---:|---:|---:|
| XRP→BTC | FULL | 3574 | 39.1 | -0.134 | 0.7 | -7.31 |
| XRP→BTC | y1 | 1787 | 40.2 | -0.156 | 0.69 | -5.35 |
| XRP→BTC | y2 | 1787 | 37.9 | -0.113 | 0.71 | -5.04 |
| XRP→BTC | last120d | 430 | 44.2 | +0.036 | 1.09 | 0.66 |
| ETH→BTC | FULL | 3574 | 38.9 | -0.148 | 0.67 | -8.27 |
| ETH→BTC | y1 | 1787 | 40.3 | -0.140 | 0.71 | -4.93 |
| ETH→BTC | y2 | 1787 | 37.5 | -0.155 | 0.62 | -7.17 |
| ETH→BTC | last120d | 542 | 42.1 | -0.083 | 0.8 | -1.77 |

## C) Funding-rate extremes → forward BTC (fade & follow)

Funding extremes (top/bottom decile), forward 24h. FADE = trade against the crowded side; FOLLOW = with it.

| variant | seg | n | WR% | mean% | PF | t |
|---|---|---:|---:|---:|---:|---:|
| FADE | FULL | 846 | 46.2 | -0.105 | 0.87 | -1.41 |
| FADE | y1 | 423 | 45.2 | -0.201 | 0.8 | -1.69 |
| FADE | y2 | 423 | 47.3 | -0.009 | 0.99 | -0.1 |
| FADE | last120d | 238 | 49.2 | -0.020 | 0.97 | -0.18 |
| FOLLOW | FULL | 846 | 45.2 | -0.195 | 0.78 | -2.63 |
| FOLLOW | y1 | 423 | 47.0 | -0.099 | 0.9 | -0.83 |
| FOLLOW | y2 | 423 | 43.3 | -0.291 | 0.64 | -3.29 |
| FOLLOW | last120d | 238 | 43.7 | -0.280 | 0.65 | -2.51 |

## Verdict

Scan the y1 AND y2 rows of each block. A keeper has the SAME sign, mean>0, |t|>2 in both halves, and last120d not negative. Anything positive only in FULL or one half is a regime artifact — do not build.
