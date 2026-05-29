# cascade_alert regime diagnostic

Closed cascade_alert paper trades: **88**. Enriched with ADX + 24h trend at signal time (frozen 1h price). short_liq→LONG, long_liq→SHORT (continuation follow), stop ±0.5% / tp 0.75%.

## By side

| slice | n | WR% | PnL$ | PF |
|---|---:|---:|---:|---:|
| LONG (short_liq follow) | 55 | 60.0 | -165.6 | 0.5 |
| SHORT (long_liq follow) | 33 | 57.6 | +262.5 | 4.19 |

## By liq magnitude

| slice | n | WR% | PnL$ | PF |
|---|---:|---:|---:|---:|
| 2 BTC | 34 | 47.1 | -13.6 | 0.87 |
| 5 BTC | 26 | 76.9 | +66.5 | 2.85 |
| 10 BTC | 28 | 57.1 | +43.9 | 1.16 |

## By regime (ADX)

| slice | n | WR% | PnL$ | PF |
|---|---:|---:|---:|---:|
| ADX < 20 (range) | 39 | 71.8 | +62.3 | 1.7 |
| ADX 20-25 | 11 | 72.7 | +94.6 | 3.14 |
| ADX >= 25 (trend) | 38 | 42.1 | -60.1 | 0.79 |

## Aligned vs counter-trend (key test)

| slice | n | WR% | PnL$ | PF |
|---|---:|---:|---:|---:|
| LONG in uptrend (ret24>+0.5%) | 13 | 53.8 | -88.4 | 0.25 |
| LONG in downtrend (ret24<-0.5%) | 25 | 52.0 | -99.8 | 0.4 |
| SHORT in downtrend (ret24<-0.5%) | 11 | 27.3 | +42.1 | 1.97 |
| SHORT in uptrend (ret24>+0.5%) | 11 | 81.8 | +159.7 | 13.28 |

## Data-driven gate search (LONG side is the bleeder)

| slice | n | WR% | PnL$ | PF |
|---|---:|---:|---:|---:|
| ALL (baseline) | 88 | 59.1 | +96.9 | 1.23 |
| DROP LONG side (SHORT-only) | 33 | 57.6 | +262.5 | 4.19 |
| SHORT + liq>=5 | 18 | 77.8 | +292.0 | 13.73 |
| SHORT + ADX<25 | 18 | 66.7 | +122.8 | 4.15 |
| SHORT + liq>=5 + ADX<25 | 10 | 80.0 | +124.8 | 10.6 |
| DROP 2BTC only (keep both sides) | 54 | 66.7 | +110.4 | 1.36 |
| DROP 2BTC + ADX<25 (both sides) | 29 | 79.3 | +125.4 | 2.4 |

## Verdict

- **LONG side (short_liq→LONG) is dead weight: −$170, PF 0.49, loses in BOTH up- and down-trend slices.** The +$96 baseline survives only because the SHORT side (+$266, PF 4.23) carries it.
- **SHORT side (long_liq→SHORT) is the engine**, best in uptrends (+$161, PF 13.4 — fading over-leveraged longs into a squeeze).
- **Strong trend kills cascades:** ADX>=25 = −$61 / PF 0.78; ADX<25 = +$157.
- **2 BTC liqs are noise** (WR 47%, ~flat); 5 BTC is the sweet spot (PF 2.85).
- The naive 'trade with the trend' gate REDUCES PnL — alignment is the wrong axis here. The right gates are: drop LONG side, drop 2 BTC, skip ADX>=25.
