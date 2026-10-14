# На проверку GPT — всё новое после разбора 13.10 (8d46c36) — 14.10.2026

Ветка `alexey/mac-2026-05-29`. Ниже — что изменилось, где лежит и что именно проверить. Частный пакет с учётом и
журналами ботов (`docs/WEEX_GRID_CODE_FOR_GPT_2026-10-14.md`, в .gitignore) оператор передаёт отдельно.

## 1. Ответы на разбор 13.10 — `docs/WEEX_GPT_GOLD_AND_BOTS_ANSWERS_2026-10-13.md`
Принято всё; каждый дефект — тест, падающий на 8d46c36. Влито:
- проверочные скрипты (214d735): `research/weex/account_now.py`, `orphan_check.py`, `pnl_reconcile.py`,
  `errors_today.py`, общий `weex_monitor_common.py`; тесты `tests/research_weex/`;
- инструменты данных (fc2be20): общая блокировка gapfill↔repair, полный час/день по уникальной сетке минут,
  `fetch_1m` без незакрытой минуты, половины `regime_grid`, месяцы `fast_grid`, ключ GinArea с точными концами и
  хешами; тесты `tests/research_tools/`;
- золото (26b03bf): причинность LVN, полнота XAU, фандинг XAU (8ч→4ч с 30.01.2026), EOF, цензура конца, шаг PAXG по
  дате, правило отмены ТЗ, R в двух единицах на одном ledger, контроль LVN (общий профиль дня, NA при нуле), CI B−A;
  отчёт `docs/GOLD_LIQUIDITY_SWEEP_RESEARCH_2026-10-13.md` переписан.

## 2. Торговый движок — **в живом боте с 14.10 18:13 UTC** (слово оператора)
Коммиты 6cdb7a1, a3b0af6, 5116ec6, слияние e2413ca; три независимые проверки ветки до выкатки.
- W1/W2: единый классификатор детали ордера во всех путях; UNKNOWN → без замены и без снятия владения; release
  ждёт разрешения всех ордеров стороны.
- Учёт передачи стороны: `transfers` / `transferred_mtm`, карточка показывает переданный мешок; миграция из журнала.
- `last_tick_ok_ts` / `last_tick_error`; `open_orders` при 10 полных страницах — WeexIncomplete, проход прерывается.
- **Новое (наша проверка F1):** ордер неясен ≥ 5 мин → одно сообщение в Telegram, повтор ≤ раз в час; блокировка
  закрытия по режиму / передачи стороны названа прямо; «мигающий» ответ не обходит лимит (тест: 22 → ≤3 за 2 ч).
- Настоящая форма WEEX `GET /capi/v3/order` (14.10, с живого счёта): orderId — число, executedQty — строка, в т.ч.
  у CANCELED; закреплено тестом `test_real_weex_detail_shape_*`.
- Выкатка: ордера до/после идентичны, первый проход успешен, сверка BTC (вкл. переданный SHORT с MTM) и ETH до цента.
- **Известный остаток:** повторная передача стороны, возвращённой боту, без лотов не пишет запись (мониторинг даёт
  тревогу, не ложное «ок»).
Проверить: `services/weex_grid/engine.py` (`_detail`, `_unknown`, `_escalations`, `release_side`,
`_migrate_transfers`, `bot_pnl`), `services/weex_grid/loop.py` (`card`), `services/weex_api/client.py`
(`_open_pages`), тесты `tests/services/weex_grid/test_weex_gpt1013.py`, `test_weex_gpt1014.py`.

## 3. ТЗ ATLAS/TradingView (1ee7e1a)
- Часть 1 «что уже реализовано» + P0 сборщиков: `docs/ATLAS_TRADINGVIEW_DATA_RESEARCH_RESULTS_2026-10-13.md`
  (аудит 13.10 проверял мёртвый `collectors/liquidations`; живой — `market_collector/liquidations.py`). P0 сделано:
  `services/weex_book/recorder.py` — depth (все уровни, U/u, E, recv_ms, session, applied), trades2 (ID сделки,
  recv_ms, m как пришло), events (connect/snapshot/gap/resync/disconnect); `market_live/liq_raw/*.jsonl` — время
  биржи + приёма, основа цены, ctVal/версия спецификации OKX.
- Дельта агрессора на 15m (ядро ATLAS «дельта против свечи»): протокол до расчётов
  `docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md` (715a2de), результат `docs/ATLAS_DELTA_RESULTS_2026-10-14.md` (1061091):
  BTC n 927 −0.150%, ETH n 929 −0.151% на сделку после расходов WEEX; независимая реализация совпала.
- Footprint (дельта в фитиле), 8 недель aggTrades: протокол `docs/ATLAS_FOOTPRINT_PROTOCOL_2026-10-14.md` (18bc3db),
  результат `docs/ATLAS_FOOTPRINT_RESULTS_2026-10-14.md`: BTC n 190 −0.14%, ETH n 169 −0.12%; две реализации совпали.
- TradingView: доступа к аккаунту нет — матрица тарифа «нет данных».
Проверить: `research/atlas_data/*.py`, расширение `research/gold/sweep_backtest.py` (UM-инструменты, версия Cn),
тесты `tests/research_atlas/`.

## 4. Прочее
- Оператор 14.10 спросил шаг 0.1 вместо 0.6 при ордере 0.0006 для живой BTC-сетки: при лимите 50 ордеров +$916
  против +$2 423 за 2 года; с лимитом 200 — +$2 126 (просадка −$1 350 против −$1 441). Разница почти вся от лимита
  ордеров; `research/weex/regime_grid.py --max-lots=`. Конфиг не менялся.

## Вопросы
1. Классификатор и эскалация неясных ордеров — нет ли пути, где живой ордер всё же теряется или сообщение не приходит.
2. Учёт передачи (`bot_pnl` с MTM переданного мешка) и миграция из журнала — верна ли граница для дневного риска.
3. Дельта/footprint: нет ли заглядывания вперёд или смещения контроля, которые могли бы скрыть край.
