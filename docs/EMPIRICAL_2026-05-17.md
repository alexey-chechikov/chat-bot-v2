# EMPIRICAL REVIEW — 2026-05-07 → 2026-05-17

**Период:** ~10 дней live (от деплоя нового стека).
**Скрипт:** `scripts/_empirical_review_20260517.py` (запускался через `.venv/bin/python`).
**Tone:** реалити-чек. Главный вывод спойлером — *счёт +8.78%, но 90% обещанных edges либо не эмитят, либо ловят в основном SL.*

---

## §0. Sanity: что вообще логировалось

| источник | rows total | в периоде | заполненность outcome |
|---|---|---|---|
| range_hunter_signals*.jsonl (BTC/ETH/XRP) | 15 | 15 | 0 |
| short_bots_audit.jsonl | 2 | 2 | оба `dry_run` test |
| confluence_fires.jsonl | 2 | 2 | n/a |
| play_journal.jsonl | 174 | 174 | 162 resolved |
| paper_trades.jsonl | 462 | 462 | 145 closes |
| p15_paper_trades.jsonl | 214 | 214 | 57 CLOSE |
| margin_automated.jsonl | 10 483 | 10 478 (5 артефактов с mark=0) | snapshot каждые ~60с |
| regime_shadow.jsonl | 2081 | 2081 | shadow only |
| grid_coordinator_fires.jsonl | 106 | 106 | regime-snapshot |

---

## §1. Range Hunter (6 emitters)

**Вывод:** Range Hunter фактически не работает. За 10 дней — 15 эмиссий, из них **placed=1**, **closed_with_pnl=0**. Live ничего не подтверждает и не опровергает.

| symbol | emits | variants | placed | closed (pnl) | total_pnl | первый эмит | последний |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 10 | 1m × 9 + legacy × 1 | 1 | 0 | $0.00 | 2026-05-15 19:59 | 2026-05-16 21:50 |
| ETHUSDT | 3 | 1m × 3 | 0 | 0 | $0.00 | 2026-05-16 18:46 | 2026-05-16 22:46 |
| XRPUSDT | 2 | 1m × 2 | 0 | 0 | $0.00 | 2026-05-16 19:44 | 2026-05-16 21:44 |

**Расхождения схемы с ожиданием:**
- В live-логе **нет** полей `event` (signal/outcome), `bar_minutes`, `variant_name`, `tp`, `sl`, `levels_source`, `outcome`. Каждая строка — одна *одиночная* запись с pre-fill полями (`buy_fill_ts: null`, `exit_ts: null`, `pnl_usd: null`).
- Поле `variant` имеет значение **только `"1m"`** — 5m варианты не эмитят **ни на одном символе** (или эмитят в этот же файл без отметки и неотличимы).
- Поле `levels_source` отсутствует — split vpvr_snap vs mid_symmetric невозможен.

**Бэктест-baseline из HANDOFF §1.2 (для контекста, не для сравнения):** BTC WR 68.6% / +$8994 (2y), ETH 73.8% / +$3677, XRP 77.1% / +$3610.

**Что делать дальше:** диагностировать почему RH вообще не эмитит (либо filter слишком жёсткий, либо emitter не запущен, либо первые сигналы появились только 15 мая → 1.5 дня настоящего live'а). До починки — никаких выводов о WR / proximity boost / 5m vs 1m делать нельзя.

---

## §2. short_bots_guard auto-pause

**Вывод:** Guard за 10 дней **не сделал ни одного real pause/resume**. Каскады (cascade_short_5.0, cascade_long_2.0 и т.д.) фиксировались в dedup, но триггера pause не было. Возможные причины: либо параметры (`MAX_PAUSE_HOURS`, `ADVERSE_CASCADE_AGE_MIN`, `REVERSAL_MIN_SCORE`) слишком строгие, либо guard ещё не интегрирован в hot loop.

### short_bots_audit.jsonl (в периоде)

| ts | bot | action | reason | trigger |
|---|---|---|---|---|
| 2026-05-16T21:48:48 | 4729923198 (SHORT-T1) | `dry_run` | manual_test | dry_run_test |
| 2026-05-16T21:48:50 | 4729923198 (SHORT-T1) | `noop_already` | manual_test | dry_run_test |

**Текущее состояние `short_bots_auto_pause.json`:** `{"triggers": {}, "paused": {}}` — пусто.

**Cascade dedup (последний таймстемп каждого триггера):**
- short_5.0 → 2026-05-16T10:09:28
- short_2.0 → 2026-05-16T06:44:03
- long_5.0 → 2026-05-16T14:47:17
- long_2.0 → 2026-05-16T14:50:20
- long_10.0_mega → 2026-05-15T05:32:57
- short_10.0_mega → 2026-05-16T09:18:36

То есть каскады **были** (минимум 6 разных триггеров за период), но `short_bots_audit.jsonl` остался пуст. Pause-pipeline отключён или не подписан на них.

**Что делать дальше:** проверить логи orchestrator: подписан ли `short_bots_guard` на `cascade_*` ивенты, и почему 6 distinct cascade-сигналов не дали ни одного `action=pause`. Без этого нельзя оценить ни качество паузы, ни reversal_override, ни max_timeout.

### §2b grid_coordinator_fires.jsonl

106 событий в периоде. Это сейчас единственный *реально работающий* кросс-сигнал.

| direction | count |
|---|---|
| down (бычьи перегревы) | 78 |
| up (медвежьи перегревы) | 28 |

Сильный перекос в `down`: бот фиксировал перегретые SHORT-условия (RSI/MFI lows + ETH sync + funding) в 3 раза чаще, чем LONG-перегревы. Согласуется с тем, что BTC за период −2.11% — рынок продавался.

---

## §3. Confluence (high-conviction карточки)

**Вывод:** 2 fires за 10 дней — недостаточно для статистики.

| ts | dir | count | sources | price |
|---|---|---|---|---|
| 2026-05-16T14:50:35 | SHORT | 2 | cascade_long_2.0 + cascade_long_5.0 | 78147 |
| 2026-05-16T15:46:40 | LONG | 2 | taker_imbalance_long + topshort_divergence_long | 78204 |

Оба fire — последний день периода, outcome ещё не залогирован. **data: 2 events, not significant.**

### §3b play_journal.jsonl (taker_imbalance / topshort_divergence)

174 fire в периоде — главное «реальное» окно в performance детекторов:

| label | n | resolved | TP1 | TP2 | STOP | pending | WR(TP1/resolved) |
|---|---|---|---|---|---|---|---|
| taker_imbalance_long | 87 | 81 | 0 | 0 | 5 | 6 | **0.0%** |
| taker_imbalance_short | 80 | 74 | 2 | 2 | 1 | 6 | 2.7% |
| topshort_divergence_long | 7 | 5 | 0 | 0 | 0 | 2 | 0.0% |

**Шок:** `taker_imbalance_long` стрелял 87 раз, TP1/TP2 = **0 раз**. Это полностью провальный детектор за этот период (или у него крайне узкие TP/SL pct: TP1=0.27%, stop=−0.4%, и за 24h в дрейфе вниз цена в основном ездит по stop). Resolved=81/87 → outcome пишется штатно, но edge не подтверждается. Это **первый кандидат на отключение/перетюн**.

**Что делать дальше:** disable `taker_imbalance_long` (или поднять threshold с 58 до 65+); протестировать short вариант на более широком окне.

---

## §4. long_multi_divergence + остальные paper-стратегии

**Вывод:** `long_multi_divergence` — единственная стратегия, **которая воспроизвела backtest-цифры почти в точку**. Все short-стратегии в paper — отрицательные.

### Свод по `paper_trades.jsonl` (по setup_type, 145 closes total)

| setup_type | opens | TP1 | TP2 | SL | EXP | WR | pnl USD |
|---|---|---|---|---|---|---|---|
| **long_multi_divergence** | 57 | 37 | 2 | 2 | 16 | **68.4%** (если EXP не считать) | **+$5624.87** |
| long_pdl_bounce | 14 | 20 | 2 | 4 | 0 | 84.6% | +$1384.89 |
| long_dump_reversal | 11 | 8 | 0 | 3 | 0 | 72.7% | +$524.99 |
| long_div_bos_15m | 3 | 0 | 1 | 2 | 0 | 33.3% | +$514.54 |
| long_mega_dump_bounce | 8 | 0 | 0 | 6 | 2 | 0.0% | +$319.31 (артефакт?) |
| short_rally_fade | 3 | 1 | 2 | 0 | 0 | 100.0% | $0.00 |
| cascade_long_2btc | 1 | 0 | 0 | 1 | 0 | 0.0% | −$40.00 |
| long_double_bottom | 12 | 8 | 0 | 4 | 0 | 66.7% | −$72.83 |
| cascade_long_5btc | 2 | 0 | 0 | 2 | 0 | 0.0% | −$100.00 |
| long_div_bos_confirmed | 1 | 0 | 0 | 1 | 0 | 0.0% | −$150.00 |
| short_mfi_multi_ga | 3 | 0 | 0 | 2 | 1 | 0.0% | −$229.54 |
| **short_pdh_rejection** | 15 | 0 | 2 | 13 | 0 | 13.3% | **−$497.47** |
| **short_double_top** | 14 | 3 | 0 | 2 | 7 | 25.0% | **−$858.93** |

### Сравнение с baseline (HANDOFF §3.1: 57 trades / 87.7% WR / +$5625 за 8-15 May)

| метрика | HANDOFF baseline | Live 5-07..5-17 | Дельта |
|---|---|---|---|
| trades | 57 | 57 | 0 |
| WR | 87.7% | 68.4% (TP1+TP2 vs SL, EXP исключены) | −19.3 п.п. |
| WR (включая EXP как loss) | n/a | 51.8% | заметно ниже |
| pnl | +$5625 | +$5624.87 | −$0.13 (sic!) |

**Идентичность по pnl с точностью до цента подозрительна** — возможно это тот же набор сделок, и HANDOFF и live смотрят на одни данные. Тем не менее тренд по сравнению с другими стратегиями ясен: **`long_multi_divergence` — единственный edge, который держится**.

### p15 (paper)

| side | opens | CLOSE | HARVEST | pnl |
|---|---|---|---|---|
| long | 75 | 44 | 43 | **−$1104.45** |
| short | 28 | 13 | 11 | −$198.55 |
| **Total** | 103 | 57 | 54 | **−$1303.00** |

p15 теряет в paper. Это противоречит backtest-обещаниям (нужно сверять с HANDOFF; если там p15 был «зелёным», то tuner за 10 дней не подтвердил).

**Что делать дальше:**
- Оставить `long_multi_divergence`, `long_pdl_bounce`, `long_dump_reversal` (единственные 3 стратегии с >+$500 pnl и WR ≥68%).
- Отключить или пересмотреть: `short_pdh_rejection`, `short_double_top`, `short_mfi_multi_ga`, `cascade_long_*btc`, `long_div_bos_confirmed`.
- p15: либо tuner-параметры неверны, либо рынок плохой для p15 (range_wide → trend_down переход). Нужен сепаратный аудит p15 на 14-15 мая (где была половина убытка).

---

## §5. BitMEX margin trajectory

**Вывод:** **счёт +8.78% за 10 дней**. Главный позитив. Просадка контролируема (max DD от пика 16.52%). Distance to liquidation никогда не падало ниже 14.5%.

| метрика | значение |
|---|---|
| период | 2026-05-07 21:06 → 2026-05-16 23:05 |
| samples (после фильтра 5 артефактов с mark=0) | 10 478 |
| margin balance start → end | $23 733.35 → **$25 817.69** (+$2 084.34, **+8.78%**) |
| wallet balance start → end | $24 461.17 → $26 728.13 (+$2 267.96) |
| margin min / max | $20 174.26 / $25 980.79 |
| max DD from peak | **16.52%** |
| coefficient (autoderiv) min/max | 0.9785 — 1.0000 |
| distance to liquidation % | 14.53% — 45.10% |
| BTC mark start → end | $79 824 → $78 137 (**−2.11%**) |

**Daily margin trajectory:**

| дата | margin USD | Δ день |
|---|---|---|
| 2026-05-07 | $23 603.05 | — |
| 2026-05-08 | $23 618.86 | +$15.81 |
| 2026-05-09 | $23 206.43 | −$412.43 |
| 2026-05-10 | $20 856.67 | **−$2 349.76** ← худший день |
| 2026-05-11 | $21 610.43 | +$753.76 |
| 2026-05-12 | $23 750.93 | +$2 140.50 |
| 2026-05-13 | $25 069.62 | +$1 318.69 |
| 2026-05-14 | $23 611.25 | −$1 458.37 |
| 2026-05-15 | $25 537.32 | +$1 926.07 |
| 2026-05-16 | $25 817.69 | +$280.37 |

Net positive дней: 6 из 10. Самый болезненный — 5-10 (−$2.35k за день, −10% от баланса). Учитывая что BTC за период упал на 2.11%, а счёт вырос на 8.78%, **bot бил рынок на ~11 п.п. за 10 дней** — это серьёзно. Источник α неизвестен (RH/short_bots_guard не работали, paper не идёт в реальные деньги), вероятно — grid-боты (T1/T2/T3 + LONG-D/V5) живут хорошо в `range_wide`-условиях; и каскад-перегревы не били их в опасное направление.

**Что делать дальше:** разобрать что произошло 5-10 (вряд ли просто BTC — он в этот день упал на ~2%, а у нас просел на ~10%). Возможно cascade event или forced liquidation на одном из бот-аккаунтов. Без этого риск повторения.

---

## §6. Vol/Regime distribution

**Вывод:** Преимущественно RANGE, согласие detector_a vs detector_b — **43% (904/2081)**, рассогласие 37%, n/a 19%. Это значимое расхождение между двумя regime-движками.

| verdict_a (новый) | count | % |
|---|---|---|
| RANGE | 750 | 36.0 |
| TREND_DOWN | 599 | 28.8 |
| COMPRESSION | 367 | 17.6 |
| TREND_UP | 365 | 17.5 |

| verdict_b (старый) | count | % |
|---|---|---|
| RANGE | 1541 | 74.1 |
| AMBIGUOUS | 397 | 19.1 |
| TREND | 143 | 6.9 |

| agree | count | % |
|---|---|---|
| True | 904 | 43.4 |
| False | 780 | 37.5 |
| None (AMBIGUOUS на B) | 397 | 19.1 |

**Top modifiers** (на verdict_a): `POST_FUNDING_HOUR` (2081 — всегда?), `WEEKEND_LOW_VOL` (2081 — всегда?!), `WEEKEND_GAP_DETECTED` (938). То что два модификатора стоят на 100% строк — это **баг**, а не сигнал.

**Что делать дальше:**
- Verdict_b слишком «толерантный» (74% RANGE) — устарел и почти бесполезен как differentiator. Подумать о выводе из эксплуатации.
- Разобрать почему `POST_FUNDING_HOUR` и `WEEKEND_LOW_VOL` стоят на 100% строк. Это явный bug в modifier-вычислителе. **P0 fix.**

---

## §7. Tuning recommendations

| # | item | действие | oboснование |
|---|---|---|---|
| 1 | RH emitters (BTC/ETH/XRP, 1m + 5m) | **диагностировать почему 15 эмиссий за 10 дней** | live ничего не подтверждает; 5m варианты не видны вообще |
| 2 | RH schema | мигрировать на `event=signal/outcome` + добавить `bar_minutes`, `levels_source`, `tp`, `sl`, `outcome`, `pnl_usd` | без этого нельзя считать WR / proximity boost item 3 |
| 3 | `taker_imbalance_long` | **DISABLE** или поднять threshold 58 → 65+ | 87 fires, TP1=0, WR=0%. Чисто отрицательный edge |
| 4 | `short_pdh_rejection`, `short_double_top` | DISABLE или ужесточить вход | в paper суммарно −$1356 за период; WR 13–25% |
| 5 | p15 | сепаратный аудит, особенно 14-15 мая | −$1303 в paper за 10 дней — противоречит ожиданиям |
| 6 | `short_bots_guard` integration | проверить subscription на cascade_* events | 6 distinct cascades за период, audit log пуст. Pause-pipeline не работает |
| 7 | regime modifiers bug | fix `POST_FUNDING_HOUR` и `WEEKEND_LOW_VOL` (стоят на 100%) | очевидный bug в modifier evaluator |
| 8 | verdict_b regime detector | депрекейт | 74% RANGE — не различает состояния |
| 9 | 5-10 drawdown investigation | разобрать −$2.35k день | риск повторения, источник неизвестен |
| 10 | `long_multi_divergence` | **оставить, расширить размер** | единственный детектор с подтверждённым live-edge: 57 trades, 68%+ WR, +$5625 |

---

## §8. Decision matrix (P0/P1/P2)

| Priority | Item | Описание | Ожидаемый эффект |
|---|---|---|---|
| **P0** | item 6 — short_bots_guard wiring | guard не пинговался cascade-ами при 6 distinct fires | Защита grid-капитала в squeeze; ключевой компонент стека |
| **P0** | item 7 — regime modifiers bug | `POST_FUNDING_HOUR` / `WEEKEND_LOW_VOL` на 100% строк | regime отчёт врёт; downstream detector'ы могут гейтиться неверно |
| **P0** | item 3 — disable `taker_imbalance_long` | 0/87 WR — чистый −EV | устранить шум-источник в confluence |
| **P1** | item 1 — RH diagnose | почему 15 эмиссий за 10 дней | без этого item 2 бессмысленен |
| **P1** | item 9 — 5-10 drawdown audit | −$2.35k за день при BTC −2% | риск-менеджмент |
| **P1** | item 2 — RH schema migration | event/outcome + levels_source | unblock proximity-boost A/B |
| **P1** | item 4 — disable failing short stratты | short_pdh_rejection + short_double_top | паузить кровотечение в paper до tuning |
| **P2** | item 5 — p15 audit | разобрать 14-15 мая | возможно регим-зависимо, не катастрофа |
| **P2** | item 8 — depreкейт verdict_b | старый regime detector | hygiene, не блокирует ничего |
| **P2** | item 10 — increase `long_multi_divergence` size | удвоить notional | confidence builder; рост альфы при подтверждённой стратегии |

---

## §9. Bottom line

- **Счёт растёт** (+8.78% за 10 дней против BTC −2.11%) — но **не из-за тех источников, которые мы продаём в HANDOFF'е**.
- **3 из 4 центральных edges либо не запустились, либо не подтвердились**: RH почти молчит; short_bots_guard не интегрирован; taker_imbalance_long — отрицательный. Confluence — 2 fire за 10 дней.
- **Подтверждено только одно:** `long_multi_divergence` (paper) — 57 trades, 68% WR, +$5625, **в точности по плану**.
- **Margin growth, скорее всего, генерируют GinArea grid-боты в range_wide-режиме**, а не новый стек. Это надо явно отделить (live pnl per bot не разбит в этом отчёте).
- Реалити-чек: дано 10 дней; половина из них была доступна только последним 1.5 дня логирования RH; **повторить review через 21 день (2026-06-07)** после исправления P0.
