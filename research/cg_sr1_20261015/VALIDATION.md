# Проверка реализации, 15.10.2026

Рабочая папка: `C:\bot7\research\cg_sr1_20261015`.
Python: локальный Python 3.10, без внешних зависимостей.

## Unit tests

Выполнено:

```text
python -B -m unittest -v test_cg_sr1
Ran 42 tests in 3.541s
OK
```

Покрыты strict t0/max capture-lock, полные UTC15m и deadline equality, exact
forward-v2/synthetic markers, первый freeze/id, пропуски наблюдений, source/metadata
cutoffs, закрытость/дубли/tick OHLC, 14 TR с действительным previous close,
Wilder gap TR, fixed seed с пропуском, no-lookahead ATR, обе стороны stop rounding,
две зоны одной свечой, первая отмена без повтора, signed geometry, строгий reclaim,
missing signal/entry/ATR, RR ровно 2 и чуть ниже, риск/quantity floor/notional cap,
одинаковый q/однократные costs, SL/TP ambiguity, известный target-open до high/low
с cap по T обеих сторон, stop gap по open, точный не-15m deadline, missing deadline
и path без late fill, ранний известный выход до позднего gap, отсутствие re-entry,
busy/priority/release и unknown portfolio, неизменность входных объектов,
CLI с явным synthetic-флагом, SHA256 входов и запретом overwrite. Дополнительный
mutation test проверяет одноразовое чтение каждого файла в bytes и совпадение
парсинга/хеша при изменении исходного CSV после чтения. Добавлены PENDING до
deadline+1min, точная maturity-граница и различие от исторического gap; standing
target-cap и stop-gap на deadline-open проверены зеркально для LONG/SHORT.

SHA256 окончательного кода:

```text
cg_sr1.py       6591B5C0BAF0279B787BECBAC5AC38D2DB5CCF93904CA889D1C8C4F8754AB96B
test_cg_sr1.py  BEA13824155CD314517171971A4E2C33D48ABA6A1072B66B7FF0F9E1D254373F
```

Внутренние конкурирующие candidates проверяются отдельно, поскольку обычные
допустимые слоты через 6 часов с horizon 4 часа не перекрываются.

## CLI smoke example — только synthetic

```text
python -B make_synthetic_fixture.py --output-dir .\synthetic_fixture
Wrote explicitly SYNTHETIC fixtures; no market or account data was used.

python -B cg_sr1.py --metadata .\synthetic_fixture\metadata.synthetic.json --snapshots .\synthetic_fixture\snapshots.synthetic.json --prices .\synthetic_fixture\prices.synthetic.csv --output .\synthetic_example_report_final.json --synthetic
{"version": "CG-SR1-v0-offline-0.1", "synthetic": true, "snapshot_count": 2, "entered_count": 1, "closed_count": 1, "pending_count": 0, "reason_counts": {"OBSERVATION_MISSED": 1}}
```

После успешного прогона новый synthetic report сохранён под итоговым именем
`synthetic_example_report.json`, заменив собственный предварительный пример в
этой новой папке. CLI overwrite по-прежнему запрещён.

Это проверка механики программы на выдуманных данных. Не backtest рынка,
не проверка maker fills и не подтверждение прибыльности. Реальные старые или
текущие изображения, журналы и snapshots не использовались. Публикации,
commit/push, сетевых запросов, чтения счёта, сборщиков и ордеров не было.
