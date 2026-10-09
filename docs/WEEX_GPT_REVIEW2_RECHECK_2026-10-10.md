# WEEX: перепроверка ответов и исправлений второго разбора — 10.10.2026

Проверен [commit 9cc641e8](https://github.com/alexey-chechikov/chat-bot-v2/commit/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1) ветки `alexey/mac-2026-05-29`. Сначала полностью прочитаны [ответы REVIEW2](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/docs/WEEX_GPT_REVIEW2_ANSWERS_2026-10-10.md), затем исправленный код, тесты и исследовательские скрипты.

**Вывод: значительная часть исправлений подтверждена, но открытых вопросов больше, чем общая ручная позиция, funding и полный счёт.** Остались четыре воспроизводимых сценария потери сопровождения позиции, ошибки комиссионного курсора и неполная выборка сделок. Не утверждается, что они уже случились на вашем счёте.

## Что проверено независимо

- Все **51 тест сетки прошли**: `python -m pytest tests/services/weex_grid -q --tb=short --confcutdir=. --basetemp=<новая временная папка>` → `51 passed in 1.25s`. Заявленные 673 теста всего проекта самостоятельно не воспроизводились.
- Дополнительно выполнены **8 lifecycle, 8 fills, 9 risk/command сценариев** и методологический пробник. Четыре скрипта завершились exit=0; в сценариях дефектов assertions подтверждают неправильное наблюдаемое поведение, а не безопасность кода.
- Атомарная запись проверена с внедрением сбоя перед `os.replace`, а не только чтением готового JSON.
- Пересчитана арифметика всех **25 новых BTC/XAU JSONL-строк**; исправление cut проверено через равенство equity отдельного префикса и carry-baseline.
- Код snapshot, рабочего бота, live config/state и счёт не изменялись; ключи не читались, WeexClient не создавался. Скрипт `pnl_reconcile.py` не запускался: для offline-проверки извлечена только функция `fetch` через AST с подставленным fake client.
- Первые запуски в Windows sandbox встретили WinError5 на atomic replace. В обычном разрешённом запуске все 51 тест прошли; этот эффект окружения исключён из дефектов реализации.

## Что теперь действительно исправлено

| Замечание | Результат перепроверки |
|---|---|
| Битый конфиг XAU становится BTC | **Закрыто в исходном сценарии:** ConfigError, проверка символа template, остановка одной сетки. |
| Битый JSON state становится пустым ботом | **Закрыто в исходном сценарии:** StateCorrupt до отмен/постановок, прежний TP сохранён. Atomic write действительно реализован. |
| Сироты-входы забываются до terminal | **Обычный путь исправлен:** adopt/strays и cumulative cursors сохраняются, повтор/restart не дублируют количество. Осталась граница cancel-before-save. |
| Частичный внешний дефицит стирает весь лот | **Закрыто:** снимается ровно дефицит, остаток сохраняет TP. Это не восстанавливает реальную цену внешнего закрытия. |
| Pending за первой страницей | **Исправлено для 150 более новых ордеров:** находится page1. Полнота за пределом 1000 не обеспечена. |
| Потерянный TP mapping до первого учёта fill | **Исправлено в заявленном тесте:** orphan TP принят и partial записан. Селективная потеря mapping после уже учтённого partial — отдельная граница ниже. |
| Остаток partial entry берётся из нового config qty | **Закрыто в исходном примере:** резерв actual remaining, уменьшение cap снимает старый partial entry. |
| Live partial TP не виден | **Закрыто:** qty/realized меняются сразу; повтор и обычный restart устойчивы. |
| Поздняя комиссия | **Частично:** минутная досверка есть; cursor expiry, миграция и limit100 остаются дефектами. |
| Слоты считаются по фрагментам | **Исправлено для новых parent-лотов:** один parent = один economic slot; продолжение того же entry второй слот не требует. Старые лоты без parent не объединяются автоматически. |
| Неизвестный/≤0 баланс пропускает stress | **Первое чтение исправлено:** добавление запрещено; узкий stale-cache случай остаётся. |
| Sigma BTC для всех | **Закрыто:** кэш и запросы разделены по символу. |
| Новая заявка проходит cap до clamp/rounding | **Закрыто для новой постановки:** проверка по конечной цене. Сохранение старой заявки использует другую ветку. |
| Success без orderId стирает pending | **Закрыто:** intent остаётся. |
| Sweep max10000, cut после операций, hourly DD | **Исправлено:** max50, cut до второй части, DD по минутным close. Tick/mark DD не заявлен и не проверен. |

## P1: что ещё может оставить реальную позицию без учёта и тейка

### 1. Cancel найденного stray раньше устойчивого сохранения

[engine.py:427–430](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/engine.py#L427): `_to_stray` сначала вызывает HTTP cancel, затем добавляет запись; save только после обхода orphan.

**Воспроизведено:** найден дополнительный собственный entry .0012 BTC; во время ответа cancel он исполнился, процесс завершился. На диске stray отсутствует. После restart ордера нет в openOrders, история без pending не запрашивается: **реально .0012 BTC, учёт 0, TP 0**.

**Исправление:** сохранить найденный order/cursors/reservation до cancel; terminal и cumulative fills принять до удаления записи. Atomic JSON не защищает событие, которое ещё не сохранено.

### 2. Live→dry перестаёт сопровождать strays-only состояние

[loop.py:138–140](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/loop.py#L138): `_live_leftovers` проверяет entry/lots/pending, но новый список strays пропускает.

**Воспроизведено штатным flow:** основной entry уже отменён, дополнительный orphan ещё CANCELING; live state содержит только stray. После dry+disabled Runner больше не делает live-проход. Поздний fill **.0012 BTC** остаётся без лота и TP. Запросов live book/info/cancel после перехода **0**.

**Исправление:** считать strays живым остатком до terminal. Наличие unresolved fee_book также требует завершения досверки; это дополнительное следствие предиката, не отдельный численно проверенный сценарий этого пробника.

### 3. Pending всё ещё удаляется после неполного поиска

[engine.py:380–386](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/engine.py#L380), [400–408](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/engine.py#L400): десять полных страниц возвращают None, затем TTL очищает intent. Сообщение оператору не меняет торгового допуска.

**Воспроизведено:** HTTP reply потерян, принятый entry полностью исполнен; после суточного простоя в окне 1000 более новых ордеров символа, исходный лежит на page10. Просмотрены только pages0..9. Pending исчезает, **.0012 BTC не учтены**, ставится новый вход .0012 — потенциально **.0024**.

Условие относится к длинному простою/активной истории, а не утверждению о 1000 ордерах за обычные две минуты. Fake явно относит строки к запрошенному окну.

**Исправление:** FOUND / COMPLETE_NOT_FOUND / INCOMPLETE / ERROR. Полная последняя страница означает INCOMPLETE. TTL уведомляет; новый риск остаётся запрещён до достоверного разрешения. Продолжать устойчивую пагинацию/дробить время либо использовать подтверждённый прямой lookup по client ID, если доступен.

### 4. Изменение sides прекращает сопровождение прежней стороны

[engine.py:542–543](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/engine.py#L542) вызывает lifecycle только для cfg.sides.

**Воспроизведено:** BOTH выставил LONG/SHORT entry .0012; config изменён на SHORT и enabled=false. LONG остаётся NEW, затем исполняется: **реальный LONG .0012, virtual 0, TP 0**. Orphan-поиск видит его как known, поэтому не восстанавливает.

Это ранее не отмеченное поведение, не доказанная регрессия именно нового commit. Триггер — изменение поля sides в конфиге; отдельной Telegram-команды смены sides сейчас нет.

**Исправление:** сверять обе стороны всегда, а новые entry разрешать только enabled && side∈cfg.sides. Исключённой стороне отменять вход с terminal tracking, обслуживать остатки и показывать их в карточке.

Пункты 1, 2 и 4 не устраняются выделением субаккаунта. Он решает ownership, но не потерю собственных событий.

## P2: учёт комиссий пока не идемпотентен во всех обычных путях

### Живой partial order переживает свой fee cursor

[engine.py:268–269](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/engine.py#L268) удаляет запись через час от последнего fill, включая живой entry/TP. Следующий fill создаёт done=0 и снова прибавляет ранее учтённый cumulative fee.

**Воспроизведено:** partial entry .0004 по99800 → fee **.0063872**; он остаётся живым 3601с, cursor удалён; restart и новый cumulative fill .0008 → **учтено .0191616 вместо .0127744**. Лишние .0063872 — повтор первой комиссии. У TP воспроизведён тот же дефект, лишние **.0064063616**.

**Исправление:** долговечный cumulative cursor отдельно от очереди минутной досверки; пока ордер живой, курсор не истекает. Terminal/archived cursor также нельзя сбрасывать при восстановлении.

### Миграция со старого fee_done не сделана

Старый state создан настоящим движком 65eae029 после partial .0004; затем загружен новым. Entry.fee_done не переносится в fee_book. Следующий fill снова даёт **.0191616 вместо .0127744**.

**Исправление:** миграция старых active entry/stray cursors до первого нового fill. Условие — живой старый partial при обновлении; наличие на текущем счёте не установлено.

### Общая досверка снова видит только последние100 fills

[engine.py:254](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/services/weex_grid/engine.py#L254) вызывает user_trades(symbol) без временного окна. Если за поздней комиссией есть100 более новых trades, она не находится, а через час запись удаляется. **Воспроизведён пропуск .0191616**, хотя комиссия появилась внутри часа. Это не утверждается для опубликованных35 live trades.

**Исправление:** полная выборка от самого старого unresolved события либо адресные запросы; timeout оставляет неизвестный fee явно unresolved, а не подтверждённым нулём.

## Дополнительные границы и признанные ограничения

- **Selective lost TP mapping после уже учтённого partial:** реально .0008, после recovery учёт .0004 и realized удвоен. Тест вручную теряет только mapping; обычный путь возникновения такого state в новом атомарном коде не установлен. Это квалифицированная граница recovery, не регулярный новый P1.
- **/start race признана и остаётся:** выключенный daily-stop не снимает уже сохранённый halted. Воспроизведено enabled=true, halted=true после подтверждённого start; следующий tick всё ещё не ставит входы. Требуется сериализация команд/state; нельзя объяснять это только задержкой poll.
- **Старый unfilled entry и сниженный cap:** new desired$119.952 проходит cap$119.97, но tolerance оставляет прежний ордер$120. Превышение в этом примере только$0.03; final-price fix новой постановки не покрывает сохранение старой цены.
- **Просроченный equity cache после ошибки:** при повторном использовании одного Grid или проходе дольше60с возвращается прежний положительный balance. Runner создаёт новый Grid на каждом poll, поэтому это узкая условная граница; первое неизвестное чтение исправлено.
- **Нагрузка fees:** 100 terminal TP дают101 user_trades и100 order_info за проход. Один запрос/минуту относится только к дополнительной досверке. Реальные 429/задержки не измерены. Parent slots могут обслуживать больше реальных TP, чем economic slots.
- **Две config-команды:** read-modify-write гонка возможна при параллельном dispatch, но этот путь Telegram dispatch здесь не подтверждён и не включён в действующие дефекты.
- Общая manual/grid ownership, funding, полный капитал счёта, old/new атрибуция, общий риск после TP и реальные maker fills в ответах честно остаются открытыми. Исправленный ledger не создаёт торговое преимущество.

## Методика: исправления подтверждены, независимый полный replay не выполнен

Max50 действительно передаётся sweep; cut equity берётся до второй части, совпадает с самостоятельным префиксом. Пример carry: первая часть−.015968, вторая+.283384096, полный+.267416096. Minute-close DD видит промежуточную просадку−9.815968 в трёхбарном контроле. Intraminute/mark/liquidation DD остаётся отдельным вопросом, что автор и указал.

| Новые опубликованные результаты | Полный PnL | При cash-return77.6% | При100% | Minute-close DD | Fresh2 | Carry2 |
|---|---:|---:|---:|---:|---:|---:|
| BTC.2/.21,q.0012 | **−553.34** | **−377.62** | **−326.90** | −1006.24 | −514.03 | +198.07 |
| XAU.75/.3,q.023 | **+270.76** | **+346.12** | **+367.87** | −640.19 | +109.36 | −34.23 |

Это арифметика предоставленных25строк, не повтор всей10месячной истории: входные минутки этого окна в snapshot не опубликованы. Cash-return условный денежный возврат, funding отсутствует. Старые−568/−391 и XAUcarry−34.07 относятся к прежней модели, новыйBTC−553.34 и XAUcarry−34.23 — к обновлённой. Вывод о положительном ожидании не изменился; причинная old/new атрибуция требует A/B из одинакового начального состояния.

## Сверка35сделок: код стал лучше, доказательство живых денег не предоставлено

Положительное изменение: отдельно сравниваются деньги, fees и qty; интервалы запроса теперь есть. Однако утверждение «ВСЕ trades» имеет границу: [pnl_reconcile.py:24–30](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/research/weex/pnl_reconcile.py#L24) прекращает дробление окна на60с, даже если ответ насыщен100.

Изолированный AST-fetch с fake, соблюдающим inclusive start/end:150fills в одном минутном окне → возвращено100, fees **.10 вместо .15**. Для заявленных35сделок само это условие не установлено; это опровержение полноты общего алгоритма, не доказательство неверной текущей суммы. Нужны более мелкие окна/поддерживаемая пагинация и явный INCOMPLETE на насыщенном минимальном окне. Скрипт также печатает «ЕСТЬ РАСХОЖДЕНИЕ», но не завершает процесс с ненулевым exit — automatic gate по exit0 всё ещё ненадёжен.

Полный реальный журнал/state/statement в репозитории отсутствует. Поэтому $0.0000 по35сделкам остаётся сообщённым результатом автора, а не независимо сверенным результатом этой проверки. Funding и общий equity этот скрипт не проверяют, что ответами корректно признано.

## Следующий приоритет

1. Сохранение stray до cancel; сопровождение всех сторон и strays после смены режима; pending с доказанной полнотой поиска.
2. Долговечные fee cursors, миграция fee_done, полная досверка unresolved fees.
3. Один владелец state/команд и полная торговая сверка с ненулевым exit при ошибке/неполноте.
4. Для торговой политики первым измерением остаются возраст лотов, distance-to-TP, occupied-hours и вклад новых entry при одинаковом старом inventory. Пройденный TP/IOC, refill tickets и side targets по-прежнему отдельные непроверенные экономические эксперименты.

## Доказательства

- [Manifest](C:/bot7/research/weex_review2_20261010/source_manifest.json).
- [Lifecycle выводы](C:/bot7/research/weex_review2_20261010/lifecycle2_findings.md), [пробник](C:/bot7/research/weex_review2_20261010/lifecycle2_repro.py), [результаты](C:/bot7/research/weex_review2_20261010/lifecycle2_results.json).
- [Fills/fees выводы](C:/bot7/research/weex_review2_20261010/fills2_findings.md), [пробник](C:/bot7/research/weex_review2_20261010/fills2_repro.py), [результаты](C:/bot7/research/weex_review2_20261010/fills2_results.json).
- [Risk/commands выводы](C:/bot7/research/weex_review2_20261010/risk_commands2.md), [пробник](C:/bot7/research/weex_review2_20261010/risk_commands2.py), [результаты](C:/bot7/research/weex_review2_20261010/risk_commands2.json).
- [Методологический AST-пробник](C:/bot7/research/weex_review2_20261010/method2_probe.py), [результаты](C:/bot7/research/weex_review2_20261010/method2_results.json).
- [Сборщик запусков](C:/bot7/research/weex_review2_20261010/verify_offline.py), [четыре успешных запуска](C:/bot7/research/weex_review2_20261010/verification/summary.json).

Для GitHub-передачи исходники четырёх пробников и результаты включаются в конец этого пакета. Локальные пути C:/bot7 в них нужно адаптировать к своему checkout; snapshot — исходники закреплённого commit, не живые state.


---

# Приложение: результаты offline-проверок

## lifecycle2_results.json

```json
{
  "commit": "9cc641e8e0c6746eefe1a6e1440a233f1f9041d1",
  "source_sha256": "a9c98ca444c9dd42c0a8b4b4bd551697f5cfd23c5ed6ac580f440c600ccdd249",
  "tests_run": 8,
  "all_reproduced": true,
  "observed": {
    "closed_config_and_atomic_write": {
      "malformed": "ConfigError",
      "wrong_symbol": "ConfigError",
      "old_file_after_failed_replace": {
        "version": "old"
      }
    },
    "closed_corrupt_state": {
      "actual_qty": 0.0012,
      "take_status": "NEW",
      "cancel_calls": 0
    },
    "closed_orphan_adopt_cursor": {
      "actual_qty": 0.0012,
      "tracked_qty": 0.0012000000000000001,
      "terminal_entry_cleared": true
    },
    "closed_stray_terminal_and_cursor": {
      "actual_qty": 0.0012,
      "tracked_qty": 0.0012000000000000001,
      "terminal_strays": 0
    },
    "closed_pending_second_page_missing_id": {
      "tracked_qty": 0.0012,
      "history_pages": [
        0,
        1
      ]
    },
    "partial_pending_page_cap_ttl": {
      "newer_history_orders": 1000,
      "worker_downtime_sec": 86400,
      "requested_pages": [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9
      ],
      "accepted_filled_qty": 0.0012,
      "tracked_qty": 0,
      "new_open_qty": 0.0012,
      "potential_total_qty": 0.0024
    },
    "new_stray_cancel_before_persist_crash": {
      "exchange_orphan_status": "FILLED",
      "actual_qty": 0.0012,
      "tracked_qty": 0.0,
      "durable_strays": 0,
      "protective_takes": 0,
      "history_contains_terminal_order": true,
      "history_searches_after_restart": 0
    },
    "new_live_dry_strays_ignored": {
      "live_book_calls_after_switch": 0,
      "cancel_calls_after_switch": 0,
      "actual_qty_after_late_fill": 0.0012,
      "durable_lot_qty": 0,
      "durable_strays": 1,
      "protective_takes": 0
    }
  }
}
```

## fills2_results.json

```json
{
  "sha": "9cc641e8e0c6746eefe1a6e1440a233f1f9041d1",
  "network_calls": 0,
  "results": {
    "resting_parent_fee_expiry": {
      "order_id": "dry1",
      "first_fee": 0.006387200000000001,
      "expired_while_live": true,
      "recorded_fee_after_next_partial": 0.0191616,
      "actual_cumulative_fee": 0.012774400000000002,
      "overcount": 0.006387199999999999,
      "restart_included": true,
      "repeat_snapshot_stable": true
    },
    "resting_tp_fee_expiry": {
      "first_tp_fee": 0.0064063616,
      "actual_cumulative_tp_fee": 0.0128127232,
      "recorded_tp_fee": 0.0192190848,
      "overcount": 0.0064063616,
      "remaining_qty": "0.0004"
    },
    "upgrade_old_fee_done": {
      "source_state_sha": "65eae029",
      "legacy_fee_done": 0.006387200000000001,
      "new_fee_book_initially_empty": true,
      "recorded": 0.0191616,
      "actual_cumulative": 0.012774400000000002,
      "duplicated_legacy_fee": 0.006387199999999999
    },
    "late_fee_outside_latest_100": {
      "fee_available_within_window": true,
      "newer_trades": 100,
      "client_limit": 100,
      "recorded": 0,
      "actual": 0.0191616,
      "expired_without_resolving_fee": true,
      "qualification": "requires >=100 later symbol trades; not asserted for observed 35-trade live run"
    },
    "orphan_after_recorded_partial": {
      "precondition": "tp_order mapping alone lost after recorded partial",
      "actual_remaining_qty": 0.0008,
      "tracked_remaining_qty": 0.0004,
      "realized_before": 0.11975999999999767,
      "realized_after": 0.23951999999999535,
      "double_accounted_qty": 0.0004,
      "repeat_snapshot_stable": true
    },
    "late_fee_after_hour": {
      "fee_window_seconds": 3600.0,
      "recorded": 0,
      "actual": 0.0191616,
      "missing_book": true,
      "qualification": "specified one-hour reconciliation bound; needs explicit unresolved status beyond it"
    },
    "fixed_controls": {
      "live_partial_qty": "0.0008",
      "repeat_and_restart_no_double": true,
      "external_deficit_removed": 0.0002,
      "remaining_protected_qty": "0.0006"
    },
    "parent_and_reserve_controls": {
      "logical_slots": 1,
      "partial_fragments": 2,
      "repeat_and_restart_stable": true,
      "remaining_original_qty": 0.0008,
      "remaining_order_canceled_after_cap_drop": true
    }
  }
}
```

## risk_commands2.json

```json
{
  "commit": "9cc641e8e0c6746eefe1a6e1440a233f1f9041d1",
  "offline_only": true,
  "temp_root": "C:\\bot7\\research\\weex_review2_20261010\\risk_commands2_q8x4epnq",
  "scenarios": {
    "final_price_new_order_fixed": {
      "desired_usd": 991.98,
      "final_usd": 1000.001,
      "cap": 999.99,
      "placed_entries": 0,
      "blocked": "достигнут потолок позиции"
    },
    "partial_reserve_fixed": {
      "old_orig_qty": 0.0012,
      "filled_qty": 0.0002,
      "old_remainder_usd": 79.84,
      "new_cap": 50,
      "status": "CANCELED"
    },
    "unknown_balance": {
      "0.0": {
        "allowed": false,
        "reason": "стресс-бюджет: баланс неизвестен"
      },
      "-1.0": {
        "allowed": false,
        "reason": "стресс-бюджет: баланс неизвестен"
      },
      "initial_exception": {
        "allowed": false,
        "reason": "стресс-бюджет: баланс неизвестен"
      },
      "expired_cache_then_exception": {
        "allowed": true,
        "cached_equity": 1000.0,
        "age_sec": 61.0
      }
    },
    "sigma_per_symbol_fixed": {
      "values": {
        "BTCUSDT": 0.01,
        "ETHUSDT": 0.02,
        "XAUUSDT": 0.03
      },
      "fetch_calls": [
        "BTCUSDT",
        "ETHUSDT",
        "XAUUSDT"
      ]
    },
    "excluded_side_entry_executes_untracked": {
      "configured_sides": [
        "SHORT"
      ],
      "enabled": false,
      "old_long_after_disable": "NEW",
      "old_long_after_price_cross": "FILLED",
      "actual_long_qty": 0.0012,
      "virtual_long_qty": 0.0,
      "long_tp_count": 0
    },
    "acknowledged_start_race_still_matters_with_stop_zero": {
      "command_ack": "▶️ Сетка WEEX BTCUSDT включена (ЖИВАЯ).",
      "state_halted_after_command": false,
      "daily_loss_stop_usd": 0.0,
      "enabled_after_command": true,
      "halted_after_worker_save": true,
      "halted_after_next_tick": true,
      "entry_count_after_next_tick": 0,
      "blocked": "стоп: prior day stop"
    },
    "existing_unfilled_entry_above_reduced_cap_kept": {
      "desired_price": 99960.0,
      "desired_notional": 119.95199999999998,
      "standing_price": 100000.0,
      "standing_notional": 119.99999999999999,
      "cap": 119.97,
      "standing_status": "NEW",
      "price_difference_pct": 0.040016006402561026,
      "trail_tolerance_pct": 0.05
    },
    "conditional_concurrent_set_overwrites_stop": {
      "stop_ack": "⏸ Сетка WEEX BTCUSDT: новые входы сняты, тейки остаются — позиция закроется сама.",
      "enabled_immediately_after_stop": false,
      "set_ack": "✅ Сетка WEEX BTCUSDT: шаг 0.2%, цель 0.3%, ордер 0.0010 BTC (≈$100). Потолок $1,000 на сторону → до 10 ордеров; стоп дня ВЫКЛ; стресс-бюджет ВЫКЛ.\nДействует на новые ордера; уже стоящие тейки остаются на старой цели.",
      "enabled_after_set_finishes": true,
      "dispatch_concurrency_not_yet_verified": true
    },
    "fee_query_burst_optimization": {
      "user_trades": 101,
      "order_info": 100,
      "fills": 100,
      "user_trades_endpoint_weight": 5,
      "weight_user_trades_only": 505,
      "real_429_or_actual_latency_not_demonstrated": true
    }
  }
}
```

## method2_results.json

```json
{
  "cut_boundary_fixed": {
    "prefix_pnl": -0.015968,
    "first_carry": -0.015968,
    "second_carry": 0.2833840959999914,
    "full_pnl": 0.26741609599999144
  },
  "minute_close_dd_fixed": {
    "dd": -9.815967999999998,
    "final_pnl": 0.18403200000000283
  },
  "reconcile_full_fetch_still_truncates": {
    "actual_trades": 150,
    "returned_trades": 100,
    "calls": [
      [
        0,
        120000
      ],
      [
        0,
        60000
      ],
      [
        60001,
        120000
      ]
    ],
    "actual_fee": 0.1500000000000001,
    "returned_fee": 0.10000000000000007,
    "condition": "150 fills within 60 seconds; fake respects inclusive time filters and limit100",
    "live_occurrence_not_established": true
  },
  "published_rows_arithmetic_checked": 25,
  "new_numbers": [
    {
      "symbol": "BTC",
      "итог": -553.3368800953522,
      "закрыто": 1478.907972181476,
      "комиссии": 226.44032737365808,
      "мешок": -1805.8045249031702,
      "просадка капитала": -1006.2402122253479,
      "h2": -514.03,
      "2-я часть непрерывно": 198.06616408449008,
      "rebate_77_6": -377.6191860533935,
      "rebate_100": -326.8965527216941
    },
    {
      "symbol": "XAU",
      "итог": 270.76259832906317,
      "закрыто": 903.4437574033009,
      "комиссии": 97.10413216637498,
      "мешок": -535.5770269078628,
      "просадка капитала": -640.1933519031683,
      "h2": 109.36,
      "2-я часть непрерывно": -34.225736892525276,
      "rebate_77_6": 346.11540489017017,
      "rebate_100": 367.86673049543816
    }
  ]
}
```


---

# Приложение: пробники исходного кода

Пути C:/bot7 адаптировать к своему checkout. snapshot — код9cc641e8; для migration-контроля fills2 требуется также прежний snapshot65eae029. Исходные минутки не требуются для этих малых пробников. pnl_reconcile извлекается через AST; запускать живой скрипт для этих проверок не нужно.

## lifecycle2_repro.py

```python
"""Offline review of frozen 9cc641e; counterexamples assert observed failures.

No WeexClient import/initialization, no keys, network, .env, production mutation.
State, configs and journals exist only in temporary workspace directories.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "snapshot"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SNAPSHOT))
from services.weex_grid import engine as eg, loop as lp
eg.logger.disabled = True
lp.logger.disabled = True
OBS = {}


class Clock:
    def __init__(self): self.t = 1_800_000_000.0
    def __call__(self): return self.t
    def advance(self, seconds=10): self.t += seconds


class ProcessLost(BaseException): pass


def order(cid, qty="0.0012", price="99000", status="NEW", filled="0", reduce=False):
    return dict(clientOrderId=cid, side="SELL" if reduce else "BUY", positionSide="LONG",
                price=price, origQty=qty, status=status, executedQty=filled,
                avgPrice=price if float(filled) else "0", reduceOnly=reduce)


class Fake(eg.DryExchange):
    def __init__(self):
        self.mid = 100_000.0
        super().__init__(lambda: (self.mid-.05, self.mid+.05))
        self.cancel_mode = "immediate"
        self.history_calls = []
        self.cancel_calls = []
        self.book_calls = 0
        self.lose_reply = False
        self.no_id = False
        self.crash_cancel_id = None
        self.delay_cancel_ids = set()

    def book(self, symbol):
        # Static snapshots: traces explicitly inject exchange fills.
        self.book_calls += 1
        return self.mid-.05, self.mid+.05

    def open_orders(self, symbol):
        return [{"orderId": k, **o} for k, o in self.orders.items() if o["status"] in eg.LIVE]

    def cancel(self, oid):
        self.cancel_calls.append(str(oid))
        o = self.orders[str(oid)]
        if oid == self.crash_cancel_id:
            # Exchange fill races cancellation; process dies before cancel returns.
            o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
            raise ProcessLost("Process killed during cancel HTTP response")
        if self.cancel_mode == "reject":
            return {"success": False, "orderId": oid}
        if self.cancel_mode == "delayed" or str(oid) in self.delay_cancel_ids:
            if o["status"] in eg.LIVE: o["status"] = "CANCELING"
        elif o["status"] in eg.LIVE:
            o["status"] = "CANCELED"
        return {"success": True, "orderId": oid}

    def actual_qty(self):
        return sum(float(o.get("executedQty") or 0) * (-1 if o["reduceOnly"] else 1)
                   for o in self.orders.values() if o["positionSide"] == "LONG")

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        self.history_calls.append(dict(page=page, limit=limit, start_ms=start_ms, end_ms=end_ms))
        return super().order_history(symbol, limit, page, start_ms, end_ms)

    def place_limit(self, *args, **kwargs):
        r = super().place_limit(*args, **kwargs)
        if not r.get("orderId"): return r
        if self.lose_reply or self.no_id:
            o = self.orders[r["orderId"]]
            o.update(status="FILLED", executedQty=o["origQty"], avgPrice=o["price"])
            if self.lose_reply:
                self.lose_reply = False
                raise TimeoutError("Exchange accepted; response lost")
            self.no_id = False
            return {"success": True, "clientOrderId": o["clientOrderId"]}
        return r


class LifecycleReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lifecycle2_", dir=HERE)
        self.root = Path(self.temp.name)
        self.ex = Fake()
        self.clock = Clock()
        self.cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False, "sides": ["LONG"],
                    "order_qty": "0.0012", "daily_loss_stop_usd": 0., "stress_budget_frac": 0.,
                    "max_notional_usd": 4000.}
        self.g = self.restart()

    def tearDown(self): self.temp.cleanup()

    def restart(self):
        return eg.Grid(self.ex, self.cfg.copy(), state_path=self.root/"st.json",
                       journal_path=self.root/"j.jsonl", now_fn=self.clock)

    def tracked_qty(self): return sum(float(l["qty"]) for l in self.g.st["LONG"]["lots"])
    def open_entries(self):
        return [o for o in self.ex.open_orders("BTCUSDT")
                if not o["reduceOnly"] and o["clientOrderId"].startswith("b7g")]

    def test_01_config_fail_closed_and_atomic_failure_keeps_old_file(self):
        cfgp = self.root/"xau.json"
        cfgp.write_text('{"symbol":"XAUUSDT",', encoding="utf8")
        with self.assertRaises(eg.ConfigError): eg.load_config(cfgp, eg.TEMPLATES["XAU"])
        cfgp.write_text('{"symbol":"BTCUSDT"}', encoding="utf8")
        with self.assertRaises(eg.ConfigError): eg.load_config(cfgp, eg.TEMPLATES["XAU"])
        old = '{"version":"old"}'
        cfgp.write_text(old, encoding="utf8")
        with patch.object(eg.os, "replace", side_effect=OSError("injected pre-replace failure")):
            with self.assertRaises(OSError): eg.atomic_write(cfgp, '{"version":"new"}')
        self.assertEqual(cfgp.read_text(encoding="utf8"), old)
        self.assertFalse(list(self.root.glob(".xau.json.*.tmp")))
        OBS["closed_config_and_atomic_write"] = {"malformed": "ConfigError", "wrong_symbol": "ConfigError",
                                                  "old_file_after_failed_replace": json.loads(old)}

    def test_02_state_corruption_preserves_real_protection(self):
        self.ex.orders["filled"] = order("b7gBLeold", status="FILLED", filled="0.0012")
        self.ex.orders["tp"] = order("b7gBLtold", reduce=True, price="99300")
        (self.root/"st.json").write_text('{', encoding="utf8")
        with self.assertRaises(eg.StateCorrupt): self.restart()
        self.assertEqual(self.ex.orders["tp"]["status"], "NEW")
        self.assertEqual(self.ex.cancel_calls, [])
        OBS["closed_corrupt_state"] = {"actual_qty": self.ex.actual_qty(), "take_status": "NEW", "cancel_calls": 0}

    def test_03_adopted_orphan_partial_is_idempotent_until_cancel_terminal(self):
        self.g.cfg["enabled"] = False
        self.ex.orders["orphan"] = order("b7gBLeold", filled="0.0004")
        self.ex.cancel_mode = "delayed"
        self.g.tick()
        self.g = self.restart()
        self.g.cfg["enabled"] = False
        self.clock.advance()
        self.g.tick()
        self.assertAlmostEqual(self.tracked_qty(), .0004)
        self.assertEqual(self.g.st["LONG"]["entry"]["id"], "orphan")
        self.ex.orders["orphan"].update(status="FILLED", executedQty="0.0012", avgPrice="99000")
        self.clock.advance()
        self.g.tick()
        self.assertAlmostEqual(self.tracked_qty(), .0012)
        self.assertIsNone(self.g.st["LONG"]["entry"])
        OBS["closed_orphan_adopt_cursor"] = {"actual_qty": self.ex.actual_qty(), "tracked_qty": self.tracked_qty(),
                                             "terminal_entry_cleared": True}

    def test_04_busy_side_stray_blocks_new_entry_until_late_fill_reconciled(self):
        self.g.tick()
        active = self.g.st["LONG"]["entry"]["id"]
        self.ex.orders["orphan"] = order("b7gBLeextra", filled="0.0004")
        self.ex.cancel_mode = "delayed"
        self.g.tick()
        self.assertEqual(len(self.g.st["LONG"]["strays"]), 1)
        self.assertEqual(self.g.st["LONG"]["entry"]["id"], active)
        self.assertAlmostEqual(self.tracked_qty(), .0004)
        self.g = self.restart()
        self.clock.advance()
        self.g.tick()
        self.assertAlmostEqual(self.tracked_qty(), .0004)
        self.ex.orders["orphan"].update(status="FILLED", executedQty="0.0012", avgPrice="99000")
        self.clock.advance()
        self.g.tick()
        self.assertAlmostEqual(self.tracked_qty(), .0012)
        self.assertEqual(self.g.st["LONG"]["strays"], [])
        OBS["closed_stray_terminal_and_cursor"] = {"actual_qty": self.ex.actual_qty(), "tracked_qty": self.tracked_qty(),
                                                   "terminal_strays": 0}

    def test_05_pending_on_page_two_and_success_missing_id_are_recovered(self):
        self.ex.no_id = True
        self.g.tick()
        self.assertIsNotNone(self.g.st["LONG"]["pending"])
        for i in range(150): self.ex.orders[f"m{i}"] = order(f"manual{i}", status="CANCELED")
        self.clock.advance()
        self.g.tick()
        self.assertAlmostEqual(self.tracked_qty(), .0012)
        self.assertIsNone(self.g.st["LONG"]["pending"])
        self.assertEqual([x["page"] for x in self.ex.history_calls], [0, 1])
        OBS["closed_pending_second_page_missing_id"] = {"tracked_qty": self.tracked_qty(), "history_pages": [0, 1]}

    def test_06_pending_on_page_eleven_is_forgotten_at_ttl(self):
        self.ex.lose_reply = True
        self.g.tick()
        lost_cid = self.g.st["LONG"]["pending"]["cid"]
        for i in range(1000): self.ex.orders[f"m{i}"] = order(f"manual{i}", status="CANCELED")
        self.clock.advance(24 * 3600)  # Worker was down a day; all later orders lie in its search window.
        self.g.tick()
        self.assertEqual(len(self.ex.history_calls), 10)
        self.assertIsNone(self.g.st["LONG"]["pending"])
        self.assertEqual(self.tracked_qty(), 0.)
        self.assertAlmostEqual(self.ex.actual_qty(), .0012)
        self.assertEqual(len(self.open_entries()), 1)
        # A replacement entry has meanwhile shifted the accepted fill by one row.
        self.assertTrue(any(o["clientOrderId"] == lost_cid for o in self.ex.order_history("BTCUSDT", page=10)))
        OBS["partial_pending_page_cap_ttl"] = {"newer_history_orders": 1000, "worker_downtime_sec": 86400,
            "requested_pages": list(range(10)),
            "accepted_filled_qty": self.ex.actual_qty(), "tracked_qty": self.tracked_qty(),
            "new_open_qty": float(self.open_entries()[0]["origQty"]), "potential_total_qty": .0024}

    def test_07_cancel_orphan_before_persist_crash_loses_terminal_fill(self):
        self.g.tick()
        self.ex.orders["orphan"] = order("b7gBLecrash", price="99000")
        self.ex.crash_cancel_id = "orphan"
        with self.assertRaises(ProcessLost): self.g.tick()
        durable = json.loads((self.root/"st.json").read_text(encoding="utf8"))
        self.assertEqual(durable["LONG"]["strays"], [])
        self.ex.crash_cancel_id = None
        self.g = self.restart()
        self.clock.advance()
        self.g.tick()
        self.assertAlmostEqual(self.ex.actual_qty(), .0012)
        self.assertEqual(self.tracked_qty(), 0.)
        self.assertFalse(any(o["reduceOnly"] for o in self.ex.open_orders("BTCUSDT")))
        OBS["new_stray_cancel_before_persist_crash"] = {"exchange_orphan_status": "FILLED", "actual_qty": .0012,
            "tracked_qty": 0., "durable_strays": 0, "protective_takes": 0,
            "history_contains_terminal_order": True, "history_searches_after_restart": len(self.ex.history_calls)}

    def test_08_live_to_dry_skips_state_having_only_canceling_stray(self):
        # Generate the strays-only durable state through the real recovery flow:
        # ordinary entry cancels immediately, extra orphan cancel remains pending.
        self.g.tick()
        self.ex.orders["orphan"] = order("b7gBLestray")
        self.ex.delay_cancel_ids.add("orphan")
        self.g.cfg["enabled"] = False
        self.g.tick()
        self.assertIsNone(self.g.st["LONG"]["entry"])
        self.assertEqual(self.g.st["LONG"]["lots"], [])
        self.assertEqual(len(self.g.st["LONG"]["strays"]), 1)
        books_before = self.ex.book_calls
        cancels_before = len(self.ex.cancel_calls)
        cfgp = self.root/"cfg.json"
        cfg = {**self.cfg, "dry_run": True, "enabled": False}
        eg.save_config(cfg, cfgp)
        r = lp.Runner()
        r._client = lambda: self.ex
        files = (cfgp, self.root/"st.json", self.root/"j.jsonl")
        with patch.object(lp, "grid_config", return_value=cfg), patch.object(lp, "run_files", return_value=files[1:]):
            r.tick_one("BTC")
            # Live orphan executes after switch; another dry tick still never reads it.
            self.ex.orders["orphan"].update(status="FILLED", executedQty="0.0012", avgPrice="99000")
            r.tick_one("BTC")
        durable = json.loads((self.root/"st.json").read_text(encoding="utf8"))
        self.assertEqual(self.ex.book_calls, books_before)
        self.assertEqual(len(self.ex.cancel_calls), cancels_before)
        self.assertEqual(durable["LONG"]["lots"], [])
        self.assertAlmostEqual(self.ex.actual_qty(), .0012)
        OBS["new_live_dry_strays_ignored"] = {"live_book_calls_after_switch": 0, "cancel_calls_after_switch": 0,
            "actual_qty_after_late_fill": self.ex.actual_qty(), "durable_lot_qty": 0,
            "durable_strays": len(durable["LONG"]["strays"]), "protective_takes": 0}


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LifecycleReview)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    payload = {"commit": "9cc641e8e0c6746eefe1a6e1440a233f1f9041d1",
               "source_sha256": hashlib.sha256((SNAPSHOT/"services/weex_grid/engine.py").read_bytes()).hexdigest(),
               "tests_run": result.testsRun, "all_reproduced": result.wasSuccessful(), "observed": OBS}
    (HERE/"lifecycle2_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)

```

## fills2_repro.py

```python
"""Offline fill/fee reproductions against pinned sha 9cc641e8.

No live client construction; no credentials; HTTP explicitly forbidden.
Snapshot source is imported without bytecode or mutation.
"""
from __future__ import annotations
import importlib.util
import json
import logging
from pathlib import Path
import socket
import sys
import tempfile
import types
import urllib.request

sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
BASE = Path(__file__).resolve().parent
SNAPSHOT = BASE / 'snapshot'

def forbidden(*a, **k):
    raise AssertionError('Network forbidden in offline replay')
urllib.request.urlopen = forbidden
socket.create_connection = forbidden
logging.basicConfig(level=logging.CRITICAL)
for name, path in [('services', SNAPSHOT / 'services'), ('services.weex_grid', SNAPSHOT / 'services/weex_grid')]:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
spec = importlib.util.spec_from_file_location('services.weex_grid.engine', SNAPSHOT / 'services/weex_grid/engine.py')
eg = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = eg
spec.loader.exec_module(eg)

class Exchange(eg.DryExchange):
    def __init__(self):
        self.mid = 100_000.0
        super().__init__(lambda: (self.mid - .05, self.mid + .05))
        self.reject_once = False
        self.position_override = None
        self.hide_fees = False
    def book(self, symbol):
        return self.mid - .05, self.mid + .05
    def open_orders(self, symbol):
        return [{'orderId': k, **v} for k, v in self.orders.items() if v['status'] in eg.LIVE]
    def place_limit(self, *a, **k):
        if k.get('reduce_only') and self.reject_once:
            self.reject_once = False
            return {'success': False, 'orderId': None}
        return super().place_limit(*a, **k)
    def user_trades(self, symbol, order_id=None):
        if self.hide_fees:
            return []
        return super().user_trades(symbol, order_id)
    def fill(self, oid, q, status='NEW'):
        o = self.orders[oid]
        o.update(executedQty=str(q), avgPrice=o['price'], status=status)
        self.trades[oid] = [{'orderId': oid, 'id': 'cumulative-'+oid, 'qty': str(q), 'price': o['price'],
                             'commission': str(q*float(o['price'])*self.maker_fee), 'maker': True}]
    def futures_positions(self):
        if self.position_override is not None:
            return [{'symbol': self.symbol, 'side': 'LONG', 'size': str(self.position_override)}]
        return super().futures_positions()

def grid(folder, ex, clock, enabled=True):
    cfg = {**eg.DEFAULT, 'enabled': enabled, 'dry_run': False, 'sides': ['LONG'], 'order_qty': '0.0012',
           'stress_budget_frac': 0, 'daily_loss_stop_usd': 0, 'max_notional_usd': 1e6}
    return eg.Grid(ex, cfg, state_path=folder/'state.json', journal_path=folder/'journal.jsonl', now_fn=lambda: clock['t'])

def opened(folder):
    ex, clock = Exchange(), {'t': 1_800_000_000.0}
    g = grid(folder, ex, clock)
    g.tick()
    entry = g.st['LONG']['entry']['id']
    ex.fill(entry, .0012, 'FILLED')
    g.cfg['enabled'] = False
    g.tick()
    lot = g.st['LONG']['lots'][0]
    return g, ex, clock, entry, lot

def resting_parent_fee_expiry(folder):
    ex, clock = Exchange(), {'t': 1_800_000_000.0}
    g = grid(folder, ex, clock)
    g.tick()
    oid = g.st['LONG']['entry']['id']
    ex.fill(oid, .0004)
    g.tick()
    first_fee = g.st['LONG']['fees']
    assert abs(first_fee - .0063872) < 1e-10
    clock['t'] += 3601
    g.tick()
    assert oid not in g.st['LONG']['fee_book']
    assert g.st['LONG']['entry']['id'] == oid
    # Restart after expiry; the cumulative order still rests and fills another part.
    g = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=lambda: clock['t'])
    ex.fill(oid, .0008)
    g.tick()
    actual = sum(float(t['commission']) for t in ex.trades[oid])
    recorded = g.st['LONG']['fees']
    assert abs(recorded - .0191616) < 1e-10
    assert abs(actual - .0127744) < 1e-10
    assert abs(recorded - actual - first_fee) < 1e-10
    before = recorded
    g.tick()
    assert g.st['LONG']['fees'] == before
    return {'order_id': oid, 'first_fee': first_fee, 'expired_while_live': True,
            'recorded_fee_after_next_partial': recorded, 'actual_cumulative_fee': actual,
            'overcount': recorded-actual, 'restart_included': True, 'repeat_snapshot_stable': True}

def resting_tp_fee_expiry(folder):
    g, ex, clock, entry, lot = opened(folder)
    oid = lot['tp_order']['id']
    entry_fee = g.st['LONG']['fees']
    ex.fill(oid, .0004)
    g.tick()
    first = g.st['LONG']['fees'] - entry_fee
    clock['t'] += 3601
    g.tick()
    assert oid not in g.st['LONG']['fee_book']
    ex.fill(oid, .0008)
    g.tick()
    actual = sum(float(t['commission']) for t in ex.trades[oid])
    recorded = g.st['LONG']['fees'] - entry_fee
    assert abs(recorded - actual - first) < 1e-10
    assert g.st['LONG']['lots'][0]['qty'] == '0.0004'
    return {'first_tp_fee': first, 'actual_cumulative_tp_fee': actual, 'recorded_tp_fee': recorded,
            'overcount': recorded-actual, 'remaining_qty': g.st['LONG']['lots'][0]['qty']}

def upgrade_old_fee_done(folder):
    old_path = BASE.parent/'weex_code_review_20261010/snapshot/services/weex_grid/engine.py'
    spec = importlib.util.spec_from_file_location('weex_old_65eae029', old_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    ex, clock = Exchange(), {'t': 1_800_000_000.0}
    initial = grid(folder, ex, clock)
    legacy = old.Grid(ex, initial.cfg, state_path=initial.state_path, journal_path=initial.journal_path,
                      now_fn=lambda: clock['t'])
    legacy.tick()
    oid = legacy.st['LONG']['entry']['id']
    ex.fill(oid, .0004)
    legacy.tick()
    cursor = legacy.st['LONG']['entry']['fee_done']
    assert abs(cursor-.0063872) < 1e-10
    upgraded = eg.Grid(ex, legacy.cfg, state_path=legacy.state_path, journal_path=legacy.journal_path,
                       now_fn=lambda: clock['t'])
    assert not upgraded.st['LONG']['fee_book']
    ex.fill(oid, .0008)
    upgraded.tick()
    recorded = upgraded.st['LONG']['fees']
    actual = sum(float(t['commission']) for t in ex.trades[oid])
    assert abs(recorded - actual - cursor) < 1e-10
    return {'source_state_sha': '65eae029', 'legacy_fee_done': cursor,
            'new_fee_book_initially_empty': True, 'recorded': recorded,
            'actual_cumulative': actual, 'duplicated_legacy_fee': recorded-actual}

def late_fee_outside_latest_100(folder):
    ex, clock = Exchange(), {'t': 1_800_000_000.0}
    g = grid(folder, ex, clock)
    g.tick()
    oid = g.st['LONG']['entry']['id']
    ex.fill(oid, .0012, 'FILLED')
    actual = sum(float(t['commission']) for t in ex.trades[oid])
    ex.hide_fees = True
    g.cfg['enabled'] = False
    g.tick()
    ex.hide_fees = False
    for i in range(100):
        ex.trades['later_'+str(i)] = [{'orderId': 'later_'+str(i), 'commission': '0.01', 'maker': True}]
    original = ex.user_trades
    # Transport-equivalent response bound in WeexClient.user_trades(limit=100).
    ex.user_trades = lambda symbol, order_id=None: original(symbol, order_id)[-100:]
    clock['t'] += 60
    g.tick()
    assert g.st['LONG']['fees'] == 0
    assert oid in g.st['LONG']['fee_book']
    clock['t'] += 3601
    g.tick()
    assert oid not in g.st['LONG']['fee_book']
    assert g.st['LONG']['fees'] == 0
    return {'fee_available_within_window': True, 'newer_trades': 100, 'client_limit': 100,
            'recorded': 0, 'actual': actual, 'expired_without_resolving_fee': True,
            'qualification': 'requires >=100 later symbol trades; not asserted for observed 35-trade live run'}

def orphan_after_recorded_partial(folder):
    g, ex, clock, entry, lot = opened(folder)
    oid = lot['tp_order']['id']
    ex.fill(oid, .0004)
    g.tick()
    realized_before = g.st['LONG']['realized']
    assert lot['qty'] == '0.0008'
    # Explicit precondition: mapping only is lost, after its partial fill was already recorded.
    # This is NOT presented as a spontaneous failure of atomic state save.
    lot['tp_order'] = None
    g.save()
    g = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=lambda: clock['t'])
    g.tick()
    qty = sum(float(l['qty']) for l in g.st['LONG']['lots'])
    actual = float(ex.futures_positions()[0]['size'])
    realized_after = g.st['LONG']['realized']
    assert abs(qty - .0004) < 1e-12
    assert abs(actual - .0008) < 1e-12
    assert abs(realized_after - 2*realized_before) < 1e-10
    g.tick()
    assert sum(float(l['qty']) for l in g.st['LONG']['lots']) == qty
    return {'precondition': 'tp_order mapping alone lost after recorded partial', 'actual_remaining_qty': actual,
            'tracked_remaining_qty': qty, 'realized_before': realized_before, 'realized_after': realized_after,
            'double_accounted_qty': .0004, 'repeat_snapshot_stable': True}

def late_fee_after_hour(folder):
    ex, clock = Exchange(), {'t': 1_800_000_000.0}
    g = grid(folder, ex, clock)
    g.tick()
    oid = g.st['LONG']['entry']['id']
    ex.fill(oid, .0012, 'FILLED')
    ex.hide_fees = True
    g.cfg['enabled'] = False
    g.tick()
    clock['t'] += 3601
    g.tick()
    assert oid not in g.st['LONG']['fee_book']
    ex.hide_fees = False
    clock['t'] += 60
    g.tick()
    assert g.st['LONG']['fees'] == 0
    return {'fee_window_seconds': eg.FEE_WINDOW, 'recorded': 0,
            'actual': sum(float(t['commission']) for t in ex.trades[oid]), 'missing_book': True,
            'qualification': 'specified one-hour reconciliation bound; needs explicit unresolved status beyond it'}

def fixed_controls(folder):
    g, ex, clock, entry, lot = opened(folder)
    oid = lot['tp_order']['id']
    ex.fill(oid, .0004)
    g.tick()
    q, realized = lot['qty'], g.st['LONG']['realized']
    assert q == '0.0008'
    g = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=lambda: clock['t'])
    g.tick()
    assert g.st['LONG']['lots'][0]['qty'] == q
    assert g.st['LONG']['realized'] == realized
    ex.orders[oid]['status'] = 'CANCELED'
    ex.position_override = .0006
    ex.reject_once = True
    g.tick()
    assert g.st['LONG']['lots'][0]['qty'] == '0.0006'
    g.tick()
    take = ex.orders[g.st['LONG']['lots'][0]['tp_order']['id']]
    assert take['origQty'] == '0.0006'
    return {'live_partial_qty': q, 'repeat_and_restart_no_double': True, 'external_deficit_removed': .0002,
            'remaining_protected_qty': take['origQty']}

def parent_and_reserve_controls(folder):
    ex, clock = Exchange(), {'t': 1_800_000_000.0}
    ex.mid = 80_000.0
    g = grid(folder, ex, clock)
    g.cfg.update(max_lots_per_side=1, max_notional_usd=200.0)
    g.tick()
    oid = g.st['LONG']['entry']['id']
    ex.fill(oid, .0002)
    g.tick()
    ex.fill(oid, .0004)
    g.tick()
    assert len(g.st['LONG']['lots']) == 2
    assert g._slots('LONG') == 1
    assert g.st['LONG']['entry']['id'] == oid
    g = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=lambda: clock['t'])
    g.tick()
    assert len(g.st['LONG']['lots']) == 2
    g.cfg.update(order_qty='0.0001', max_notional_usd=50)
    g.tick()
    assert ex.orders[oid]['status'] == 'CANCELED'
    assert g.st['LONG']['entry'] is None
    return {'logical_slots': 1, 'partial_fragments': 2, 'repeat_and_restart_stable': True,
            'remaining_original_qty': .0008, 'remaining_order_canceled_after_cap_drop': True}

def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix='fills2_', dir=BASE) as root:
        for name, fn in [('resting_parent_fee_expiry', resting_parent_fee_expiry),
                         ('resting_tp_fee_expiry', resting_tp_fee_expiry),
                         ('upgrade_old_fee_done', upgrade_old_fee_done),
                         ('late_fee_outside_latest_100', late_fee_outside_latest_100),
                         ('orphan_after_recorded_partial', orphan_after_recorded_partial),
                         ('late_fee_after_hour', late_fee_after_hour), ('fixed_controls', fixed_controls),
                         ('parent_and_reserve_controls', parent_and_reserve_controls)]:
            folder = Path(root)/name
            folder.mkdir()
            results[name] = fn(folder)
    data = {'sha': '9cc641e8e0c6746eefe1a6e1440a233f1f9041d1', 'network_calls': 0, 'results': results}
    (BASE/'fills2_results.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False, indent=2))
if __name__ == '__main__':
    main()

```

## risk_commands2.py

```python
"""Offline review of pinned WEEX 9cc641e8. Uses only DryExchange and local temp states.

Assertions reproduce the observed behavior, including bad behavior; a green run is
NOT a claim that the production implementation satisfies all desired invariants.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "snapshot"
sys.path.insert(0, str(SNAPSHOT))
from services.weex_grid import engine as eg
from services.weex_grid import loop as lp

logging.disable(logging.CRITICAL)
RESULTS = {}
RUN_ROOT = Path(tempfile.mkdtemp(prefix="risk_commands2_", dir=ROOT))


class Px:
    def __init__(self, mid=100_000.0):
        self.mid = mid
    def __call__(self):
        return self.mid - .05, self.mid + .05


def make(name, **kw):
    p = RUN_ROOT / name
    p.mkdir()
    px = Px()
    ex = eg.DryExchange(px)
    clock = {"t": 1_800_000_000.0}
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": False,
           "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0,
           "sides": ["LONG"], **kw}
    g = eg.Grid(ex, cfg, p / "state.json", p / "journal.jsonl", now_fn=lambda: clock["t"])
    return g, ex, px, clock, p


def final_price_control():
    g, ex, px, clock, p = make("final_price", sides=["SHORT"], order_qty="0.01", max_notional_usd=999.99)
    g.st["SHORT"]["ref"] = 99_000.0
    g.tick()
    assert not [o for o in ex.orders.values() if not o["reduceOnly"]]
    RESULTS["final_price_new_order_fixed"] = {"desired_usd": 991.98, "final_usd": 1000.001, "cap": 999.99,
                                               "placed_entries": 0, "blocked": g.st["SHORT"]["blocked"]}


def partial_reserve_control():
    g, ex, px, clock, p = make("partial_reserve", order_qty="0.0012", max_notional_usd=200.0)
    px.mid = 80_000
    g.tick()
    oid = g.st["LONG"]["entry"]["id"]
    ex.orders[oid].update(executedQty="0.0002", avgPrice=ex.orders[oid]["price"])
    g.tick()
    g.cfg.update(order_qty="0.0001", max_notional_usd=50.0)
    g.tick()
    assert ex.orders[oid]["status"] == "CANCELED"
    RESULTS["partial_reserve_fixed"] = {"old_orig_qty": .0012, "filled_qty": .0002,
                                       "old_remainder_usd": .001 * 79840,
                                       "new_cap": 50, "status": ex.orders[oid]["status"]}


def unknown_balance_control_and_stale_cache():
    g, ex, px, clock, p = make("balance", stress_budget_frac=.25)
    statuses = {}
    for balance in (0.0, -1.0):
        ex.balance = balance
        g._equity = None
        ok, reason = g.may_add("LONG", 99800, 100000)
        assert not ok
        statuses[str(balance)] = {"allowed": ok, "reason": reason}
    def fail():
        raise TimeoutError("offline balance unavailable")
    original = ex.futures_balance
    ex.futures_balance = fail
    g._equity = None
    ok, reason = g.may_add("LONG", 99800, 100000)
    assert not ok
    statuses["initial_exception"] = {"allowed": ok, "reason": reason}
    ex.futures_balance = original
    ex.balance = 1000
    assert g.may_add("LONG", 99800, 100000)[0]
    clock["t"] += 61
    ex.futures_balance = fail
    ok, reason = g.may_add("LONG", 99800, 100000)
    assert ok and g._equity == 1000
    statuses["expired_cache_then_exception"] = {"allowed": ok, "cached_equity": g._equity,
                                               "age_sec": clock["t"] - g._equity_ts}
    RESULTS["unknown_balance"] = statuses


def sigma_control():
    calls = []
    mod = types.ModuleType("services.grid_model.stress_budget")
    values = {"BTCUSDT": .01, "ETHUSDT": .02, "XAUUSDT": .03}
    def fake_sigma(symbol):
        calls.append(symbol)
        return values[symbol]
    mod.sigma24 = fake_sigma
    pkg = types.ModuleType("services.grid_model")
    pkg.__path__ = []
    with patch.dict(sys.modules, {"services.grid_model": pkg, "services.grid_model.stress_budget": mod}), \
         patch.object(lp, "_SIGMA", {}), patch.object(lp.time, "time", lambda: 1800000000.):
        got = {symbol: lp.sigma24(symbol) for symbol in values}
        for symbol in values:
            assert lp.sigma24(symbol) == values[symbol]
    assert calls == list(values)
    RESULTS["sigma_per_symbol_fixed"] = {"values": got, "fetch_calls": calls}


def excluded_side_not_reconciled():
    g, ex, px, clock, p = make("excluded_side", sides=["LONG", "SHORT"], order_qty="0.0012")
    g.tick()
    old_long = g.st["LONG"]["entry"]["id"]
    g.cfg.update(sides=["SHORT"], enabled=False)
    g.tick()
    assert ex.orders[old_long]["status"] == "NEW"
    px.mid = 99790
    g.tick()
    assert ex.orders[old_long]["status"] == "FILLED"
    actual = next(float(x["size"]) for x in ex.futures_positions() if x["side"] == "LONG")
    assert actual == .0012 and not g.st["LONG"]["lots"]
    long_tp = [o for o in ex.orders.values() if o["positionSide"] == "LONG" and o["reduceOnly"]]
    assert not long_tp
    RESULTS["excluded_side_entry_executes_untracked"] = {
        "configured_sides": g.cfg["sides"], "enabled": False,
        "old_long_after_disable": "NEW", "old_long_after_price_cross": "FILLED",
        "actual_long_qty": actual, "virtual_long_qty": 0.0, "long_tp_count": 0,
    }


def start_lost_despite_stop_zero():
    g, ex, px, clock, p = make("halted_race", enabled=False)
    cfg_path = p / "config.json"
    cfg_path.write_text(json.dumps(g.cfg), encoding="utf-8")
    g.st.update(halted=True, halt_reason="prior day stop")
    g.save()
    g = eg.Grid(ex, g.cfg, p / "state.json", p / "journal.jsonl", now_fn=lambda: clock["t"])
    original_book = ex.book
    got = {}
    def hook_book(symbol):
        got["command_ack"] = lp.command("start")
        got["state_halted_after_command"] = json.loads((p / "state.json").read_text())["halted"]
        ex.book = original_book
        return original_book(symbol)
    with patch.object(lp, "grid_config", lambda name="BTC": eg.load_config(cfg_path)), \
         patch.object(lp, "save_grid_config", lambda cfg, name="BTC": eg.save_config(cfg, cfg_path)), \
         patch.object(lp, "run_files", lambda name, dry: (p / ("dry_state.json" if dry else "state.json"), p / "journal.jsonl")):
        ex.book = hook_book
        g.tick()
        state_after = json.loads((p / "state.json").read_text())
        new_cfg = eg.load_config(cfg_path)
        g2 = eg.Grid(ex, new_cfg, p / "state.json", p / "journal.jsonl", now_fn=lambda: clock["t"])
        g2.tick()
    assert got["state_halted_after_command"] is False
    assert state_after["halted"] and g2.st["halted"] and new_cfg["enabled"]
    assert not [o for o in ex.orders.values() if not o["reduceOnly"]]
    RESULTS["acknowledged_start_race_still_matters_with_stop_zero"] = {
        **got, "daily_loss_stop_usd": 0.0, "enabled_after_command": new_cfg["enabled"],
        "halted_after_worker_save": state_after["halted"],
        "halted_after_next_tick": g2.st["halted"], "entry_count_after_next_tick": 0,
        "blocked": g2.st["LONG"]["blocked"],
    }


def existing_entry_cap_not_rechecked_at_its_price():
    g, ex, px, clock, p = make("existing_entry_cap", order_qty="0.0012", max_notional_usd=200.0)
    old_price = 100000.
    desired = 99960.
    px.mid = 100001.
    r = ex.place_limit("BTCUSDT", "BUY", "LONG", ".0012", "100000.0", "b7gBLEmanual")
    oid = str(r["orderId"])
    g.st["LONG"].update(ref=desired / .998,
                        entry={"id": oid, "cid": "b7gBLEmanual", "qty": ".0012", "price": old_price})
    g.cfg["max_notional_usd"] = 119.97
    g.tick()
    assert ex.orders[oid]["status"] == "NEW" and g.st["LONG"]["entry"]["id"] == oid
    assert old_price * .0012 > g.cfg["max_notional_usd"]
    RESULTS["existing_unfilled_entry_above_reduced_cap_kept"] = {
        "desired_price": desired, "desired_notional": desired * .0012,
        "standing_price": old_price, "standing_notional": old_price * .0012,
        "cap": g.cfg["max_notional_usd"], "standing_status": ex.orders[oid]["status"],
        "price_difference_pct": (old_price - desired) / desired * 100,
        "trail_tolerance_pct": g.cfg["trail_min_move_pct"],
    }


def concurrent_config_edit_interleaving():
    # This proves an unlocked read-modify-write interleaving, not that the
    # Telegram dispatch layer actually executes two command handlers concurrently.
    g, ex, px, clock, p = make("config_race")
    cfg_path = p / "config.json"
    cfg_path.write_text(json.dumps(g.cfg), encoding="utf-8")
    got = {}
    def delayed_price():
        got["stop_ack"] = lp.command("stop")
        got["enabled_immediately_after_stop"] = json.loads(cfg_path.read_text())["enabled"]
        return 100000.
    with patch.object(lp, "grid_config", lambda name="BTC": eg.load_config(cfg_path)), \
         patch.object(lp, "save_grid_config", lambda cfg, name="BTC": eg.save_config(cfg, cfg_path)):
        got["set_ack"] = lp.set_params("ордер 100", delayed_price)
    final = json.loads(cfg_path.read_text())
    assert got["enabled_immediately_after_stop"] is False and final["enabled"] is True
    RESULTS["conditional_concurrent_set_overwrites_stop"] = {
        **got, "enabled_after_set_finishes": final["enabled"],
        "dispatch_concurrency_not_yet_verified": True,
    }


def fee_request_burst():
    g, ex, px, clock, p = make("fee_burst", sides=["LONG", "SHORT"], enabled=False)
    # 50 tracked closed TPs per side in one snapshot. No network access.
    for side in ("LONG", "SHORT"):
        tp_price = 100300. if side == "LONG" else 99700.
        order_side = "SELL" if side == "LONG" else "BUY"
        for i in range(50):
            oid = f"tp{side}{i}"
            ex.orders[oid] = {"clientOrderId": f"b7gB{side[0]}t{i}", "side": order_side,
                              "positionSide": side, "price": str(tp_price), "origQty": ".0001",
                              "status": "FILLED", "executedQty": ".0001", "avgPrice": str(tp_price),
                              "reduceOnly": True}
            g.st[side]["lots"].append({"entry": 100000., "qty": ".0001", "tp": tp_price,
                                        "tp_order": {"id": oid, "price": tp_price, "qty": ".0001"},
                                        "t": clock["t"] + i, "parent": f"entry{side}{i}"})
    counts = {"user_trades": 0, "order_info": 0}
    old_trades, old_info = ex.user_trades, ex.order_info
    def trades(*args):
        counts["user_trades"] += 1
        return old_trades(*args)
    def info(*args):
        counts["order_info"] += 1
        return old_info(*args)
    ex.user_trades, ex.order_info = trades, info
    g.tick()
    assert counts == {"user_trades": 101, "order_info": 100}
    RESULTS["fee_query_burst_optimization"] = {**counts, "fills": 100,
                                              "user_trades_endpoint_weight": 5,
                                              "weight_user_trades_only": 505,
                                              "real_429_or_actual_latency_not_demonstrated": True}


for scenario in (final_price_control, partial_reserve_control, unknown_balance_control_and_stale_cache,
                 sigma_control, excluded_side_not_reconciled, start_lost_despite_stop_zero,
                 existing_entry_cap_not_rechecked_at_its_price, concurrent_config_edit_interleaving,
                 fee_request_burst):
    scenario()

out = {"commit": "9cc641e8e0c6746eefe1a6e1440a233f1f9041d1", "offline_only": True,
       "temp_root": str(RUN_ROOT), "scenarios": RESULTS}
(ROOT / "risk_commands2.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))

```

## method2_probe.py

```python
"""Offline verification of method fixes and completeness of reconciliation fetch.

The live reconciliation script is NEVER imported or executed: only its fetch() AST
is compiled, with a fake client. Source files and production are unchanged.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SNAP = HERE / "snapshot"
spec = importlib.util.spec_from_file_location("review2_fast_grid", SNAP / "research/weex/fast_grid.py")
fg = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fg
spec.loader.exec_module(fg)


def synthetic(ts, op, hi, lo, cl):
    return (np.array(ts, dtype=np.int64), *(np.array(v, dtype=float) for v in (op, hi, lo, cl)))


def main():
    out = {}
    data = synthetic([0, 60], [100, 100.5], [100, 100.5], [99.79, 100.5], [99.8, 100.5])
    full = fg.run(data, ("LONG",), step=.2, target=.3, order_qty=1, cut_ts=60)
    prefix = fg.run(tuple(x[:1] for x in data), ("LONG",), step=.2, target=.3, order_qty=1)
    assert abs(full["1-я часть непрерывно"] - prefix["итог"]) < 1e-12
    assert abs(full["2-я часть непрерывно"] - (full["итог"] - prefix["итог"])) < 1e-12
    out["cut_boundary_fixed"] = {"prefix_pnl": prefix["итог"], "first_carry": full["1-я часть непрерывно"],
                                 "second_carry": full["2-я часть непрерывно"], "full_pnl": full["итог"]}

    dddata = synthetic([0, 60, 120], [100, 99.7, 100], [100, 99.7, 100], [99.79, 90, 100], [99.8, 90, 100])
    dd = fg.run(dddata, ("LONG",), step=.2, target=100, order_qty=1, max_orders=1)
    assert dd["просадка капитала"] < -9
    out["minute_close_dd_fixed"] = {"dd": dd["просадка капитала"], "final_pnl": dd["итог"]}

    source = (SNAP / "research/weex/pnl_reconcile.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch")
    trades = [{"id": str(i), "time": i, "commission": ".001"} for i in range(150)]

    class Fake:
        def __init__(self):
            self.calls = []

        def user_trades(self, symbol, start_ms=None, end_ms=None):
            self.calls.append([start_ms, end_ms])
            found = [r for r in trades if start_ms <= r["time"] <= end_ms]
            return sorted(found, key=lambda r: -r["time"])[:100]

    fake = Fake()
    namespace = {"c": fake}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "offline_fetch_ast", "exec"), namespace)
    fetched = namespace["fetch"](0, 120000)
    assert len(fetched) == 100 and len(trades) == 150
    out["reconcile_full_fetch_still_truncates"] = {
        "actual_trades": len(trades), "returned_trades": len(fetched), "calls": fake.calls,
        "actual_fee": sum(float(r["commission"]) for r in trades),
        "returned_fee": sum(float(r["commission"]) for r in fetched),
        "condition": "150 fills within 60 seconds; fake respects inclusive time filters and limit100",
        "live_occurrence_not_established": True,
    }

    rows = []
    for pattern in ("sweep_BTCUSDT_both_*.jsonl", "sweep_XAUUSDT_both_*.jsonl"):
        for file in (SNAP / "research/weex").glob(pattern):
            for line in file.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                assert abs(r["итог"] - (r["закрыто"] - r["комиссии"] + r["мешок"])) < 1e-7
                assert abs(r["комиссии"] - r["оборот"] * .00016) < 1e-6
                assert abs(r["1-я часть непрерывно"] + r["2-я часть непрерывно"] - r["итог"]) < 1e-7
                assert abs(r["h1"] - r["1-я часть непрерывно"]) <= .00501
                if ("BTC" in file.name and r["step"] == .2 and r["target"] == .21) or (
                    "XAU" in file.name and r["step"] == .75 and r["target"] == .3):
                    rows.append({"symbol": "BTC" if "BTC" in file.name else "XAU",
                                 **{k: r[k] for k in ("итог", "закрыто", "комиссии", "мешок", "просадка капитала", "h2", "2-я часть непрерывно")},
                                 "rebate_77_6": r["итог"] + .776 * r["комиссии"],
                                 "rebate_100": r["итог"] + r["комиссии"]})
    out["published_rows_arithmetic_checked"] = 25
    out["new_numbers"] = rows
    (HERE / "method2_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"))


if __name__ == "__main__":
    main()

```

## verify_offline.py

```python
"""Run only local fake-client probes, capturing UTF-8 logs. No live script is executed."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "verification"
LOG.mkdir(exist_ok=True)
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
summary = []
for name in ("lifecycle2_repro.py", "fills2_repro.py", "risk_commands2.py", "method2_probe.py"):
    start = time.monotonic()
    r = subprocess.run([sys.executable, str(HERE / name)], cwd=HERE, env=env, capture_output=True, timeout=120)
    (LOG / (name + ".stdout.txt")).write_bytes(r.stdout)
    (LOG / (name + ".stderr.txt")).write_bytes(r.stderr)
    summary.append({"script": name, "exit_code": r.returncode, "seconds": round(time.monotonic() - start, 3)})
(LOG / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
raise SystemExit(0 if all(r["exit_code"] == 0 for r in summary) else 1)

```
