# LONG inverse XBTUSD — независимая верификация колегин $7-8M plan

**Дата:** 2026-05-18
**Контекст:** колеги (Win) в `docs/STRATEGIES/GINAREA_VOLUME_STRATEGY_2026-05-17.md`
(ветка `chechikov-win/range-hunter-emitter-2026-05-15`) предложил Level 2 plan
с добавлением LONG-ОБЪЁМ и LONG-ХЕДЖ, claim DD=$0 в 11/11 окон и vol $3.7M/мес.

Backtest engine колеги (`backtest_lab.engine_v2.bot.GinareaBot`) присутствует
только на его Win окружении. На Mac я не могу воспроизвести его sim напрямую.

**Решение:** написан независимый sim
`scripts/verify_long_objem_dd.py` — LONG-only inverse XBTUSD grid с правильной
PnL-математикой `pnl_btc = qty_usd × (1/entry − 1/exit)` (LONG inverse),
equity = realized + unrealized, max DD по equity curve.

## Sim setup

- Данные: `backtests/frozen/BTCUSDT_1m_2y.csv` (1,055,422 1m баров)
- Разбиение: 104 непересекающихся окна по 7 дней
- Anchor = close первого бара каждого окна (static, как в GinArea без reanchor)
- Grid: N уровней ниже anchor с шагом `gs%`, BUY на каждом
- На fill BUY → создаётся TP SELL по `entry × (1 + target%)`
- На fill TP SELL → level освобождается (мимикрия GinArea auto-replace)
- max_opened: cap concurrent open positions
- Always-on (без `in.start.cnds` per колеги doc)

## Результаты по конфигам

### LONG-ОБЪЁМ (gs=0.02, max=200, target=0.13, $100/order, $20k max exposure)

| metric | value | колеги claim |
|---|---|---|
| Volume mean/wk | $454,818 | — |
| **Volume monthly (×4)** | **$1.82M** | **$1.68M ✓ (+8.3%)** |
| Realized PnL mean/wk | +$291 | — |
| Realized annual (×52) | +$15,132 (75% годовой на $20k) | — |
| **Max DD mean/wk** | **$624** | **$0 ✗** |
| Max DD median | $267 | $0 |
| **Max DD worst** | **$4,741** (BTC −9.05% за 7d) | $0 |
| DD = $0 окон | 4% (тихие, нет fills) | 100% |
| DD < $500 окон | 61% | — |
| DD $500-3k окон | 33% | — |
| DD $3k+ окон | **3% (tail events)** | — |

**Volume claim ✓ ПОДТВЕРЖДЁН**, DD claim ✗ OVERSTATED.

### LONG-ХЕДЖ (gs=0.04, max=80, target=0.85, $100/order, $8k max exposure)

| metric | value | колеги claim |
|---|---|---|
| Volume mean/wk | $33,149 | — |
| **Volume monthly** | **$0.13M** | **$2.06M ✗ (−93.6%)** |
| Realized PnL mean/wk | +$128 | — |
| Realized annual | +$6,656 | — |
| Max DD mean | $287 | $0 |
| Max DD worst | $1,931 | $0 |
| DD ≥ $3k окон | 0% | — |

**Volume claim ✗ NOT confirmed** — реальный объём ×15 меньше из-за широкого
target=0.85% (round-trips редкие). Расхождение указывает на возможный
bug в engine_v2 для wide-target inverse LONG configs.

## Verdict для деплоя

1. **LONG-ОБЪЁМ — DEPLOY (вначале с половинным size)**
   - Реальный объём $1.8M/мес validated
   - DD не $0 но manageable: mean $624 на $20k = 3% weekly avg
   - Worst-case $4.7k в редких -10% BTC weeks = 24% intra-week temporary
   - C3 TWAP defender bot7 поймает bleed и пришлёт сигнал → ручной hedge

2. **LONG-ХЕДЖ — SKIP**
   - Мой sim даёт ×15 меньше объёма
   - Профиль "много капитала ради микро-объёма" не оправдан
   - Альтернатива: scale LONG-ОБЪЁМ size $100 → $200 даёт $3.6M/мес
     при DD mean $1.2k (всё ещё manageable)

3. **Цель колеги $8.1M/мес (Level 2) — частично достижима**
   - Existing $3.16M (managed $1.36M + personal $1.8M) +
   - LONG-ОБЪЁМ full size +$1.8M +
   - LONG-ОБЪЁМ scaled-up (если testbed validate) +$1.8M = **$6.8M/мес total**
   - Гэп до 8.1M закрывается либо ШОРТ-ОБЪЁМ (DD $3-4k риск) либо B2 Session-breakout (PF 1.85 deployed)

## План валидации перед full deploy

| день | действие | критерий |
|---|---|---|
| **D0** (сегодня) | создать LONG-ОБЪЁМ в GinArea с **minQ=50 USD** (половина) | бот в `ACTIVE` |
| **D1-D2** | мониторить trade_volume, position, current_profit | volume ~$200-250k за 2 дня |
| **D3-D7** | сравнить РЕАЛЬНЫЙ max intraday DD с моим sim ($300-1.2k diapason) | если DD ≤ $1.2k → OK, если ×2-3 выше → разбор |
| **D7** | решение: scale up minQ 50 → 100, OR hold, OR rollback | data-driven |
| **D14** | если scale up прошёл успешно — рассмотреть scale LONG-ОБЪЁМ-2 (вторая инстанция на другом ценовом anchor) | only after positive validation |

## Источники
- Колеги doc: `docs/STRATEGIES/GINAREA_VOLUME_STRATEGY_2026-05-17.md` (в ветке `chechikov-win/range-hunter-emitter-2026-05-15`)
- Колеги backtest base: `docs/STRATEGIES/COMBINED_ALL_BOTS_V2.md` (engine_v2 managed_grid_sim)
- Sim код: `scripts/verify_long_objem_dd.py`
- Sim data: `backtests/frozen/BTCUSDT_1m_2y.csv`
