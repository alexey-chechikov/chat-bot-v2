# CVD Divergence × liq_cluster — Phase 3.4 Research

**Цель:** проверить может ли CVD (Cumulative Volume Delta) divergence
повысить precision liq_cluster signal'а как co-trigger.

**Script:** `scripts/cvd_pre_cascade_research.py`

## Method

CVD construction (approximate):
- per 1m bar в `market_live/market_1m.csv` (BTC volume)
- nearest deriv_live snapshot taker_buy_pct → imbalance = (taker_buy_pct - 50) × 2 / 100
- CVD(t) = cumulative sum of (imbalance × bar_volume)

Divergence detection (60-min lookback before fire):
- **bearish_div**: price max came AFTER cvd max (price kept rising but CVD already topped)
- **bullish_div**: price min came AFTER cvd min (price kept falling but CVD already bottomed)

## Результаты — counter-intuitive

| Trigger | n | Same-dir div precision | OPPOSITE div precision |
|---|---|---|---|
| short cluster (expects price↑) | 39 | bearish_div: **30%** (n=10) | bullish_div: **56%** (n=16) ✅ |
| long cluster (expects price↓) | 36 | bullish_div: **38.5%** (n=13) | bearish_div: **54.5%** (n=11) ✅ |

Baseline без фильтра: 42.7%.

## Интерпретация

CVD divergence в **обратном** ожидаемом направлении — это сигнал что
**absorption** случился ДО фейка цены:

- liq_cluster short + bullish_CVD_div = "shorts ликвиднулись после того как
  buyers абсорбировали мини-крах" — squeeze setup сильнее
- liq_cluster short + bearish_CVD_div = "CVD уже на топе пока цена ещё растёт"
  — momentum exhausted, продолжение менее вероятно

Это **inverse signal** — CVD divergence НЕ confirms direction-of-fire, а
**flags absorption** который преcedates squeeze.

## Lift quantification

CVD opposite-div: +12 пп vs baseline 43%
Taker-buy filter (R1.6): +23 пп  
**Taker filter сильнее**. CVD-divergence добавляет marginal info.

## Decision

**НЕ добавляю отдельное R1.7-CVD правило** в bot_brain — taker filter уже
ловит большую часть сигнала, CVD дублирует с lower lift.

**Future hypothesis:** combo R1.8 — liq_cluster + taker_filter + CVD_opposite_div
может дать precision 75-85% но n будет маленький. Wait for 30+ дней дополнительных
данных, потом повторить combined feature search.

## Caveats

- CVD approximated from 5-min deriv_taker_buy_pct + 1m volume — не настоящий
  per-trade CVD (тот требует L3 order book / trade tape).
- 60-min lookback divergence — простая argmax-сравнение, не proper
  trendline-divergence (Pine `ta.cum`/`ta.divergence`).
- TradingView Pro имеет **real CVD indicator** на основе trade tape с
  millisecond precision. Если интегрировать TV-data via webhook, точность
  может вырасти существенно (см. `docs/RESEARCH_tradingview_pro_integration_2026-05-17.md`).
