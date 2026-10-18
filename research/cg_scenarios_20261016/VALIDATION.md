# Проверка CG-SR1 manual card, 16.10.2026

Перед кодом сохранён README с human-readable ASSUMPTIONS. После independent QA
добавлены guards непустого snapshotID, contract binding/minimums и поздней первой
котировки. Эти допуски интерфейса явно отделены от исходного CG-SR1 v0.

## Unit tests

```text
python -B -m unittest -v test_scenario_card
Ran 29 tests in 0.063s
OK
```

Негативные CLI-сценарии намеренно возвращают ошибку без `--synthetic` и при
overwrite; сообщения `error:` в выводе соответствующего теста ожидаемы.

Проверены strict t0, начало полного сигнального бара, close-confirmation вместо
касания, строгие границы и оба направления, обе зоны в свече, отсутствие E без
подстановки close/spot/уровня, known/unknown/stale lag, неизвестные settings,
contract binding и min quantity/notional, expired/future times, quote timestamps,
исполнимость/first-receipt declaration, свежая сейчас, но запоздалая на 2 часа E,
60s delay boundary, предыдущий ATR с 14 TR/реальным previous close/Wilder gap,
missing price/ATR, 1m→15m сверка, signed geometry, RR ровно 2 и чуть ниже,
единственный резерв 8bp, размер/округление, consumed/busy, отсутствие влияния
цвета/интенсивности и frozen spot на E, diagnostic-only continuation с ценовой
инвалидацией, optional same-bar F без фильтра, неизменность входа и CLI read-once
bytes/hash при мутации исходного файла после чтения.

SHA256:

```text
scenario_card.py       0A95BF8CBFF3171A98C61BA9DBB70347E65A38BBD96041C7C44CE2F724C9BF7C
test_scenario_card.py  580B833A8C46A6CA04269DDC7640EDAF9087A67A2CE1C21EC930EFDD64164BDC
```

## CLI smoke, все данные выдуманы

`make_synthetic.py` создал пять входов в synthetic_inputs. Каждый вход передан
CLI с `--synthetic`; JSON/MD сохранены в synthetic_cards. После финальной правки
русского текста CLI повторён в новые временные output paths, затем только
собственные предварительные примеры заменены итоговыми в этой новой папке.
CLI сам существующие файлы не перезаписывает.

| Пример | Результат |
|---|---|
| wait | WAIT, нет первой закрытой reclaim-свечи |
| conditional | CONDITIONAL/LONG_RECLAIM, E=null, RR/q не вычислены |
| ready_research | READY_RESEARCH/LONG_RECLAIM, только исследовательская готовность |
| unknown_lag | CONDITIONAL, неизвестная задержка и свежесть, вне primary |
| no_trade | NO_TRADE, net RR reserve8bp < 2 |

Во всех случаях trade_permission=false и primary_admitted=false. Денежный
результат, maker fills и вероятности не рассчитывались. Реальных новых карт,
снимков прошлого как свежих данных, сети, Mac, счёта или коллектора не было.
Старый v0/journal/конфигурации не менялись. Commit/push/публикации не выполнялись.

Это проверка механики минимального offline utility, не подтверждение торгового
преимущества или допуска алгоритма в реальную торговлю.
