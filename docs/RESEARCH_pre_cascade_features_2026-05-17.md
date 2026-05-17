# Pre-Cascade Feature Search — 2026-05-17

Цель: повысить precision liq_cluster signal (baseline 44%) добавив co-trigger
фильтры на deriv-state в момент fire'а.

**Script:** `scripts/pre_cascade_feature_search.py`
**Метод:** для каждого fire'а из `state/liq_pre_cascade_fires.jsonl` подбирается
ближайший snapshot из `state/deriv_live_history.jsonl` (max gap 10 мин), вычисляются
9 features, applies threshold filter, считается precision на подвыборке.
**Label:** hit if same-direction cascade в `state/cascade_accuracy.jsonl` fired
within 30 min после liq-cluster.

## Результаты

**Baseline (без фильтра):**
- short-side cluster: n=39, **precision 43.6%**
- long-side cluster: n=36, **precision 41.7%**

### Short-side (predicts SHORT cascade = price↑)

| Filter | n | TP | Precision | Lift vs baseline |
|---|---|---|---|---|
| **`btc_taker_buy < 38`** | 5 | 4 | **80.0%** | **+36.4 п.п. 🟢** |
| **`btc_taker_buy < 42`** | 12 | 8 | **66.7%** | **+23.1 п.п. 🟢** |
| `btc_oi_1h_pct > 0.3` | 7 | 4 | 57.1% | +13.5 п.п. |
| `btc_taker_buy < 45` | 17 | 9 | 52.9% | +9.3 п.п. |
| `btc_oi_1h_pct > 0.5` | 6 | 3 | 50.0% | +6.4 п.п. |
| `btc_premium < 0` | 39 | 17 | 43.6% | +0 (нейтрально) |
| `btc_funding > 3e-5` | 11 | 3 | 27.3% | −16.3 п.п. ❌ |

**Интерпретация**: short-side кластер ликвидации + BTC taker_buy heavily sell
(below 42%) = настоящий продавливающий сетап. Высокий positive funding (longs
платят) парадоксально снижает precision (возможно overcrowded longs already
flushed — каскад слабее).

### Long-side (predicts LONG cascade = price↓ в 2026-inverted edge)

| Filter | n | TP | Precision | Lift |
|---|---|---|---|---|
| **`btc_funding < -3e-5`** | 5 | 3 | **60.0%** | **+18.3 п.п. 🟢** (small n) |
| `btc_taker_buy > 58` | 9 | 4 | 44.4% | +2.7 п.п. |
| `btc_oi_1h_pct < -0.5` | 5 | 2 | 40.0% | −1.7 п.п. |
| `btc_ls < 0.7` | 10 | 4 | 40.0% | −1.7 п.п. |
| `btc_oi_1h_pct < -0.3` | 9 | 2 | 22.2% | −19.5 п.п. ❌ |

**Интерпретация**: long-side кластер + negative funding (shorts платят longs)
указывает на crowded long-side несмотря на short-bias capital flow — реверсал
вниз более вероятен. Малая выборка (n=5), требует подтверждения.

## Применено в bot_brain

Добавлены 2 HIGH-confidence rules в `services/bot_brain/rules.py`:

### R1.6_pre_cascade_short_HIGH
```python
trigger: liq-cluster short-side + btc_taker_buy < 42
action:  pause SHORT bots (T1/T2/T3/TB)
confidence: 0.70  (или 0.80 если taker < 38)
expected precision: 67-80%
```

### R2.6_pre_cascade_long_HIGH
```python
trigger: liq-cluster long-side + btc_funding < -0.003%/8h
action:  pause LONG bots (LONG-D, LONG-V5)
confidence: 0.60
expected precision: 60% (на n=5 — нужна валидация)
```

R1.5/R2.5 (baseline) **сохранены** — fire'ят на ВСЕХ liq-cluster events
независимо от co-trigger. R1.6/R2.6 fire'ят ДОПОЛНИТЕЛЬНО когда условия совпадают.

В `bot_brain_proposals.jsonl` это видно как раздельные rule_id записи → audit
после 24-48ч покажет: 
- сколько R1.6/R2.6 фактически предотвратили loss
- какова реальная precision в live режиме (vs paper 67%)

## Что в очереди

1. **Audit per-rule effectiveness** — для каждой pause проверить движение цены
   за 30-60 мин (script: R1.5/R2.5/R1.6/R2.6 audit)
2. **Sample size growth** — R1.6 short-strict (taker<38) имеет всего n=5; ждём
   ещё 7-14 дней live data до твёрдых выводов
3. **Time-window study** — попробовать 15-min window vs 30-min: тоньше окно =
   меньше recall но возможно ещё выше precision
