# B018: три убыточные сделки мая–июля и цена запретов на вход

Дата исследования: 02.11.2026. Для Claude, ветка `alexey/mac-2026-05-29`. Все времена ниже — **UTC**; летом на графике в часовом поясе Варшавы нужно прибавить 2 часа. Это офлайн-разбор публичных данных и модельных сделок. Живая торговля, процессы и настройки не менялись.

**Главный результат:** у варианта с тремя ордерами в мае–июле было пять сделок, три убыточные. Две закончились стопом, одна — по времени. Простой запрет по TEMA убирает убытки вместе с большинством хороших входов. Запрет «встречный taker-поток + падение OI» выглядит лучше на исходной истории, но результат раннего периода снова отрицателен при дополнительной задержке данных на один час. Подтверждённого нового преимущества пока нет.

Разбирается **B018**, а не все варианты из предыдущего перебора: H4, три конечные части на откате, структурный стоп `swing6`, цель `2R`. B018 был выбран для рассмотрения постфактум. Нового массового перебора, подбора порогов и перестройки выходов здесь нет. Шесть небольших гипотез запрета применены к неизменным сигналам, затем выполнен полный повтор исполнения.

## 1. Что именно потеряли

| № исходного цикла | Вход | Сторона | Выход | Причина | Заполнилось | Net, USDT |
|---|---|---|---|---|---:|---:|
| 1 | 12.06 20:00 | SHORT | 13.06 21:00–22:00 | Стоп | 1 из 3 | −1,5255 |
| 3 | 07.07 08:00 | SHORT | 10.07 16:00 | 80 часов удержания | 3 из 3 | −1,2504 |
| 5 | 29.07 12:00 | LONG | 31.07 14:00–15:00 | Стоп | 3 из 3 | −3,0433 |

В мае сделок B018 нет. Сумма трёх убытков **−5,8192**, два прибыльных цикла 06.07 и 26.07 дали **+2,8216**. Общий net мая–июля **−2,9976**. Это результаты непрерывной исследовательской симуляции, не история реальных аккаунтных ордеров.

Внутри часа точная минута исполнения неизвестна: текущая проверка использует H1 OHLC. Два порядка движения OHLC/OLHC дали одинаковые результаты для всех сравниваемых вариантов; это проверка неоднозначности свечи, а не доказательство биржевого исполнения. В предыдущем отчёте минутами проверялся октябрь, не эти июньско-июльские эпизоды.

## 2. Правила и значения, известные до входа

Исходный сигнал использует канал Дончиана по **предыдущим 30 закрытым H4**, память касания границы и два закрытия по нужную сторону H4 EMA200. Условия плоского режима одновременно требуют малого наклона EMA, ADX<22 и допустимой ширины канала. Поэтому ниже EMA само по себе не означает сильный нисходящий тренд, а почти горизонтальная EMA не обязательно выключает вход: ADX может оставаться выше 22.

Свеча сигнала заканчивается в указанное время; первая часть исполняется на открытии следующего H1, в тот же момент на временной оси. Две лимитные части размещаются на 0,375 и 0,75 ATR против позиции. Срок заявок — 12 часов; общий срок позиции — 80 часов. Стоп фиксируется за экстремумом последних шести **уже закрытых** H4 с буфером 0,25 ATR. Тейк рассчитывается как 2R от плановой средней всех трёх частей. **Если набрана одна часть, её собственный R:R не равен 2.**

Плановый риск корзины — до 3 USDT с базовыми комиссиями и проскальзыванием, номинал до 300 USDT. Это одна общая сумма риска. Maker 0,016%, taker 0,048%, проскальзывание рыночного исполнения 0,02%, лимитный trade-through 0,01%. Funding взят из истории Bybit и применяется только к уже открытым частям. Будущие гэпы/funding могут увеличить убыток сверх плановых 3.

Средние: гладкая голубая EMA200; зелёная TEMA50, жёлтая TEMA100, красная TEMA200. Формулы восстановлены по доступному исходнику и строке настроек; это не побайтовая проверка установленного у пользователя Pine. Дневная ступенчатая SMA100 — другая линия. [Предыдущая сверка настроек и ограничений](https://github.com/alexey-chechikov/chat-bot-v2/blob/071de6c0ea94b97f91677e9e0e446112a7d71331/docs/WEEX_GPT_MA_SETTINGS_AND_SIGNAL_RECHECK_2026-11-02.md).

| Доступно в момент входа | 12.06 SHORT | 07.07 SHORT | 29.07 LONG |
|---|---:|---:|---:|
| Закрытие H4 | 63 549,10 | 63 062,70 | 64 484,70 |
| H4 EMA200 | 69 970,32 | 63 912,62 | 64 281,68 |
| Отступ цены от H4 EMA | −9,177% | −1,330% | +0,316% |
| H4 TEMA50 / TEMA100 / TEMA200 | 62 265,79 / 59 879,36 / 61 527,90 | 63 654,29 / 62 358,75 / 59 680,47 | 63 999,92 / 64 919,62 / 64 975,72 |
| H1 EMA200 | 63 685,88 | 62 053,98 | 64 468,92 |
| Отступ от H1 EMA | −0,215% | +1,626% | +0,024% |
| H4 ADX14 | 16,58 | 25,14 | 25,29 |
| Наклон H4 EMA за 5 баров | −0,473% | −0,033% | −0,014% |
| H4 ATR14 | 1 006,47 | 830,11 | 632,69 |
| H4 канал low / high | 60 614,50 / 64 371,80 | 60 075,00 / 64 703,20 | 62 707,40 / 65 749,20 |
| Изменение цены за 6 часов | +0,550% | −1,178% | +0,701% |
| Binance Δ taker за 6 часов | +4,565% | −7,415% | −0,404% |
| Доля taker-покупок в обороте за 6 ч | 52,283% | 46,292% | 49,798% |
| Bybit OI, BTC | 53 337,442 | 57 291,500 | 53 894,938 |
| Изменение OI за 6 часов | −1,722% | +2,163% | −1,044% |
| Отношение long/short аккаунтов | 1,513 | 1,534 | 1,419 |

Δ = `100 × (2 × taker_buy_quote_6h / total_quote_6h − 1)`. Это дисбаланс исполненных агрессивных сделок Binance USDT-M, а не изменение цены и не лимитный стакан. Поля taker buy и quote volume описаны в [официальном наборе Binance](https://github.com/binance/binance-public-data/blob/master/README.md). Источник фактических свечей в сохранённой provenance — `fapi.binance.com/fapi/v1/klines`.

OI взят с Bybit linear BTCUSDT, в BTC; значения и account-ratio доступны модели с дополнительной задержкой **один час**. Последний OI на решении 12:00 относится к 11:00; его изменение сравнивается с 05:00. Поток использует шесть полностью закрытых часов до 12:00. Ни будущие значения, ни обратное заполнение пропусков не используются. API допускает задержки данных; поэтому отдельно проверен ещё один час задержки. [Bybit OI](https://bybit-exchange.github.io/docs/v5/market/open-interest).

Отношение аккаунтов считает держателей, не размер денег: 1,5 не означает, что лонговый денежный объём на 50% больше. [Определение Bybit](https://bybit-exchange.github.io/docs/v5/market/long-short-ratio). Покупка может открывать лонг или закрывать шорт, падение OI отражает сокращение открытого интереса, но сочетание этих рядов не идентифицирует участников. Истории CoinGlass Whale Index 2, агрегированных ликвидаций и книги лимитных заявок для этих решений нет. Утверждения о китах и ликвидациях здесь не проверены.

## 3. Сделка 1: шорт 12 июня — медленная средняя разрешила продавать восстановление

**Что разрешило вход.** H4 12.06 12:00–16:00 достиг 64 371,80 при предыдущем верху канала 64 250,00 и закрылся 63 565,70. Следующее закрытие 20:00 сохранило цену ниже H4 EMA200; импульсного запрета SHORT не было. Формальный flat не включился: наклон EMA −0,473% по модулю больше границы 0,30%, хотя ADX всего 16,58.

**Что этому противоречило до сделки.** Цена ниже очень медленной EMA почти на 9,2%, но уже выше **всех TEMA**, в том числе жёлтой на 6,13%. За последние шесть часов цена выросла на 0,55%, taker-покупки преобладают, OI уменьшился на 1,72%. Моя трактовка — восстановление после падения при сокращении позиций, а не согласованный набор нового нисходящего импульса. Закрытие шортов — возможное объяснение, не установленный факт. Нельзя объявить столь удалённую EMA достаточным основанием нового шорта.

| Событие | Время/цена |
|---|---|
| Первая часть рынком | 12.06 20:00; 63 536,39; 0,001317405 BTC |
| Плановые части 2 / 3 | 63 926,53 / 64 303,95; не заполнились до истечения срока |
| Отмена двух заявок | 13.06 08:00, через 12 часов |
| Общий стоп / тейк | 64 623,42 / 62 515,43 |
| Исполнение стопа с модельным проскальзыванием | В час 13.06 21:00; 64 636,34 |
| Gross − комиссия + funding | −1,44908 − 0,08105 + 0,00461 = **−1,52552** |

До часа выхода минимум цены был 63 358,70: движение в пользу первого входа всего **0,280%**. Затем восстановление продолжилось. В час стопа high достиг 64 746,90 и пересёк фиксированный уровень. Позднейший проход через цены второй/третьей части не может считаться их исполнением: заявки уже отменены.

Собственный ценовой R:R единственной набранной части — **0,94 до комиссий**, хотя конфигурация называется R2. Это следствие расчёта цели от ещё не набранной полной корзины. Стоп здесь ограничил убыток; увеличение срока заявок набрало бы больший риск на восстановлении. Последнее не является отдельно проверенной модификацией.

До стопа правило `cut_short` ни разу не включилось на закрытом H4: EMA оставалась далеко сверху, а подъём не давал достаточного импульса за выбранное окно. Запрет по конфликту TEMA, ADX или встречному потоку убрал бы этот вход. Его цена на остальных сделках рассчитана ниже.

## 4. Сделка 3: шорт 7 июля — направление сначала сработало, цель и удержание не сработали

**Что разрешило вход.** Касание верхней границы пришло с H4, закрывшегося 06.07 20:00: high 63 969,30 рядом с прежним high канала 63 987,10. Память касания сохранилась до сигнала 07.07 08:00. Цена ниже H4 EMA, ADX 25,14, формальный flat отсутствует. Поток −7,42%, OI +2,16%, цена за шесть часов −1,18% — сочетание согласуется с направлением шорта. Оно не доказывает, что весь прирост OI — новые шорты.

**Конфликт до входа.** H1 цена выше EMA200 на 1,63%; H4 цена выше жёлтой и красной TEMA, ниже зелёной. H4 EMA почти горизонтальна. Это неоднородная структура, а не единогласный нисходящий тренд. Но ближайшая прибыльная сделка 06.07 тоже продавала выше H1 EMA и H4 TEMA100. Нельзя запретить только плохой экземпляр этого признака после того, как известен результат.

| Событие | Время/цена |
|---|---|
| Части 1 / 2 / 3 | 07.07 08:00 / час 10:00 / час 12:00 |
| Цены частей | 63 050,09 / 63 373,99 / 63 685,28 |
| Количества BTC | 0,000626965 / 0,000623761 / 0,000620712 |
| Средняя полного набора | 63 368,72 |
| Стоп / тейк | 64 910,73 / 60 284,72 |
| Закрытие через 80 часов | 10.07 16:00; 64 034,40 с проскальзыванием |
| Gross − комиссия + funding | −1,24578 − 0,08915 + 0,08453 = **−1,25039** |

**Стоп не сработал.** До выхода максимум составлял 64 688,20, ниже стопа. После полного набора цена в час 08.07 15:00 дошла до **61 500**: движение от первого входа в пользу шорта **2,459%**. До цели 60 284,72 рынок не дошёл, затем прибыльное движение полностью отдалось назад. Значит, этот убыток нельзя честно объяснить лишь «плохим направлением на входе».

Во время доливок изменялось подтверждение: Δ6 ослабла с −7,42% на входе до −0,49% в 10:00 и −0,13% в 12:00, OI6 с +2,16% до +0,43% и +0,36%. В текущем исполнителе уже размещённые лимитки не требуют нового подтверждения каждого добавления. На 12:00 известен H4 close 63 378,70; цена третьей части достигается позже внутри этого часа. Будущий максимум часа не использован при решении.

На **09.07 08:00** уже доступен противоположный импульс: H4 тело **+1,669%**, close **62 977,60**, Δ6 **+5,277%**, OI6 **−0,121%**. `cut_short` становится true, но в B018 он **отменяет только незаполненные заявки**, а все три уже заполнены. Позиция остаётся открытой. Это конкретное место для отдельной проверки выхода из остатка, а не основание задним числом запретить вход 7 июля. Доходность правила такого выхода в этой работе не заявляется.

## 5. Сделка 5: лонг 29 июля — формальное закрепление у EMA и цель за пределами канала

**Что разрешило вход.** H4, закрывшийся 28.07 16:00, проколол низ канала: low 62 707,40 против прежнего low 63 023,10, затем close 63 899,80. К 29.07 12:00 закрытия находятся над H4 EMA. ADX 25,29 не даёт считать режим flat, несмотря на почти нулевой наклон EMA −0,014%.

**Что было слабо до входа.** Над H4 EMA всего **0,316%**, над H1 EMA **0,024%**. Цена ниже TEMA100/200, TEMA50 ниже TEMA100. Δ6 **−0,404%** означает почти баланс, а не мощные продажи: taker-покупок 49,798%. OI падает на 1,044% при росте цены за шесть часов +0,701%. Это не согласованный набор сильного лонгового тренда, но и не доказанный разворот вниз.

| Событие | Время/цена |
|---|---|
| Первая и вторая части | 29.07 в час 12:00; 64 497,60 / 64 247,44 |
| Третья часть | В час 29.07 15:00; 64 010,19 |
| Количества BTC | 0,000565510 / 0,000567712 / 0,000569816 |
| Средняя полного набора | 64 251,13 |
| Стоп / тейк | 62 549,23 / 67 654,92 |
| Верх канала при входе | **65 749,20**, ниже цели на 1 905,72 |
| Выход | В час 31.07 14:00; 62 536,72 с проскальзыванием |
| Gross − комиссия + funding | −2,91970 − 0,08030 − 0,04330 = **−3,04330** |

Общий стоп был посчитан до входа; в час выхода low **62 384,90** пробил его. Превышение плановых 3 USDT здесь объясняется funding **0,04330**, а не расширением стопа. До часа выхода рынок поднимался до **65 391,60** в час 31.07 01:00 — **+1,386%** от первого входа. Ни исходный верх канала 65 749,20, ни более дальняя R2-цель достигнуты не были. Утверждение «тейк по верху канала точно спас бы эту сделку» неверно.

На **30.07 00:00** после трёх закрытий H4 ниже EMA сработал `cut_long`: close 63 952,60, EMA 64 267,94. Все части уже набраны, отменять нечего. Через несколько баров цена вернулась над EMA; к стопу три последовательных закрытия ниже неё ещё не набрались заново. Это показывает различие фиксированного стопа, отмены добавлений и выхода при потере структуры. Они не должны иметь одинаковое имя «стоп» в будущем индикаторе.

## 6. Что дали возможные запреты, включая потерянные прибыльные сделки

Все условия ниже проверены **на закрытом баре до первого ордера**. Они ограничивают исходный новый сигнал B018: запрещённый сигнал не переносится автоматически на следующий бар. Остальные правила неизменны. Отдельно выполнены полный повтор исполнения, удвоенные расходы и оба порядка OHLC. Новых входов вместо запрещённых в этой конкретной истории не появилось; поэтому суммы совпали с простой фильтрацией исходных циклов. Это установленный результат повторного прогона, не общее свойство таких запретов.

| Код | Точное условие разрешения |
|---|---|
| price_tema100 | Для LONG close > H4 TEMA100; для SHORT close < TEMA100 |
| tema_alignment | Предыдущее условие плюс TEMA50 > TEMA100 для LONG; зеркально для SHORT |
| flow_aligned | Δ6 > 0 для LONG; Δ6 < 0 для SHORT |
| no_opposing_flow_oi_drop | Запрет при Δ6 против позиции **и одновременно** OI6 < 0; при пропуске этих данных вход не разрешён |
| h1_ema_confirmation | Последний закрытый H1 по стороне своей EMA200 в направлении сделки |
| adx22 | H4 ADX14 ≥ 22 |

`tema_alignment` — самостоятельная гипотеза про зелёную/жёлтую, **не формула зоны Grid Regime v11**, где сравниваются TEMA100/200. Порог 22 взят из прежних настроек, а не подобран по этим трём убыткам. Комбинации всех фильтров и новые пороги не перебирались.

| Разрешение | Май–июль | Авг.–15 сент. | 16 сент.–окт. | Май–окт. | Циклов | Убрано убыточных / прибыльных | Просадка непрерывного прогона |
|---|---:|---:|---:|---:|---:|---:|---:|
| Исходный B018 | −2,9976 | +4,1989 | +8,9835 | +10,1848 | 12 | — | 6,4071 |
| Цена по стороне TEMA100 | 0 | 0 | +5,9188 | +5,9188 | 2 | 3 / 7 | 2,9563 |
| Цена + порядок TEMA50/100 | 0 | 0 | 0 | 0 | 0 | 3 / 9 | 0 |
| Поток по направлению | +1,5712 | +1,3704 | +7,4981 | +10,4398 | 7 | 2 / 3 | 5,1639 |
| Запрет: встречный поток + OI↓ | +1,5712 | +2,6804 | +7,4981 | +11,7497 | 8 | 2 / 2 | 5,1639 |
| Подтверждение H1 EMA | −4,5688 | +1,3099 | +5,7539 | +2,4950 | 4 | 1 / 7 | 5,8948 |
| ADX ≥ 22 | −1,4721 | +1,5185 | +8,9835 | +9,0299 | 9 | 1 / 2 | 6,6824 |

Все суммы и просадки в USDT, с расходами. Нулевой результат означает отсутствие торговли, а не доказанную прибыльность. Просадка включает нереализованный результат по закрытиям H1; внутрисвечная просадка может быть больше. Даже без срабатываний стопа просадка не обязана равняться нулю.

Цена запретов на всём периоде:

- TEMA100 предотвращает 5,8192 убытков, но убирает **10,0853** прибыли: итог хуже на 4,2660. Причина — стратегия входа на откате часто специально входит до восстановления быстрых средних.
- Дополнительный порядок TEMA50/100 отсекает вообще все 12 циклов, в том числе октябрьский удачный шорт. Из факта «нет убытков» преимущество не следует.
- Поток по направлению предотвращает 4,5688 убытков, теряет 4,3138 прибыли. Улучшение всего **0,2550** на шести месяцах.
- Встречный поток + OI↓ предотвращает те же 4,5688, теряет **3,0039** прибыли — лонги **11.09 +1,5185** и **17.09 +1,4853**. Разница к исходному B018 **+1,5650**. Самый большой положительный цикл 29.10 даёт +5,7539, почти половину итогового net фильтра.
- H1 EMA отсекает июльский убыточный шорт, но оставляет оба стопа и убирает семь прибыльных циклов. Идея «подтвердить всем таймфреймам» здесь ухудшила результат.
- ADX22 удаляет июньский убыток, но вместе с ним прибыльные лонги 31.08 и 08.09. Результат и непрерывная просадка хуже исходных.

## 7. Проверка-опровержение: один час меняет вывод

После основных прогонов отдельно зафиксирована проверка задержки. Время ценового сигнала, размеры и выходы сохранены. OI6 и Δ6 взяты из предыдущего доступного часа: это **ещё один час** сверх уже заложенной задержки OI, не сдвиг на H4 и не новый поиск параметров.

| Правило | Май–июль, обычные данные | Май–июль, +1 ч задержки | Май–окт., обычные | Май–окт., +1 ч |
|---|---:|---:|---:|---:|
| Поток по направлению | +1,5712 | **−1,4721** | +10,4398 | **+6,0261** |
| Встречный поток + OI↓ | +1,5712 | **−1,4721** | +11,7497 | **+8,7064** |

Причина проверяема на конкретной сделке: перед лонгом 29.07 у доступного за час до входа потока **+0,2104%**, а у текущего −0,4040%. OI6 отрицателен в обоих случаях. Знак близкого к нулю потока меняется; оба запрета разрешают этот стоповый лонг при задержке. Пороговый сигнал неустойчив даже без изменения ценового графика. Для простого потока дополнительно исчезает прибыльная сделка 08.09.

Удвоение комиссии и проскальзывания при сохранении исходных количеств даёт за май–октябрь: B018 **+9,2446**, поток **+9,9134**, встречный поток + OI↓ **+11,1403**. Это не устраняет проблему задержки. Совместный стресс «задержка + двойные расходы» здесь не выполнялся; выбирать лучший из разных стрессов нельзя.

Новые фильтры сформулированы после просмотра неудачных сделок; весь май–октябрь уже использовался в прежнем исследовании. Названия прежних частей выборки train/validation/control не превращают эти новые результаты в независимую проверку. Улучшение от двух удалённых стопов при 12 исходных циклах не устанавливает статистическую закономерность.

## 8. Мой вывод для следующей версии индикатора

Пользователь попросил оценивать много факторов, выбирать long/short/паузу и проверять конечный вход из 3–5 частей. Ни запрет именно этих трёх входов, ни приведённая интерпретация их механики не приписываются пользователю: это выводы Codex, которые можно сопоставить с его чтением графика.

1. **Сторона медленной EMA — описание контекста, а не достаточное разрешение.** Июньский вход демонстрирует восстановление над TEMA при цене намного ниже EMA. Для интерфейса полезно явно показывать конфликт, расстояние до EMA и состояние локальной структуры.
2. **Поток/OI показывать с временем доступности и силой, а не только знаком.** «−0,40% Δ» нельзя отображать как сильное давление продавцов. Долю покупок 49,80% следует считать почти равновесной; конкретный порог нейтральной зоны ещё не подтверждён и здесь не подбирался.
3. **Разрешение первого входа и каждой доливки различать.** 7 июля подтверждение потока ослабло почти до нуля ещё до полного набора. Это отдельный проверяемый вопрос; нельзя использовать знание всего часа для отмены уже состоявшегося внутри него исполнения.
4. **Показывать R:R фактически набранной позиции.** Надпись R2 скрывает июньские 0,94 до комиссий для единственной части. Нельзя незаметно переносить цель после недобора: это уже другая политика, требующая проверки.
5. **Отмена лимиток не закрывает остаток.** Для 7 июля есть конкретная точка 09.07 08:00, где действующее правило обнаружило встречный импульс, но не защищало накопленную позицию. Следующая предметная проверка — выход остатка на следующем открытии после `cut`, с оценкой также прибыльных циклов и изменившихся последующих входов.
6. **Вход от диапазона и цель на продолжение тренда согласовать явно.** 29 июля исходная R2-цель лежала выше верха канала на 1 905,72. Но и верх канала не был достигнут; обещать исправление одним переносом TP нельзя.

Из этих проверок я **не выбираю новый автоматический запрет для живой торговли**. Для теневого исследования сохраняется гипотеза встречного потока и снижения OI, вместе с её опровержением по задержке. TEMA, ADX и H1-подтверждение тоже не объявляются бесполезными вообще: проверено только конкретное добавление к B018, на конкретных данных и правилах.

Исполнимость по лотам остаётся ограничением прежней модели: количества нормированы непрерывно, без округления к спецификации биржи. В июльских примерах каждая часть меньше 0,001 BTC; текущее ограничение Bybit из предыдущей проверки не допускает такой объём. Округление вверх изменит риск; историю требований на даты сделок и правила WEEX здесь не подтверждали. Это анализ признаков и механики на общей нормировке, не готовая доходность исполнимой WEEX-стратегии.

## 9. Проверки, артефакты и связь с предыдущими работами

**13 тестов прошли.** Исходные 12 циклов B018 воспроизведены полностью, включая события и суммы. Проверены неизменность хешей входных данных и старого исполнителя, пересчёт средних и сигналов на усечённой истории без будущих баров, границы шестичасовых окон Δ/OI из сырых рядов, доступность H1/H4, запрет при пропусках факторов, сверка каждой части с итогом цикла, причины выхода и оба порядка OHLC.

Новые расчёты сохранены в `research/basket_loss_review_20261102`. `protocol.json` и `review.py` зафиксированы хешами до получения итогов запретов; это фиксация эксперимента, не независимость от ранее просмотренной истории. Дополнительный тест задержки отдельно помечен posthoc. Старые исходники и результаты не перезаписаны.

Основные файлы: `loss_cases.json` (все три подробных журнала), `loss_event_snapshots.csv` (показатели на входах, доливках, закрытиях H4 и выходах), `all_entries_and_vetoes.csv` (все 12 сделок, включая прибыльные), `replay_results.csv`, `direct_veto_cost.csv`, `replay_cycle_changes.csv`, `timing_stress_results.csv`, `frozen_inputs.json`. Графики `case_01.png`, `case_03.png`, `case_05.png`, `veto_comparison.png` находятся в локальном пакете. В Git публикуется один самодостаточный текстовый отчёт с таблицами и исходниками ниже; локальные PNG и сырые ряды в этот коммит не включены.

Основание для воспроизведения — [исправление исполнения и конечные корзины, ab51e55](https://github.com/alexey-chechikov/chat-bot-v2/blob/ab51e55cf4eaaff9fc549df9b569e1511b9611fd/docs/WEEX_GPT_432_EXECUTION_CORRECTION_AND_STAGED_ENTRIES_2026-11-02.md), где приведён `staged.py` и старые правила. Отозванные результаты прежней сетки с ошибкой marketable-maker не возвращаются в сравнение. Здесь от старого `engine.py` используется только загрузчик `Replay` свечей/funding/mark, а не ошибочный сеточный исполнитель.

Предыдущий [разбор рынка и CoinGlass](https://github.com/alexey-chechikov/chat-bot-v2/blob/df78486f7a6800a28da261f8d2048f23f2e3c014/docs/WEEX_GPT_MARKET_REGIMES_AND_GRID_RULES_2026-11-02.md) и [добавление S&P 500, золота и нефти](https://github.com/alexey-chechikov/chat-bot-v2/blob/9fe58447a256c113849b978e46d7f51e3571dd02/docs/WEEX_GPT_MACRO_CORRELATION_ADDENDUM_2026-11-02.md) остаются контекстом. В данной проверке макрофакторы не использовались для запретов; им не приписывается объяснение конкретных стопов.

Поручение Claude для проверки: сверить причинность и переносимость времён/типов средних; воспроизвести три журнала и потерянные хорошие входы; проверить отдельную политику закрытия остатка при `cut`, не меняя одновременно входы; оценить эту политику на ещё не использованном периоде после фиксации правил. Не внедрять по результатам этого ретроспективного отчёта без отдельного решения пользователя о живой торговле.


## Приложение A. Все исходные входы и разрешения

Да/нет — разрешение соответствующего дополнительного фильтра в момент исходного входа. Будущий результат приведён только для оценки цены фильтра.

| UTC | Сторона | Net | T100 | T50/T100 | Поток | Поток+OI | H1 EMA | ADX22 |
|---|---|---|---|---|---|---|---|---|
| 12.06 20:00 | SHORT | -1.5255 | нет | нет | нет | нет | да | нет |
| 06.07 08:00 | SHORT | +1.5365 | нет | нет | да | да | нет | да |
| 07.07 08:00 | SHORT | -1.2504 | нет | нет | да | да | нет | да |
| 26.07 00:00 | LONG | +1.2852 | нет | нет | да | да | нет | да |
| 29.07 12:00 | LONG | -3.0433 | нет | нет | нет | нет | да | да |
| 31.08 04:00 | LONG | +1.3099 | нет | нет | нет | да | да | нет |
| 08.09 20:00 | LONG | +1.3704 | нет | нет | да | да | нет | нет |
| 11.09 20:00 | LONG | +1.5185 | нет | нет | нет | нет | нет | да |
| 17.09 00:00 | LONG | +1.4853 | нет | нет | нет | нет | нет | да |
| 09.10 00:00 | LONG | +1.5794 | нет | нет | да | да | нет | да |
| 15.10 20:00 | LONG | +0.1649 | да | нет | да | да | нет | да |
| 29.10 04:00 | SHORT | +5.7539 | да | нет | да | да | да | да |

## Приложение B. Данные и воспроизводимость

Хеши сохранены до расчёта. Относительные пути ниже относятся к корню проекта. Публичные ряды для воспроизведения содержатся в локальном архиве, их сырые значения в Git не публикуются.

<details><summary>frozen_inputs.json</summary>

```json
{
  "research\\basket_loss_review_20261102\\protocol.json": "ad83aa599bc91ea3b7b3d8da66a4d71757186f4fa6089c5be463c9c195178d37",
  "research\\basket_loss_review_20261102\\review.py": "88788905afc36457a379640fd5747ad12e685f803715ed6aaa49d4eb0e431993",
  "research\\staged_entry_20261102\\staged.py": "e62faa4350fbde4e54e5863f662bfd4fc447926e326f296cffef51d62c159d59",
  "research\\strategy432_regimes_20261102\\features.py": "e7b874430c4bc05c0561a7125f0a1c8218aad70694c3d478d151d3cce315e847",
  "research\\strategy432_regimes_20261102\\engine.py": "93b832904f1195206bf7422f36c763f357c33ddb1d2cde4f0aa386b99f018926",
  "research\\strategy432_regimes_20261102\\features_H4.parquet": "4368998b86251ba575cb1cb8d673233893288d416ebf6cae44ca4fcf21c4ce21",
  "research\\strategy432_regimes_20261102\\features_H1.parquet": "b42d028b9e16bf45ee357b08a908143a829a0a4ac2f679bb3608722a1fa8efc3",
  "research\\staged_entry_20261102\\B018_continuous_detail.json": "2687c351374fdefef694032ce47052dc7847a221b8c4151fb022497532474cef",
  "research\\strategy432_regimes_20261102\\public_data\\accounts.json": "7db640ad23c575bf357766076e7d7c5ebf7e872b97f8bf2cb7b2b2a4b6b644ac",
  "research\\strategy432_regimes_20261102\\public_data\\binance_1h.json": "f7dbdea09ddbd5b2142afc3879ed7313f6977a25b42ee3effe7b79332c2459a5",
  "research\\strategy432_regimes_20261102\\public_data\\bybit_1h.json": "30a8fd8a7f37a81be137ce00835e007eed9ea38211dd1508ef340c5414dc386e",
  "research\\strategy432_regimes_20261102\\public_data\\bybit_4h.json": "c64deff67d39425f8447db5130847897b7e44e7062944b300599f380a525904b",
  "research\\strategy432_regimes_20261102\\public_data\\bybit_mark_1h.json": "a9d42435cadf89b7985e73c3b337df0074feea942665137e3a32d285aa2a6581",
  "research\\strategy432_regimes_20261102\\public_data\\funding.json": "9ec1f1b67349bec9a8350b26d6c146dce48754c8d5cc5d3976c0b2e06036a50f",
  "research\\strategy432_regimes_20261102\\public_data\\oi.json": "44d053c4f9f3c314fc023a3b1ef1c2b49dea9e76081d4ced76c4c25a8cdddf96",
  "research\\strategy432_regimes_20261102\\public_data\\provenance.json": "955cd32fd2abfc76ace6a6ef2b5d14a3ff7d702b7bdcdce95ecc0cf58ee6a625"
}
```
</details>

<details><summary>protocol.json</summary>

```json
{
  "date": "2026-11-02",
  "task": "Review the three losing May-July cycles of B018 and the cost of causal entry vetoes on profitable cycles.",
  "research_only": true,
  "baseline": "B018; H4; 3 one-shot pullback orders; swing6 stop; R2 target",
  "frozen_engine": "../staged_entry_20261102/staged.py",
  "status": "All hypotheses are retrospective and all periods were previously inspected. No new out-of-sample claim.",
  "hypotheses": {
    "baseline": "Original B018 signals unchanged.",
    "price_tema100": "Require side * (closed H4 close - TEMA100) > 0.",
    "tema_alignment": "Require price_tema100 and side * (TEMA50 - TEMA100) > 0.",
    "flow_aligned": "Require side * Binance 6-hour taker delta > 0.",
    "no_opposing_flow_oi_drop": "Veto if side * delta6 < 0 AND Bybit OI6 < 0. Both inputs must be available.",
    "h1_ema_confirmation": "Require side * (last completed H1 close - H1 EMA200) > 0.",
    "adx22": "Require closed H4 ADX14 >= 22. Existing regime boundary, not a fitted threshold."
  },
  "scope": "One-factor gates only, no threshold search, no combination search, no change to entry/stop/target/sizing/exit engine. Gate original rising-edge signals only; a rejected setup is not deferred to a later bar.",
  "periods": {
    "early": ["2026-05-01", "2026-08-01"],
    "middle": ["2026-08-01", "2026-09-16"],
    "late": ["2026-09-16", "2026-11-01"],
    "continuous": ["2026-05-01", "2026-11-01"]
  },
  "checks": "Reproduce original 12 cycles, causal joins and feature prefix invariance, direct block table vs full replays, accounting reconciliation, doubled costs preserving quantities, compare both OHLC paths.",
  "interpretation": "Public market history; fractional quantities and fee assumptions inherited from original research. This is not account PnL, CoinGlass aggregate data, or proof of WEEX executability."
}

```
</details>

<details><summary>timing_stress_protocol.json</summary>

```json
{
  "reason": "Flow near zero on July 29 warrants a timing robustness check, not threshold optimization.",
  "posthoc": true,
  "extra_delay_hours": 1,
  "gates": [
    "flow_aligned",
    "no_opposing_flow_oi_drop"
  ],
  "unchanged": "All price signals, stops, targets, quantities and exits; base OI delay is still present."
}
```
</details>

<details><summary>review.py</summary>

```python
"""Focused retrospective B018 loss review; imports frozen offline research only."""
from pathlib import Path
import hashlib, json, sys
import numpy as np
import pandas as pd

P = Path(__file__).resolve().parent
STAGED = P.parent / 'staged_entry_20261102'
OLD = P.parent / 'strategy432_regimes_20261102'
sys.path.insert(0, str(STAGED))
from staged import inputs, run
from features import candles

def dump(name, obj):
    (P/name).write_text(json.dumps(obj, indent=2, default=lambda x: x.item() if isinstance(x, np.generic) else str(x)), encoding='utf-8')

def joined():
    f = inputs('H4')
    h = pd.read_parquet(OLD/'features_H1.parquet')
    # The just-completed H1 bar is available at the decision/next order open.
    right = h[['known_utc','close','ema','ret6']].rename(columns={
        'known_utc':'h1_known_utc', 'close':'h1_close','ema':'h1_ema','ret6':'price_ret6h'})
    g = pd.merge_asof(f.reset_index().sort_values('known_utc'), right.sort_values('h1_known_utc'),
                      left_on='known_utc', right_on='h1_known_utc', direction='backward', tolerance=pd.Timedelta('1h'))
    return g.set_index('open_utc')

def permit(f, name, side):
    if name == 'baseline': return pd.Series(True, index=f.index)
    if name == 'price_tema100': return side*(f.close-f.tema100)>0
    if name == 'tema_alignment': return (side*(f.close-f.tema100)>0)&(side*(f.tema50-f.tema100)>0)
    if name == 'flow_aligned': return f.delta6.notna()&(side*f.delta6>0)
    if name == 'no_opposing_flow_oi_drop':
        return f[['delta6','oi6']].notna().all(axis=1)&~((side*f.delta6<0)&(f.oi6<0))
    if name == 'h1_ema_confirmation': return side*(f.h1_close-f.h1_ema)>0
    if name == 'adx22': return f.adx>=22
    raise ValueError(name)

def gated(f, name):
    g=f.copy()
    g['long']=f.long&permit(f,name,1);g['short']=f.short&permit(f,name,-1)
    return g

def main():
    protocol=json.loads((P/'protocol.json').read_text())
    freeze_paths=[P/'protocol.json',P/'review.py',STAGED/'staged.py',OLD/'features.py',OLD/'engine.py',
                  OLD/'features_H4.parquet', OLD/'features_H1.parquet',STAGED/'B018_continuous_detail.json']
    for file in (OLD/'public_data').glob('*.json'):
        freeze_paths.append(file)
    freeze={str(x.relative_to(P.parent.parent)):hashlib.sha256(x.read_bytes()).hexdigest() for x in freeze_paths}
    if (P/'frozen_inputs.json').exists():
        assert json.loads((P/'frozen_inputs.json').read_text())==freeze, 'Inputs changed; preserve original run'
    else: dump('frozen_inputs.json',freeze)
    f=joined();cfg=json.loads((STAGED/'configs.json').read_text())['B018']
    baseline=json.loads((STAGED/'B018_continuous_detail.json').read_text())
    bytime=f.set_index('known_utc')
    names=list(protocol['hypotheses'])
    feature_cols=['close','ema','tema50','tema100','tema200','adx','slope','atr','lo','hi','width','oi','oi6','delta6','ls','ret1','ret5',
                  'available_utc','h1_ema','h1_close','h1_known_utc','price_ret6h']
    entries=[]
    for i,c in enumerate(baseline,1):
        r=bytime.loc[pd.Timestamp(c['entry_time'])]
        entry=dict(cycle=i,entry_time=c['entry_time'],exit_time=c['exit_time'],side=c['side'],net=c['net'],reason=c['reason'],filled=c['filled'])
        entry.update({k:r[k] for k in feature_cols})
        for name in names[1:]: entry[name]=bool(permit(r.to_frame().T,name,c['side']).iloc[0])
        entries.append(entry)
    entries=pd.DataFrame(entries);entries.to_csv(P/'all_entries_and_vetoes.csv',index=False)
    raw=candles('1h');h1=pd.read_parquet(OLD/'features_H1.parquet').set_index('known_utc')
    cases=[];snapshots=[]
    for i,c in enumerate(baseline,1):
        start=pd.Timestamp(c['entry_time']);end=pd.Timestamp(c['exit_time'])
        if not (start<pd.Timestamp('2026-08-01',tz='UTC') and c['net']<0): continue
        closed=raw.loc[(raw.index>=start)&(raw.index<end)]
        first=c['orders'][0]['fill'];side=c['side']
        fav=float(closed.high.max() if side==1 else closed.low.min())
        adverse=float(closed.low.min() if side==1 else closed.high.max())
        r=bytime.loc[start];si=f.index[f.known_utc==start][0];loc=f.index.get_loc(si)
        touch=f.iloc[max(0,loc-5):loc]
        touches=touch[(touch.low<=touch.lo*1.0015)&(touch.close>=touch.lo)] if side==1 else touch[(touch.high>=touch.hi*.9985)&(touch.close<=touch.hi)]
        during=bytime.loc[(bytime.index>start)&(bytime.index<=end)]
        cut=during[during.cut_long if side==1 else during.cut_short]
        case=dict(cycle=i,**c,entry_features={k:r[k] for k in feature_cols},
            prior_channel_touches=touches[['known_utc','high','low','close','lo','hi']].reset_index().to_dict('records'),
            favorable_price_before_exit_hour=fav,adverse_price_before_exit_hour=adverse,
            mfe_first_entry_pct=side*(fav/first-1)*100,mae_first_entry_pct=-side*(adverse/first-1)*100,
            first_leg_price_RR=side*(c['target']-first)/(side*(first-c['stop'])),
            target_outside_signal_channel=bool(c['target']>r.hi if side==1 else c['target']<r.lo),
            first_post_entry_directional_cut=None if cut.empty else dict(time=str(cut.index[0]),close=float(cut.iloc[0].close),ret1=float(cut.iloc[0].ret1),ret5=float(cut.iloc[0].ret5)),
            exit_hour_OHLC=raw.loc[end,['open','high','low','close']].to_dict())
        cases.append(case)
        points={start,end}|{pd.Timestamp(e['time']) for e in c['events']}|set(during.index)
        for time in sorted(points):
            # Events carry only the containing hour, not exact intrabar timestamps.
            a=bytime.loc[bytime.index<=time].iloc[-1];b=h1.loc[h1.index<=time].iloc[-1]
            snapshots.append(dict(cycle=i,time=time,events=';'.join(e['event']+(str(e.get('order',''))) for e in c['events'] if pd.Timestamp(e['time'])==time),
                H4_known=bytime.loc[bytime.index<=time].index[-1],H4_close=a.close,H4_ema=a.ema,H4_tema50=a.tema50,H4_tema100=a.tema100,H4_tema200=a.tema200,
                H4_adx=a.adx,H4_cut=bool(a.cut_long if side==1 else a.cut_short),H1_close=b.close,H1_ema=b.ema,
                delta6=b.delta6,oi6=b.oi6,ls=b.ls,price_ret6h=b.ret6,available_utc=b.available_utc))
        raw.loc[start-pd.Timedelta('48h'):end+pd.Timedelta('8h')].to_csv(P/f'case_{i:02d}_hourly.csv')
    dump('loss_cases.json',cases);pd.DataFrame(snapshots).to_csv(P/'loss_event_snapshots.csv',index=False)
    results=[];direct=[];changes=[]
    for name in names:
        g=gated(f,name)
        for period,(start,end) in protocol['periods'].items():
            metrics,cycles,eq,rejections=run(g,cfg,start,end,detail=True)
            results.append(dict(gate=name,period=period,costs=1,path='adverse',**metrics))
            if period=='continuous':
                dump(name+'_cycles.json',cycles);pd.DataFrame(eq).to_csv(P/(name+'_equity.csv'),index=False)
                if name=='baseline':
                    assert len(cycles)==len(baseline)
                    for a,b in zip(cycles,baseline):
                        assert (a['entry_time'],a['exit_time'],a['reason'])==(b['entry_time'],b['exit_time'],b['reason'])
                        assert abs(a['net']-b['net'])<1e-10
                old={(c['entry_time'],c['side']):c for c in baseline};new={(c['entry_time'],c['side']):c for c in cycles}
                for key in sorted(set(old)|set(new)):
                    a=old.get(key);b=new.get(key)
                    changes.append(dict(gate=name,entry_time=key[0],side=key[1],status='retained' if a and b else 'removed' if a else 'new',
                        baseline_net=a['net'] if a else None,replay_net=b['net'] if b else None))
        for mult,path in [(2.,'adverse'),(1.,'OHLC'),(1.,'OLHC')]:
            metrics=run(g,cfg,*protocol['periods']['continuous'],mult=mult,path=path)
            results.append(dict(gate=name,period='continuous',costs=mult,path=path,**metrics))
        if name!='baseline':
            blocked=entries[~entries[name]]
            direct.append(dict(gate=name,blocked_losses=int((blocked.net<0).sum()),blocked_wins=int((blocked.net>0).sum()),
                avoided_loss=float(-blocked.loc[blocked.net<0,'net'].sum()),foregone_gain=float(blocked.loc[blocked.net>0,'net'].sum()),
                deletion_only_net=float(entries.loc[entries[name],'net'].sum())))
        print(name, results[-4]['net'], flush=True)
    pd.DataFrame(results).to_csv(P/'replay_results.csv',index=False)
    pd.DataFrame(direct).to_csv(P/'direct_veto_cost.csv',index=False)
    pd.DataFrame(changes).to_csv(P/'replay_cycle_changes.csv',index=False)
    dump('run_summary.json',dict(baseline_reproduced=True,baseline_cycles=len(baseline),early_cycles=int((pd.to_datetime(entries.entry_time)<pd.Timestamp('2026-08-01',tz='UTC')).sum()),
         early_losses=len(cases),early_loss_sum=sum(c['net'] for c in cases),may_cycles=int((pd.to_datetime(entries.entry_time)<pd.Timestamp('2026-06-01',tz='UTC')).sum()),
         protocol_sha256=hashlib.sha256((P/'protocol.json').read_bytes()).hexdigest()))

if __name__=='__main__': main()

```
</details>

<details><summary>timing_stress.py</summary>

```python
"""Sensitivity to one EXTRA hour of market-data delay, after initial gate analysis."""
import hashlib, json
import pandas as pd
from review import P, STAGED, OLD, joined, gated, run, dump

if __name__=='__main__':
    protocol=dict(reason='Flow near zero on July 29 warrants a timing robustness check, not threshold optimization.',
        posthoc=True,extra_delay_hours=1,gates=['flow_aligned','no_opposing_flow_oi_drop'],
        unchanged='All price signals, stops, targets, quantities and exits; base OI delay is still present.')
    dump('timing_stress_protocol.json',protocol)
    f=joined();h=pd.read_parquet(OLD/'features_H1.parquet').set_index('known_utc')
    cfg=json.loads((STAGED/'configs.json').read_text())['B018']
    # Exactly the previous hourly published feature, not a full H4 shift.
    old=h[['oi6','delta6']].reindex(pd.DatetimeIndex(f.known_utc)-pd.Timedelta('1h'))
    g=f.copy();g[['oi6','delta6']]=old.to_numpy()
    rows=[];entries=[]
    cases=json.loads((P/'baseline_cycles.json').read_text())
    for name in protocol['gates']:
        altered=gated(g,name)
        for period,(start,end) in json.loads((P/'protocol.json').read_text())['periods'].items():
            rows.append(dict(gate=name,period=period,extra_delay_hours=1,**run(altered,cfg,start,end)))
        bytime=altered.set_index('known_utc')
        for c in cases:
            r=bytime.loc[pd.Timestamp(c['entry_time'])]
            entries.append(dict(gate=name,entry_time=c['entry_time'],side=c['side'],net=c['net'],
                oi6=r.oi6,delta6=r.delta6,allowed=bool(r.long if c['side']==1 else r.short)))
    pd.DataFrame(rows).to_csv(P/'timing_stress_results.csv',index=False)
    pd.DataFrame(entries).to_csv(P/'timing_stress_entries.csv',index=False)
    dump('timing_stress_hashes.json',{name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ['timing_stress.py','timing_stress_protocol.json']})
    print(pd.DataFrame(rows)[['gate','period','net','cycles','wins']].to_string(index=False))

```
</details>

<details><summary>test_review.py</summary>

```python
"""Causality/accounting checks for a financial retrospective, not bot tests."""
import hashlib,json
import numpy as np
import pandas as pd
import pytest
from review import P, OLD, STAGED, joined, permit, gated
from features import technical, candles, signals
from staged import BASE

@pytest.fixture(scope='module')
def frame(): return joined()

def test_frozen_inputs_unchanged():
    for rel,sha in json.loads((P/'frozen_inputs.json').read_text()).items():
        assert hashlib.sha256((P.parents[1]/rel).read_bytes()).hexdigest()==sha,rel

def test_original_twelve_cycles_reproduced():
    old=json.loads((STAGED/'B018_continuous_detail.json').read_text());new=json.loads((P/'baseline_cycles.json').read_text())
    assert old==new

@pytest.mark.parametrize('time',['2026-06-12 20:00Z','2026-07-07 08:00Z','2026-07-29 12:00Z'])
def test_features_and_signals_do_not_need_future(time,frame):
    t=pd.Timestamp(time);raw=candles('4h');past=raw[raw.index+pd.Timedelta('4h')<=t]
    short=technical(past,'4h');full=technical(raw,'4h')
    cols=['ema','tema50','tema100','tema200','atr','adx','lo','hi','slope','ret1','ret5']
    pd.testing.assert_frame_equal(short[cols],full.loc[short.index,cols])
    truncated=frame[frame.known_utc<=t]
    pd.testing.assert_frame_equal(signals(truncated,BASE),signals(frame,BASE).loc[truncated.index])
    for name in json.loads((P/'protocol.json').read_text())['hypotheses']:
        pd.testing.assert_frame_equal(gated(truncated,name),gated(frame,name).loc[truncated.index])

def test_asof_availability(frame):
    f=frame.loc['2026-05-01':'2026-10-31']
    assert f[['available_utc','h1_known_utc','oi6','delta6']].notna().all().all()
    assert (f.available_utc<=f.known_utc).all()
    assert (f.h1_known_utc<=f.known_utc).all()
    assert (f.h1_known_utc==f.known_utc).all()

@pytest.mark.parametrize('time',['2026-06-12 20:00Z','2026-07-07 08:00Z','2026-07-29 12:00Z'])
def test_raw_oi_and_flow_windows(time,frame):
    t=pd.Timestamp(time);r=frame.set_index('known_utc').loc[t]
    oi=pd.DataFrame(json.loads((OLD/'public_data/oi.json').read_text()))
    oi.index=pd.to_datetime(oi.timestamp.astype('int64'),unit='ms',utc=True)
    oi=oi.openInterest.astype(float)
    assert r.oi==oi.loc[t-pd.Timedelta('1h')]
    np.testing.assert_allclose(r.oi6,100*(oi.loc[t-pd.Timedelta('1h')]/oi.loc[t-pd.Timedelta('7h')]-1))
    b=json.loads((OLD/'public_data/binance_1h.json').read_text())
    window=[x for x in b if t-pd.Timedelta('6h')<=pd.Timestamp(x[0],unit='ms',tz='UTC')<t]
    assert len(window)==6
    expected=100*(2*sum(float(x[10]) for x in window)/sum(float(x[7]) for x in window)-1)
    np.testing.assert_allclose(r.delta6,expected,rtol=0,atol=1e-11)

def test_missing_flow_is_not_a_permission(frame):
    f=frame.tail(3).copy();f['oi6']=np.nan;f['delta6']=np.nan
    for side in [-1,1]:
        assert not permit(f,'flow_aligned',side).any()
        assert not permit(f,'no_opposing_flow_oi_drop',side).any()

def test_cycle_accounting_and_replay_vs_deletion():
    r=pd.read_csv(P/'replay_results.csv');direct=pd.read_csv(P/'direct_veto_cost.csv').set_index('gate')
    for name in json.loads((P/'protocol.json').read_text())['hypotheses']:
        cycles=json.loads((P/(name+'_cycles.json')).read_text())
        m=r[(r.gate==name)&(r.period=='continuous')&(r.costs==1)&(r.path=='adverse')].iloc[0]
        assert abs(m.net-sum(c['net'] for c in cycles))<1e-9
        for c in cycles:
            assert c['closed']
            assert abs(c['net']-(c['gross']-c['fees']+c['funding']))<1e-9
            assert abs(c['net']-sum(o.get('net',0) for o in c['orders']))<1e-9
        # Specific observed equality; not a general claim about gated strategies.
        if name!='baseline': assert abs(m.net-direct.loc[name,'deletion_only_net'])<1e-9
    changes=pd.read_csv(P/'replay_cycle_changes.csv');assert not (changes.status=='new').any()

def test_loss_labels_and_stop_bar():
    cases=json.loads((P/'loss_cases.json').read_text())
    assert [c['reason'] for c in cases]==['stop','time','stop']
    for c in cases:
        if c['reason']=='stop':
            b=c['exit_hour_OHLC'];assert b['low']<=c['stop']<=b['high']
        else:
            assert pd.Timestamp(c['exit_time'])-pd.Timestamp(c['entry_time'])==pd.Timedelta('80h')

def test_path_sensitivity_results():
    r=pd.read_csv(P/'replay_results.csv');r=r[(r.period=='continuous')&(r.costs==1)]
    for name,g in r.groupby('gate'):
        assert len(g)==3 and g.net.max()-g.net.min()<1e-9

```
</details>
