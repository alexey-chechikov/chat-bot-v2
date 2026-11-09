# Execution-bounded path repair, 09.11.2026

Только изолированная repair-копия; живые процессы и торговые настройки не менялись.

`services/btc_signals/excursions.py` отделяет путь позиции от движения уже после исполнения. `features.path` сохраняет прежние ключи и принимает `exit_mode='close'|'target'`, optional `execution` (minute OHLC, t — OPEN seconds UTC).

- Close exit сохраняет полные H/L до закрытия. Первые ±1 ATR в одном баре дают None/ambiguous, а не фиктивное 0.5.
- Target exit сохраняет все полные предыдущие часы. Favorable excursion exit-hour ограничен известным first-touch exit price; adverse lower учитывает предыдущие бары, open и exit, upper допускает adverse H/L выхода. Когда bounds различаются, числовой MAE=None, bounds сохранены.
- При исполнении target на open-gap H/L всего exit-hour исключены.
- Minute execution проверяет непрерывность с начала exit-hour до first target hit. Полные предыдущие минуты включены. В touching minute favorable ограничен exit price, adverse остаётся bounds по open…H/L; это не tick-порядок. Последующие минуты игнорируются, даже если содержат экстремумы/дыры. При дыре до исполнения — честный возврат к hourly bounds с reason.
- `run.feature_rows` и `trade_table.build` передают target mode для целевых выходов. Все новые bounds/quality и `добор UTC` явно исключены в `trade_scan.OUTCOME`, чтобы итоговые метки не становились model inputs. Приватные funding coverage и add clocks тоже не входят в признаки.

Новые поля: MFE/MAE lower/upper в ATR и %, качество пути, разрешение выхода, причина качества, качество порядка ±1 ATR. Legacy `часов до MFE/MAE` — верхняя граница соответствующего бара, а не восстановленная tick-минута; это отмечено `семантика времени экстремумов='bar_upper_bound_not_tick_time'`. Новые lower/upper для времени дают часовой/минутный интервал либо точную open-gap точку; при неизвестном MAE время тоже None. Все timing outcomes исключены из входных признаков.

Old capped-horizon keys `ход через 24ч/72ч/7д` сохраняют семантику min(horizon, exit), но horizon задаётся фактическим временем `entry_time+w*3600`. При раннем выходе используется exit price, иначе требуется точная запись horizon; отсутствующий час даёт None без asof/future fill. Это исправление часов на разрывах источника, не изменение торговой стратегии. Отдельные uncapped fixed-horizon labels требуют отдельного артефакта.

**14 новых acceptance-тестов**: post-exit hourly extremes, long/short open gap, full close hour, previous completed hours, adverse open bound, first minute touch and remaining intraminute bounds, exact adverse dominated by earlier minute, gap before hit, ignore gaps/extremes after hit, known cross-bar order, no-hit zero, model-feature exclusion, actual-clock capped horizon with a missing exact hour.

Совместный запуск `tests/services/btc_signals`, `test_features_ext.py`, `test_btc_funding_repair.py`, `test_btc_path_repair.py`: **63 passed in 3.45s** (30 прежних +20 funding +13 path). `py_compile` изменённых модулей — успешно. Полный исходный suite 1584 этим числом не заявлен.

Ограничение: точный high/low и временной порядок внутри touching minute без тиков неизвестны. Bounds/None сохраняют неопределённость; label «exact» означает точные возвращаемые агрегаты и threshold order при имеющейся гранулярности, а не восстановленную всю траекторию.
