# PUMP FILTER — Feature Contract (Phase 4 ML-resume-гейт)

**Статус:** зафиксировано 2026-05-22. Win-Claude.
**Назначение:** определить, на каких фичах коллеге обучать GBM-модель
resume-гейта, чтобы train-набор сошёлся с live-данными колонка-в-колонку.

Связь: `docs/STRATEGIES/PUMP_DUMP_FILTER_V2.md`, каталог
`state/pump_event_catalog.csv`, модуль `services/pump_freeze/resume_model.py`.

---

## Главное ограничение (проверено по данным)

GBM 0.84 (CV) / 0.84 (OOT) опирался на `taker_t15` и `oi_delta_win` —
топ-importance фичи. Но:

- **`deriv_live.json`** отдаёт OI/taker **снапшотом раз в N минут**, не
  поминутным рядом → `oi_delta_win` (дельта за 30-мин окно) в live
  посчитать нельзя.
- **Binance LS-ratio** (`globalLongShortAccountRatio`,
  `topLongShortAccountRatio`) — история только ~1 месяц.
  `data/historical/binance_combined_BTCUSDT.parquet`: покрытие этих
  колонок **20%** за 2 года (с 2026-04-19). Для обучения на 542 событиях —
  на 90% NaN → непригодны. Обогащение каталога LS-ratio фичами ОТМЕНЕНО.

Вывод: feature contract сводится к фичам, **уже** в каталоге. Новых
добавлять нечем — то, что богато в live, не имеет 2-летней истории.

---

## live_grade per feature

| Feature | live_grade | Комментарий |
|---|---|---|
| `move_pct` | **reliable** | move за 30м-окно — из OHLC баров, есть везде |
| `move_t5/15/30/60` | **reliable** | move на горизонтах — из баров |
| `accel` | **reliable** | 2-я производная цены — из баров |
| `wick_ratio` | **reliable** | форма свечей — из баров |
| `vol_spike` | **reliable** | volume в окне / медиана 24ч — volume есть в barах |
| `funding_at_anchor` | **reliable** | funding 8h — `deriv_live.json` отдаёт, 100% истории |
| `n_triggers` | **reliable** | число триггеров события — детерминировано детектором |
| `taker_win` | **snapshot-only** | live taker_buy_pct — снапшот раз в N мин, не поминутно |
| `taker_t5/15/30/60` | **snapshot-only** | то же — горизонтное среднее в live не точное |
| `oi_delta_win` | **snapshot-only** | ΔOI за 30м — live OI снапшотный, дельту не собрать |
| `oi_delta_t5/15/30/60` | **snapshot-only** | то же |
| `trigger_price` | **exclude** | абсолютная цена — не фича, нормализующий якорь |
| `fwd_extreme_pct` | **LEAK** | forward-looking — считается из 4ч-исхода |
| `bars_to_return` | **LEAK** | forward-looking |
| `bars_to_continue` | **LEAK** | forward-looking |
| `move_24h_signed` | **LEAK** | forward-looking |
| `outcome` | **TARGET** | целевая метка trend/whipsaw |

---

## РЕШЕНО: вариант A (reliable-only) — проверено по данным

Замер 2026-05-22 на каталоге 8b51acd (475 trend/whipsaw, GBM depth-3):

| Набор фич | фич | CV AUC | OOT AUC (50/50) |
|---|---|---|---|
| **reliable-only** | 10 | 0.877 | **0.902** |
| reliable+snapshot | 20 | 0.871 | 0.851 |

**reliable-only не просто проходит — он ЛУЧШЕ.** OOT 0.902 против 0.851
у полного набора. snapshot-фичи (taker_*, oi_delta_*) на out-of-time
не помогают, а вредят — переобучают на train-периоде, на будущем
разваливаются. 10 ценовых+funding фич устойчивее во времени.

**Следствия:**
- Вариант B (поминутный OI/taker логгер) — НЕ НУЖЕН. Инфра-работа снята.
- Финальная модель обучается на 10 `reliable` фичах:
  `accel, funding_at_anchor, move_pct, move_t5, move_t15, move_t30,
   move_t60, n_triggers, vol_spike, wick_ratio`.
- Все 10 — из OHLC-баров + funding → гарантированно есть в live.
  `build_live_features()` дописывается ровно под этот список, без
  snapshot-зависимостей.

Машиночитаемый список — `state/pump_feature_grades.json` (ключ `reliable`).

---

## Контракт meta.json (для resume_model.py)

Артефакт `models/pump_resume_gbm.meta.json` обязан содержать:
```json
{
  "feature_order": ["move_pct", "move_t15", ...],   // только выбранные фичи
  "live_grade_used": "reliable | reliable+snapshot",  // какой вариант
  "horizon_min": 30,
  "whipsaw_threshold": 0.65,
  "trend_threshold": 0.35,
  "oot_auc": 0.xx,                                   // подтверждённый OOT
  "trained_on": "state/pump_event_catalog.csv @ 8b51acd"
}
```
`feature_order` — НИ ОДНОЙ фичи с `live_grade` = LEAK / exclude / TARGET.
`build_live_features()` в `loop.py` дописывается строго под этот список.
