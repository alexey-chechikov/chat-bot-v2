# Pre-Cascade Signal Audit — 2026-05-17

Validates whether existing pre-cascade detectors actually predict cascade fires.

**Method:** for each pre-cascade fire at time T with direction D, check if a
real cascade in direction D fired within [T, T+30min]. Computes precision,
recall, F1 vs random baseline (cascade frequency in same period).

**Data window:** 2026-05-13 → 2026-05-17 (~4 days)

**Audit script:** `scripts/pre_cascade_audit.py`

## Results

| Detector | Fires | TP | FP | Precision | Recall | F1 | Baseline | Edge |
|---|---|---|---|---|---|---|---|---|
| `OI+funding+LS` (full pre_cascade_alert) | 9 | 0 | 9 | **0%** | 0% | 0 | 12.8% | **−12.8 п.п. ❌** |
| `liq_clustering` (liq_pre_cascade) | 73 | 32 | 41 | **43.8%** | 65.3% | 0.524 | 20.7% | **+23.2 п.п. ✅** |
| Both combined | 82 | 32 | 50 | 39.0% | 65.3% | 0.488 | 11.7% | +27.4 п.п. |

## Выводы

### `liq_clustering` — настоящий рабочий pre-cascade сигнал ✅

- **Precision 43.8%**: из 73 fires 32 действительно сопровождались match-direction
  каскадом в течение 30 минут.
- **Recall 65.3%**: предсказывает 2 из 3 реальных каскадов с lead-time до 30 мин.
- **Edge over baseline +23 п.п.**: значительно выше шумовых ожиданий.
- Это даёт возможность **предупредительной паузы** ботов вместо реактивной.

### `OI+funding+LS` — НЕ работает в текущей форме ❌

- 9 fires за 4 дня, 0 hits.
- Все 3 условия совпадают редко, и когда совпадают — не предсказывают каскад.
- Это **anti-edge** в текущей конфигурации (либо тонкая выборка n=9).
- Кандидат на отключение или re-tune порогов (oi/funding/LS thresholds).

## Применено в bot_brain

**Phase 2 rules.py** — добавлены 2 новых правила:

```python
R1.5_pre_cascade_short_pause:
  trigger: liq-cluster SHORT-side fire (age ≤ 30 min)
  action:  pause SHORT bots (T1/T2/T3/TB)
  confidence: 0.55 (44% precision = 56% pause-без-нужды)

R2.5_pre_cascade_long_pause:
  trigger: liq-cluster LONG-side fire
  action:  pause LONG bots (LONG-D, LONG-V5)
  confidence: 0.55
```

Снапшот `state/bot_brain_state.jsonl` теперь содержит:
- `market.BTCUSDT.liq_cluster_fires_recent` — список fires за последние 30 мин

R1.5/R2.5 запускаются параллельно с reactive R1/R2 (`short_bots_guard` тоже
работает после факта). Это даёт **двойную защиту**: pre-emptive если liq-cluster
fire, reactive если каскад вышел внезапно без cluster-signal.

## Следующие шаги

1. **24-48ч наблюдения** — собирать `bot_brain_proposals.jsonl` с R1.5/R2.5
   fires. Проверить, как часто pre-pause экономит drawdown.
2. **Re-tune OI+funding+LS** или disable — либо найти porog combinations что
   реально работают (на новой 30-дневной выборке), либо отключить.
3. **Phase 3.3 — feature search**: для `liq_clustering` можем поднять precision
   с 44% до 55-60% добавив co-trigger (например: liq-cluster + OI rising fast
   + funding extreme в одну сторону). Backtest combinations.
4. **Lead-time analysis**: 30-min window — но может precision вышe при 15-min?
   Trade-off: shorter window → меньше recall но больше precision.

---

## Window-size sensitivity study (added 2026-05-17)

`liq_clustering` precision/recall trade-off across forward window:

| Window | n fires | TP | FP | Precision | Recall | F1 | Baseline | Edge vs baseline |
|---|---|---|---|---|---|---|---|---|
| 15 min | 75 | 25 | 50 | 33.3% | 43.2% | 0.376 | 10.0% | **+23.3 п.п.** |
| **30 min** | 73 | 32 | 41 | **43.8%** | **65.3%** | **0.524** | **20.7%** | **+23.2 п.п.** |
| 60 min | 75 | 39 | 36 | 52.0% | 74.3% | 0.612 | 40.0% | +12.0 п.п. |

**Interpretation**:
- 15-min слишком узкое окно — каскад не успевает реализоваться после liq-cluster
- 60-min даёт **высочайший raw precision** (52%), но edge_over_baseline падает
  с +23 → +12 п.п. потому что baseline (% времени когда random window содержит
  cascade) тоже растёт с 21% до 40%
- **30-min — sweet-spot**: precision/recall/edge все максимальны или близки к max

**Decision**: R1.5/R2.5/R1.6/R2.6 продолжают использовать 30-min lookback окно.
Без serial-correlation теста сейчас (нужны более длинные данные) — это правило
"don't fix what works"

**Future**: после 7-14 дней дополнительных данных пересчитать на расширенной
выборке. Если precision @60min продолжит > @30min — добавим R1.5-LATE с 60-min
window для пост-каскадного "поздняка".
