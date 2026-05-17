# Cross-Asset OI Delta — leading indicator research (Phase 3.5)

**Цель:** проверить может ли OI delta на ETH/XRP предсказать BTC форвард-движение.

**Script:** `scripts/cross_asset_oi_leading_research.py`
**Data:** 2,748 joined snapshots (~10 дней, 3-5 мин cadence) deriv_live_history × market_1m.csv

## Результаты по correlations (Pearson)

| Feature | vs 5m | vs 15m | vs 30m |
|---|---|---|---|
| btc_oi_1h | +0.020 | +0.041 | +0.055 |
| eth_oi_1h | -0.008 | -0.013 | -0.025 |
| xrp_oi_1h | -0.014 | -0.025 | -0.032 |
| alt_oi_avg | -0.018 | -0.031 | -0.048 |

Все |corr| < 0.10 — **классически шум**. Alt OI **сам по себе не предсказывает** BTC форвард-движение.

## Bucket analysis (Q1-Q5 by signal)

BTC own OI (Q5 highest vs Q1 lowest):
- Q5 up_30m = 51.5% / Q1 up_30m = 54.8%
- U-shaped pattern (экстремальные движения OI = больше vol), не monotonic predictive

XRP OI 1h:
- Q1 (XRP OI dumps): BTC up_30m = 55.9%
- Q4 (XRP OI rises): BTC up_30m = 45.8%
- Reverse direction pattern, но эффект слабый и not statistically robust

## 🎯 KEY FINDING — Triple-OI Confluence

| Bucket | n | mean_30m BTC | up_30m % |
|---|---|---|---|
| ALL UP (BTC + ETH + XRP each > +0.3%) | 51 | **+0.047%** | **62.7%** ✅ |
| ALL DOWN (each < -0.3%) | 66 | +0.030% | 45.5% (asymmetric) |
| Baseline (all 2748) | 2748 | -0.008% | 50.4% |

**+12 пп lift** when all three OIs rise simultaneously (n=51). ALL-DOWN не даёт symmetric эффект — суждение: ALL-UP — bullish positioning signal, ALL-DOWN — random.

## Гипотеза для actionable rule (НЕ деплою пока)

**R7_triple_oi_up_confluence**: когда все три OI (BTC/ETH/XRP 1h) одновременно > +0.3% — pause SHORT bots pre-emptively / boost LONG conviction. Confidence ~0.65 (62.7% precision на n=51).

**Почему не добавляю в bot_brain прямо сейчас:**
- n=51 — small. Нужен >=150 для статзначимости.
- 30-min горизонт коротковат для grid-bot pause cycles (наш минимум 4h hold)
- Может conflict с уже работающим R1.5/R1.6 (которые уже paused SHORTs)
- Ждать накопления данных deriv_live_history до 30+ дней, перетестировать

## Что в очередь записал

1. После 30 дней live history — запустить script снова, проверить устойчивость +12 пп lift
2. Если устойчиво → добавить R7 confluence rule в bot_brain
3. Также проверить ALL-DOWN: может для LONG bots это actionable (long_30m down rate?)

## Caveats

- Sample 10 days в TREND_DOWN/low-vol режиме — может не работать в TREND_UP
- OI delta sampled at 5min granularity — noisy. Real signal может быть на 15-min smoothed OI
- Не проверял interaction с funding / taker — confluence with those может lift'ить precision дальше

## Применение

Сейчас **не добавляется в bot_brain rules** (sample too small + horizon mismatch). Документ для followup через ~3 недели когда накопится 30+ дней OI history.
