# Mac → Win: что сделано, проверь (2026-05-30)

Ветка `alexey/mac-2026-05-29` (запушена на origin). Новые коммиты после твоего
хендофф-документа:

| commit | что |
|---|---|
| `3d9ac8b` | reality-filter re-grade — executor на выживших, limit-only |
| `4a62195` | визуальный разбор сделок на свечах |
| `9417c54` | phase-2b — ETH-исполнение |

Метод 3.3 принят: **истина = setup_precision_outcomes.jsonl + живой P&L, paper НЕ метрика.**

---

## 1. Подтвердил твою находку независимо ✅
Пересчитал `setup_precision_outcomes.jsonl` (n=252) сам — твой ранжир воспроизводится.
long_multi_divergence = **54 TIMEOUT / 2 SL / 1 TP1, avg −0.075%**.
**Проверка:** `tools/_reality_regrade.py` (печатает таблицу) → `docs/STRATEGIES/REALITY_FILTER_REGRADE.md`.

## 2. Ответ на 3.1 — калибровка филлов из 6 живых сделок
Источник: `state/auto_executor_outcomes.jsonl` (6 сделок, все long_pdl_bounce BTC).
- **Entry slippage:** limit-филлы 0.00%; market_fallback +0.15…+0.31% (4 из 6). Блендед +0.145%.
- **Находка важнее слиппеджа:** market_fallback = adverse selection — **4/4 fallback-входа → SL; 2/2 чистых limit → флэт.**
- → В re-grade заложил калиброванную модель (косты 0.15/0.30/0.45%); вместо твоих грубых −0.3%.
- **Проверка:** перечитай 6 строк `auto_executor_outcomes.jsonl` (поля entry_price/avg_entry_price/exit_reason).

## 3. Визуальный разбор → ГЛАВНАЯ находка: эдж на АЛЬТАХ, не BTC
`tools/_chart_setups.py` → `docs/STRATEGIES/setup_charts.html` (свечи + входы/выходы).
Per-pair из precision (net@0.30%):

| пара | n | avg/сделку | net@0.30% |
|---|---|---|---|
| BTCUSDT | 17 | +0.27% | **−0.04%** 🔴 |
| ETHUSDT | 20 | +0.80% | **+0.50%** 🟢 |
| XRPUSDT | 16 | +1.57% | **+1.27%** 🟢 |

На ETH: pdl_bounce 9/9, dump_reversal 6/6, double_bottom 5/5 TP1. На BTC те же — таймауты.
**Executor торговал BTC-only = худшую пару.** Это объясняет «paper красиво / live минус».
**Проверка:** сгруппируй precision_outcomes по (setup_type, pair) — счётчики outcome совпадут.

## 4. Что изменено в executor (live, реальные деньги, микро)
`services/auto_executor/`:
- **ALLOWED_SETUPS** = long_pdl_bounce, long_dump_reversal, long_double_bottom (3 выживших).
  Убран long_multi_divergence (honest −21%).
- **Откачены шорты** 2026-05-29 (были на paper PF, honest n=1 минус). SHORT-код есть, gated off.
- **market_fallback ОТКЛЮЧЁН** (`MARKET_FALLBACK_ENABLED=False`) — лимит-онли, не догоняем рынком.
- **Phase-2b: ALLOWED_PAIRS += ETHUSDT.** Динамический sizing по живым спекам инструмента
  (`underlying = orderQty / underlyingToPositionMultiplier`; сверено с публичным API:
  ETH lotSize=1000/u2p=1e5 → min 0.01 ETH ≈ $20; XBT 0.0001 ≈ $7) + **жёсткий $30 nominal guard**.
  Multi-symbol last-price в `_manage_filled`. Side-aware loop (инверсия SL/TP) — протестирован.
- **Проверка:** `pytest tests/services/auto_executor/ -q` → **65 passed**. Спеки: публичный
  `GET bitmex.com/api/v1/instrument?symbol=ETHUSDT` (поля lotSize/underlyingToPositionMultiplier).

## Что НЕ доказано (честно)
- Эдж выживших — **окно 8–12 мая, out-of-time НЕ проверен**. N мал (15–21).
- Калибровка односетаповая (6 живых = long_pdl_bounce BTC). Кросс-сетап/кросс-пара не калибровано.
- Живые ETH-филлы = первая внешняя проверка гипотезы «правый сетап, правая пара».

## Что от тебя
Наводи свой re-grade движок на **ETH precision-данные** (там эдж). И, если согласен —
out-of-time проверка выживших (разные окна), прежде чем растить размер/добавлять XRP.
