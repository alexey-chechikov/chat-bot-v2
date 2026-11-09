# Funding repair: 09.11.2026

Изменения только в `C:/bot7/tmp/btc-features-repair-20261109`. Исходная audit-копия, живые процессы и экспорт модели не менялись.

## Изменено

- `features.funding_records`: реальные наблюдённые timestamps/ставки, стабильная сортировка и последняя запись дубликата. Нулевая ставка остаётся наблюдением. Невалидная ставка не становится нулём.
- `features.funding_window`: суммы `(t-window, t]` только при полном покрытии. Для BTCUSDT применяется явно заданный expected interval 8h; другой источник/синтетический fixture может задать свой interval. До inception, при пропущенной выплате, внутреннем разрыве или без metadata — NaN. Будущее возобновление не меняет прошлое. Покрытие определяется по реальным records и source contract, не по изменениям F.
- `entry_rules.prep`: новые `funding_records` в a; future records отсекаются по последнему закрытому price time. F строится через asof cumulative payouts, без clip будущего в последний час. Нулевые реальные records сохраняются.
- `trade_table`: `_add_t`, `_add_i`, видимое `добор UTC`, приватные маски покрытия на часе входа. Target path call уже передаёт `exit_mode`, реализуемый следующим repair-этапом. Model export не изменён.
- `basis_check.with_funding`: вторая нога начинается с собственного add clock; отсутствие времени/покрытия даёт NaN. Engine-добор отмечен `_add_before_close`: выплата на закрытии его часа начисляется добору, так как стоящий stop исполнился до закрытия. Выплата на точном первом entry исключается. При выплате строго внутри часа добора порядок неизвестен — NaN. Последующие summaries исключают unknown строки с явным изменением n, без превращения unknown в ноль.
- Synthetic rich fixture получает явные hourly funding records.

## Проверки

Последняя совместная проверка: `python -X utf8 -m pytest -c pytest.ini --confcutdir=. --basetemp=C:/bot7/tmp/btc-funding-path-repair-pytest-1 -q tests/services/btc_signals tests/research_tools/test_features_ext.py tests/research_tools/test_btc_funding_repair.py tests/research_tools/test_btc_path_repair.py` → **63 passed in 3.45s**: 30 прежних целевых, **20 funding acceptance**, 13 path acceptance.

`py_compile` четырёх изменённых production/research модулей — успешно.

Проверены наблюдённые нулевые ставки, inception и полная зрелость окон 24h/7d/30d, внутренняя дыра и отсутствующая due payout, configurable hourly schedule, невалидный/retracted record, отсутствие metadata при меняющемся F, prefix invariance до первой выплаты и после разрыва, future payout cutoff upstream, long/short funding до add, add timestamp/index, отсутствующий add clock и покрытие, entry-exclusive payout boundary, propagation add clocks/coverage в таблицу.

Для private-data модулей acceptance-тесты компилируют точные тела проверяемых функций через AST; это unit acceptance, не vendor end-to-end replay.

## Явные ограничения

- Expected interval — проверяемый контракт источника. Смена расписания funding требует отдельной явной metadata; 8h не восстанавливается по значениям F.
- Window coverage консервативно требует наблюдение на/до левой границы и непрерывную ожидаемую последовательность после неё. После восстановления данных нужно заново накопить полное окно.
- `add_t` существующего движка — закрытие часа, не точный intrahour fill. Для exact timestamp применяется `(entry, exit]`. Для engine add с `_add_before_close=True` payout на часе закрытия включён, на начале часа исключён; выплаты строго внутри часа дают unknown. Это явная standing-stop конвенция, не восстановленная tick-последовательность.
- Время publication/revision внешнего funding API отдельно не восстановлено; здесь устранены lookahead/coverage и неверный cutoff по наблюдённым source records.

`funding_repair.patch` содержит изменения этого funding-этапа; основной checkout проекта не изменён.
