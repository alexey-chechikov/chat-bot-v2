# S&P 500, золото и нефть в разборе режимов BTC

**Дополнение от 02.11.2026 для Claude.** Поручение оператора: добавить корреляцию S&P 500, золота и нефти к анализу тех же графиков. Основной отчёт: [режимы рынка и правила сеток](WEEX_GPT_MARKET_REGIMES_AND_GRID_RULES_2026-11-02.md), коммит `df78486f7a6800a28da261f8d2048f23f2e3c014`.

## 1. Результат

Добавлен отдельный блок внешнего рынка. На **94 общих сессиях с 1 мая по 15 сентября 2026 года** одновременная корреляция доходностей BTC с S&P 500 составила **+0,375**, с золотом **+0,526**, с WTI **−0,085**.

**Это контекст режима, а не установленный опережающий торговый сигнал.** Связь завершившегося движения внешнего рынка с последующим движением BTC слабая; интервалы неопределённости включают ноль для всех трёх рынков. В августе одновременная связь BTC с S&P 500 почти исчезла: месячная корреляция **−0,030**. Жёсткий запрет LONG/SHORT только по направлению индекса этим исследованием не оправдан.

На этом участке золото двигалось с BTC согласованнее, чем S&P 500. Это не делает золото постоянным ведущим индикатором и не означает, что оно всегда защищает от падения BTC. Для нефти предположение о стабильной обратной связи не подтвердилось.

Ни торговый код, ни живые настройки, ордера или процессы не менялись. Модель сеток не переобучалась, новые параметры по результату не подбирались.

## 2. Какие инструменты и почему

| Рынок | Основной ряд | Дополнительная проверка | Ограничение |
|---|---|---|---|
| BTC | Binance USD-M BTCUSDT, сохранённые H1 из основного исследования | Те же цены и период, что в отчёте режимов | Не лента исполнения WEEX. |
| S&P 500 | Денежный индекс `^GSPC` | Проверка календаря и единого момента закрытия | Не фьючерс ES, не круглосуточный CFD. |
| Золото | Yahoo `GC=F`, H1 close ровно к закрытию американской фондовой сессии | GLD, цена акции фонда в тот же момент | GC — фьючерсный ряд поставщика; правила исторической склейки контрактов не верифицированы. GLD не точная копия spot/futures. |
| Нефть | WTI `CL=F`, тот же H1 срез | USO в тот же момент | Нефть в этой проверке — WTI, не Brent. USO — фонд с фьючерсами, расходами и эффектом перекладки, не сама нефть. |

Данные Yahoo получены через публичный chart endpoint. Для пяти инструментов сохранены дневные массивы, а для GC/CL дополнительно часовые: по **3 986 меток времени** с марта до середины сентября. В расчёт вошли только согласованные срезы, а не все часы подряд. Дневные GC/CL **не использовались в основной корреляции**, поскольку их дневной close/settlement не обязан совпадать с 16:00 Нью-Йорка.

GLD создан для отражения цены золотого bullion за вычетом расходов; для USO существенны фьючерсный benchmark и перекладка. Поэтому результаты фондов показаны отдельными строками. [Описание GLD](https://www.spdrgoldshares.com/usa/gld/), [описание USO](https://www.uscfinvestments.com/uso).

У непрерывных фьючерсных рядов существует выбор между front/active contract и правилами смены контракта; он может менять траекторию ряда. Мы не считаем название `GC=F` доказательством конкретной методики склейки и не удаляем неудобные скачки вручную. [CME: continuous price series](https://www.cmegroup.com/market-data/cme-group-continuous-price-series.html).

## 3. Как устранено ложное совпадение по времени

Для каждого дня из календаря S&P 500 берётся **16:00 America/New_York**. В исследуемом мае–сентябре это **20:00 UTC**:

- S&P 500, GLD и USO — рыночный close основной сессии;
- BTC, GC и CL — close часовой свечи, которая **закончилась** ровно в этот момент;
- доходность — `ln(P_t/P_previous_session)` для всех инструментов между одинаковыми временными границами;
- выходные и праздники не заполняются нулевой доходностью или повтором пятничной цены;
- понедельничная доходность включает интервал с предыдущего закрытия, в том числе выходные BTC. Это одинаковый elapsed-time интервал, хотя ликвидность и возможность торговли различны.

Дневной timestamp Yahoo у индекса/ETF обозначает начало дневной свечи: его нельзя использовать как момент, когда уже было известно дневное закрытие. Для этого и назначен отдельный close-anchor. В данном периоде по календарю NYSE нет запланированных ранних закрытий; 3 апреля, 25 мая, 19 июня, 3 июля и 7 сентября исключены из соответствующей подготовленной истории. [NYSE: календарь и часы](https://www.nyse.com/trade/hours-calendars).

Для проверки опережения сравниваем завершившуюся внешнюю доходность с движением BTC **от часа после закрытия** до часа после следующего закрытия. Это один заранее выбранный лаг с запасом времени на доступность данных. Дополнительно посчитан следующий фиксированный интервал 24H после того же часового запаса. Из дневного исследования не делается вывод об опережении на 15 минут или 1–4 часа.

На 15 сентября последующего BTC-интервала уже недостаточно, поэтому в таблице опережения **93 пары**, а не 94. Пропуски не превращались в нули. Реальная задержка публикации/исторических исправлений Yahoo неизвестна; один час — допущение исследования, не доказательство first-seen.

## 4. Общая связь и проверка опережения

| Ряд | N | Одновременная Pearson | 95% блочный интервал | Связь с последующей сессией BTC, N=93 | 95% интервал опережения |
|---|---|---|---|---|---|
| S&P 500 | 94 | +0.375 | [+0.184; +0.540] | -0.121 | [-0.316; +0.117] |
| Золото GC=F | 94 | +0.526 | [+0.372; +0.651] | +0.040 | [-0.178; +0.246] |
| Нефть WTI CL=F | 94 | -0.085 | [-0.248; +0.072] | +0.067 | [-0.121; +0.244] |
| GLD, проверка золота | 94 | +0.534 | [+0.384; +0.656] | +0.036 | [-0.183; +0.246] |
| USO, проверка нефти | 94 | -0.103 | [-0.269; +0.058] | +0.049 | [-0.142; +0.229] |

Интервалы — описательный paired circular moving-block bootstrap: блок 5 сессий, 2 000 повторов, фиксированный seed. Он учитывает часть зависимости соседних наблюдений, но не является доказательством стационарности и не скорректирован за множество рассматриваемых связей/окон. Правила расчёта зафиксированы до просмотра коэффициентов; сам период и движения BTC уже были известны из предыдущего разбора. Это не независимый out-of-sample.

Проверка ранговой корреляцией Spearman дала тот же общий порядок: S&P **+0,363**, золото **+0,511**, WTI **−0,112**. Это дополнительная проверка того, что результат Pearson не определяется только одним масштабом экстремального дня; она не устраняет всю чувствительность к выбросам.

GLD повторяет результат золота (**+0,534**), USO — слабую отрицательную связь нефти (**−0,103**). Согласованность альтернативных инструментов полезна, но не доказывает отсутствие проблем склейки у GC/CL и не создаёт независимую выборку рынков.

Корреляции завершённого макродвижения со **следующими 24H BTC**: S&P **−0,098**, золото **+0,077**, WTI **+0,097**. Сильного опережающего эффекта на этом выбранном горизонте также не видно. Нельзя заменять слабое опережение значительно большей одновременной корреляцией в презентации модели.

## 5. Связь меняется вместе с режимом

| Месяц | N сессий | BTC–S&P | BTC–золото | BTC–WTI |
|---|---|---|---|---|
| 2026-05 | 20 | +0.339 | +0.096 | -0.038 |
| 2026-06 | 21 | +0.490 | +0.503 | -0.096 |
| 2026-07 | 22 | +0.460 | +0.712 | -0.298 |
| 2026-08 | 21 | -0.030 | +0.536 | +0.000 |
| 2026-09 | 10 | +0.668 | +0.477 | -0.369 |

В сентябрьской строке только 10 сессий до 15 числа; её нельзя представлять как результат полного сентября или устойчивую оценку. Майская связь BTC с золотом около **+0,096**, июльская **+0,712** — правило «BTC всегда следует золоту» не описывает даже этот короткий период одинаково.

Скользящие корреляции на последних **20 общих сессиях** менялись в диапазонах:

- S&P 500: **−0,143…+0,653**;
- золото: **+0,096…+0,772**;
- WTI: **−0,625…+0,165**.

Диапазоны рассчитаны при последовательном движении окна; это не 94 независимые оценки. 60-сессионная оценка использует более длинный прошлый контекст. На 15 сентября она составляла соответственно **+0,311 / +0,597 / −0,143**. Это исторический срез на конец исследования, **не состояние рынка 2 ноября**.

## 6. Дополнение к конкретным участкам пользователя

В таблице каждый отрезок составлен из межсессионных доходностей, **заканчивающихся** в соответствующие даты. Первая доходность начинается на предыдущем закрытии, которое может быть до первого дня подписи. Поэтому цифры BTC здесь закономерно отличаются от полного UTC open→close в основном отчёте. Все четыре рынка внутри одной строки имеют одинаковые границы.

| Окно | N | BTC | S&P 500 | Золото GC | WTI CL |
|---|---|---|---|---|---|
| 6–9 мая | 3 | -1.72% | +1.92% | +3.67% | -7.66% |
| 10–13 мая | 3 | -0.68% | +0.61% | -0.79% | +6.80% |
| 12–22 мая | 9 | -7.43% | +0.82% | -4.92% | -2.08% |
| 31 мая–6 июня | 5 | -17.99% | -2.59% | -5.10% | +2.45% |
| 7–11 июня | 4 | +5.48% | +0.14% | -2.62% | -4.11% |
| 12–15 июня | 2 | +4.74% | +2.16% | +2.66% | -6.02% |
| 16 июня–1 июля | 11 | -9.88% | -0.94% | -6.68% | -16.36% |
| 2 июля–15 августа | 31 | +4.89% | +4.04% | +9.36% | +21.14% |
| 19–25 августа | 5 | +22.08% | -0.19% | +7.35% | -3.53% |
| 26 августа–11 сентября | 12 | -2.08% | -0.26% | -7.04% | +24.04% |

### 6–9 и 10–13 мая

На 6–9 мая BTC снизился примерно на 1,73%, тогда как S&P вырос на 1,93%, золото — на 3,67%; WTI упала на 7,66%. BTC был слаб относительно индекса и золота. Это контекст в пользу поиска собственной причины слабости крипторынка в его структуре/потоке, а не основание автоматически покупать BTC вслед за индексом. Здесь всего 3 межсессионных наблюдения: коэффициент корреляции отдельного отрезка не публикуется.

На 10–13 мая сочетание другое: BTC −0,68%, S&P +0,61%, золото −0,79%, нефть +6,80%. Единого «все внешние рынки за шорт BTC» нет. Это пример, почему нельзя назначить фиксированные голоса направления каждому активу.

### 12–22 мая

BTC −7,43%, S&P +0,82%, золото −4,92%. Относительная слабость BTC к акциям существенна; дневной индекс сам по себе не объясняет его падение. Золото движется в ту же сторону, но это ещё не доказательство общего причинного фактора. Сохраняются только 9 интервалов — слишком мало для отдельной устойчивой корреляции.

### 31 мая–6 июня и отскок 7–15 июня

В начальном обвале BTC около −17,99%, S&P −2,59%, золото −5,10%, WTI +2,45%. Совместное снижение BTC, акций и золота **совместимо** с более широким стрессом, но причина не установлена: для уверенного объяснения понадобились бы дополнительные источники по доллару, ставкам/доходностям и событиям. Новые активы в это поручение автоматически не добавлялись.

В отскоке 7–11 июня BTC +5,47% при S&P +0,14% и золоте −2,61%. Если требовать, чтобы перед покрытием short сначала развернулись все внешние рынки, можно пропустить локальное восстановление BTC. На 12–15 июня направление BTC, S&P и золота уже совпало вверх, но там только 2 наблюдения.

### 16 июня–1 июля

BTC −9,88%, золото −6,68%, WTI −16,36%, S&P −0,94%. Тезис «это безопасный флет» снова не поддерживается. Корреляция BTC с золотом на 11 интервалах около +0,506, с S&P +0,174, с нефтью +0,052. Даже одновременное снижение нефти и BTC между концами окна **не означает сильную корреляцию их отдельных движений**.

### 2 июля–15 августа

S&P +4,04%, золото +9,36%, WTI +21,14%, BTC +4,89%. Внешние рынки росли, а BTC большую часть времени колебался в широком диапазоне. Связь доходностей BTC с S&P +0,462, с золотом +0,587, с WTI −0,334 на 31 интервале. Растущая нефть не даёт универсальной команды LONG BTC. Для диапазонных сеток важны собственные границы BTC и их отмена; внешний фон не заменяет их.

### 19–25 августа

BTC **+22,09%**, золото **+7,35%**, S&P **−0,19%**, WTI **−3,53%** на совпадающих межсессионных границах. Это важнейший контрпример жёсткому подтверждению со стороны S&P. Сильный пробой BTC нельзя отменить только потому, что индекс за тот же отрезок не вырос. Связь с золотом видима, но 5 точек не позволяют доказать, что золото заранее предсказало пробой.

### 26 августа–11 сентября

BTC −2,08%, S&P −0,26%, золото −7,04%, WTI +24,04%. На 12 интервалах BTC сильнее двигался вместе с S&P/золотом (корреляции около +0,726/+0,771), чем с нефтью (−0,091). Эта связь пригодна для описания уже наблюдаемого режима; нельзя задним числом применить её как известную ещё 19 августа.

## 7. Как добавить блок в индикатор сеток

### Данные, доступные к решению

Хранить для каждого внешнего ряда: точный symbol/venue, тип spot/index/future/fund, session close, bar start/end, publication/received time, возраст последнего наблюдения, market_open, наличие пропуска и roll flag. В выходные/праздники последнее закрытие индекса — **старый контекст**, а не новый нулевой сигнал. H1-сигнал до закрытия американской сессии не может читать её будущий дневной результат.

### Признаки-кандидаты

1. Завершённые доходности рынка за 1 и 5 сессий; их волатильность относительно прошлых 60 сессий.
2. `corr20` и `corr60` изменений BTC и каждого рынка; абсолютный уровень связи, знак и изменение знака. Для 60-сессионного признака нужно 60 полных прошлых пар — ранние строки текущей истории его ещё не имеют.
3. Относительная сила BTC: разница BTC-return и объясняемой внешним рынком части. Например, beta оценивается **на предыдущих 60 парах без текущей**; текущий residual вычисляется только после завершения текущего совместного интервала. Не называть residual причинным «чистым криптопотоком».
4. Флаги согласованности и расхождения: BTC растёт при падающем S&P, BTC падает при растущем золоте и т.п.; это описания ситуации, а не готовые LONG/SHORT-ярлыки.

Не складывать «S&P растёт», «S&P выше средней», «корреляция с S&P» в три независимых голоса. Аналогично GC и GLD — две реализации одного близкого контекста, не два независимых подтверждения.

### Влияние на решения

| Ситуация | Кандидатное применение | Чего не делать |
|---|---|---|
| BTC и связанный с ним рынок вместе падают, собственная структура BTC DOWN | Контекст для существующей short-гипотезы и ограничения риска встречного LONG | Не открывать short только по красной свече S&P без уровня, отмены и полного учёта сетки. |
| BTC теряет поддержку при растущем S&P/золоте | Зафиксировать относительную слабость; проверить OI, исполненный поток и неудачные возвраты | Не объявлять неизбежный догоняющий рост BTC. |
| BTC пробивает вверх, S&P стоит или снижается | Проверить собственный пробой/ретест BTC и свежесть связи; не вводить автоматический запрет LONG | Не заставлять BTC ждать согласия индекса, как показал август. |
| Золото падает вместе с BTC при положительной актуальной корреляции | Дополнительный риск-контекст, не защитный актив по умолчанию | Не считать LONG золота гарантированным hedge BTC. |
| Нефть резко растёт | Отметить шок/изменение внешнего фона, проверить текущую связь | Не кодировать «нефть вверх → BTC вниз»: здесь стабильного общего закона не установлено. |
| RANGE BTC, внешние рынки активны | Следить за расширением волатильности и собственным пробоем границ BTC | Не расширять границы сетки и не отменять её стоп ради внешнего объяснения. |

Предлагаемый экспериментальный gate доверия к макросвязи: минимум 60 завершённых пар, одинаковый знак corr20/corr60 и `abs(corr60)>=0,30`; stale/roll uncertainty выводится отдельно. **Порог 0,30 — новая проверяемая гипотеза, не оптимизированный результат этой работы.** На данном этапе блок следует показывать как контекст; его автоматическое влияние на размер, допуск или закрытие сетки сначала сравнить отдельно.

## 8. Задание Claude и критерий полезности

Добавить в прежний протокол ровно одно парное сравнение: **та же структурная/деривативная политика без макроблока и с макроблоком**, с тем же капиталом, исполнением, комиссиями, funding и выходом остатка. Отдельно проверить защиту уже открытой позиции и допуск нового входа: это разные решения.

Сначала проверить корректность часов, биржевого календаря и roll-метаданных. Затем показать добавочный net, просадку, число подавленных/разрешённых циклов, пропущенные хорошие входы и самые плохие ошибки. Обязательные контрпримеры — июньский отскок без согласия золота и августовский рост без роста S&P. Добавление красивого корреляционного графика само по себе не доказывает полезность фильтра.

Не запускать новый массовый перебор десятков рынков и лагов. Лаги/окна этого дополнения зафиксированы; увеличение набора является новым исследованием. История уже просмотрена, поэтому подтверждение преимуществ требует заранее зафиксированных правил и нового периода/forward shadow. Авторизация на живые сделки и динамические ордера не менялась.

## 9. Проверки и воспроизведение

Прошли **22 проверки**: полнота согласованных цен, правильный час закрытия, отсутствие выходных и пяти праздников, соответствие BTC сырому часовому close, независимая формула Pearson для пяти внешних рядов, неизменность исторических rolling-признаков при двух обрезаниях будущего на каждый ряд, проверка цены будущего результата после задержки и запрет корреляций при N<10. Это проверки вычислений, не тест прибыльности сеток.

Скользящая связь показана в локальном `C:/bot7/research/macro_context_20261102/macro_context.png`; исходные JSON, provenance, protocol, CSV и checks сохранены в том же каталоге. В Git публикуется один самодостаточный отчёт. Для повторения нужны файлы BTC из основного отчёта: его публичный загрузчик сохранён в приложении к коммиту `df78486`.

| Raw JSON | SHA256 |
|---|---|
| CL_F.json | aef1004900dc6ab62d0830669c5e379ef05a5af2b5d8159ca12d37dcf5fead75 |
| CL_F_1h.json | c10e244b2d5749ba7fa790ce17193ee2a0f87d25b73d05161ca49ef08680d779 |
| GC_F.json | f5c3aefcb0b8ff02cec75ab6d6a8d329c57c84dafa4f0b4da672a31d0f076906 |
| GC_F_1h.json | 37dd66d442dd233bac7fab71229f79f994a93b39c27e07a66929b29a495a5eb5 |
| GLD.json | 5cc77c0a148b820de83dc0e3c0c9463ef6b83b1495688e70c6bb14711ba5920d |
| GSPC.json | 1a0de45f15642f4456988d1445b8955a91c6b3802a96404fcac4ea2f300e36b3 |
| USO.json | 495781fbbe33366e988509dda50a1537d7ac6598279fe2a3e2c3167a86349e67 |

Поставщик котировок: [S&P 500](https://finance.yahoo.com/quote/%5EGSPC/history/), [золото](https://finance.yahoo.com/quote/GC%3DF/history/), [WTI](https://finance.yahoo.com/quote/CL%3DF/history/). URL chart-запросов и время получения сохраняются в `public_data/provenance.json`. SHA фиксирует использованную выгрузку; более поздняя история поставщика может быть пересмотрена.


Сначала воспроизвести публичный BTC-набор из основного отчёта в `research/market_regimes_review_20261102/public_data/btc_1h.json`. Следующие файлы сохранить в соседний `research/macro_context_20261102`. Нужны Python, numpy, pandas, scipy и matplotlib. Запустить `fetch_macro.py`, затем `analyze_macro.py`; торговые службы не импортируются.

### `protocol.json`

```json
{
  "task": "Add SP500, gold and oil context to the selected BTC May-September 2026 windows",
  "status": "Descriptive historical analysis, not untouched out-of-sample or a fitted trading strategy",
  "freeze": "Before computing correlations; charts and BTC outcomes already known",
  "primary": ["SP500 ^GSPC cash close", "GC=F hourly close at NY16:00", "CL=F hourly close at NY16:00"],
  "robustness": ["GLD market close", "USO market close"],
  "clock": "NYSE session close 16:00 America/New_York; BTC last completed H1 close at exactly the same anchor. No market forward fill. May-Sep2026 calendar has no scheduled NYSE early closes.",
  "return": "Natural log return between consecutive common NYSE close anchors; weekends included in the elapsed interval for every instrument",
  "window": ["2026-05-01", "2026-09-15"],
  "rolling_sessions": [20,60],
  "lead": "Past completed market return at session t vs BTC from t+1h to next scheduled NYSE close+1h; also 24h horizon, allowing one hour after close for availability. No intraday lead inferred.",
  "windows": "Reuse the 10 windows from the published Nov2 BTC report; suppress small-window correlation when N<10",
  "uncertainty": "Paired circular moving block bootstrap length5 sessions, 2000 draws, seed20261102; intervals descriptive, no multiplicity-adjusted claim",
  "limits": ["Continuous-futures roll methodology unverified", "Yahoo revisions and first-seen unavailable", "USO is a fund with futures/roll effects, not WTI spot", "No grid PnL inferred from correlation", "No automatic macro risk switch deployed"]
}
```

### `fetch_macro.py`

```python
"""Public market research, fixed historical window. No account endpoints."""
from pathlib import Path
from datetime import datetime, timezone
import urllib.parse, urllib.request, json, hashlib
P=Path(__file__).resolve().parent/'public_data'
P.mkdir(parents=True,exist_ok=True)
def sec(s):return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
meta=[]
for symbol,interval in [(s,'1d') for s in ['^GSPC','GLD','USO','GC=F','CL=F']]+[('GC=F','1h'),('CL=F','1h')]:
    name=symbol.replace('^','').replace('=','_')+('_1h' if interval=='1h' else '')+'.json'
    if (P/name).exists(): continue
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')+'?'+urllib.parse.urlencode(dict(period1=sec('2026-03-01'),period2=sec('2026-09-17'),interval=interval,includePrePost='false',events='div,splits'))
    rec={'symbol':symbol,'interval':interval,'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as r:raw=r.read()
        obj=json.loads(raw);result=obj['chart']['result'][0]
        (P/name).write_bytes(raw)
        rec.update(status='ok',rows=len(result['timestamp']),sha256=hashlib.sha256(raw).hexdigest())
    except Exception as e:rec.update(status='unavailable',error=str(e))
    meta.append(rec)
    print(json.dumps(rec))
existing=json.loads((P/'provenance.json').read_text()) if (P/'provenance.json').exists() else []
(P/'provenance.json').write_text(json.dumps(existing+meta,indent=2),encoding='utf-8')
```

### `analyze_macro.py`

```python
"""Aligned session-close research. Correlation, not grid PnL or causal attribution."""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

P=Path(__file__).resolve().parent
PREV=P.parent/'market_regimes_review_20261102'
def load(symbol,hourly=False):
    name=symbol.replace('^','').replace('=','_')+('_1h' if hourly else '')+'.json'
    obj=json.loads((P/'public_data'/name).read_text())['chart']['result'][0]
    idx=pd.to_datetime(obj['timestamp'],unit='s',utc=True)
    if hourly:
        assert (idx.minute==0).all(), 'Unexpected hourly anchoring'
        idx=idx+pd.Timedelta(hours=1)
    else:
        dates=idx.tz_convert('America/New_York').strftime('%Y-%m-%d')
        idx=pd.DatetimeIndex(pd.to_datetime(dates+' 16:00:00')).tz_localize('America/New_York').tz_convert('UTC')
    s=pd.Series(obj['indicators']['quote'][0]['close'],index=idx,name=symbol,dtype=float)
    assert s.index.is_unique and (s.dropna()>0).all()
    return s.sort_index()
raw=json.loads((PREV/'public_data/btc_1h.json').read_text())
btc=pd.Series([float(x[4]) for x in raw],index=pd.to_datetime([x[0]+3600000 for x in raw],unit='ms',utc=True),name='BTC')
sp=load('^GSPC');idx=sp.index
prices=pd.DataFrame({'BTC':btc.reindex(idx),'SP500':sp,'GOLD_F':load('GC=F',True).reindex(idx),
                     'WTI_F':load('CL=F',True).reindex(idx),'GLD':load('GLD').reindex(idx),'USO':load('USO').reindex(idx)})
prices=prices.loc['2026-04-01':'2026-09-15']
# Keep all scheduled cash-session anchors before differencing: a missing value is not bridged or filled.
r=np.log(prices/prices.shift(1))
lead=pd.Series(index=idx,dtype=float)
for j,t in enumerate(idx[:-1]):
    a=t+pd.Timedelta(hours=1);b=idx[j+1]+pd.Timedelta(hours=1)
    if a in btc.index and b in btc.index:lead.loc[t]=np.log(btc.loc[b]/btc.loc[a])
f24=pd.Series({t:np.log(btc.loc[t+pd.Timedelta(hours=25)]/btc.loc[t+pd.Timedelta(hours=1)])
              for t in idx if t+pd.Timedelta(hours=25) in btc.index and t+pd.Timedelta(hours=1) in btc.index})
r['btc_next_session_after1h']=lead.reindex(r.index)
r['btc_next24_after1h']=f24.reindex(r.index)
r.to_csv(P/'aligned_returns.csv');prices.to_csv(P/'aligned_prices.csv')

def block_ci(x,y):
    a=np.column_stack([x,y]);a=a[np.isfinite(a).all(axis=1)];n=len(a)
    rng=np.random.default_rng(20261102);out=[]
    for _ in range(2000):
        starts=rng.integers(0,n,size=(n+4)//5)
        ii=np.concatenate([(j+np.arange(5))%n for j in starts])[:n]
        z=a[ii]
        if (z.std(axis=0)>0).all():out.append(np.corrcoef(z.T)[0,1])
    return np.quantile(out,[.025,.975]).tolist()

summary=[]
sample=r.loc['2026-05-01':'2026-09-15']
for s in ['SP500','GOLD_F','WTI_F','GLD','USO']:
    a=sample[['BTC',s]].dropna()
    ci=block_ci(a.BTC,a[s]);t20=r.BTC.rolling(20,min_periods=20).corr(r[s]);t60=r.BTC.rolling(60,min_periods=60).corr(r[s])
    a1=sample[[s,'btc_next_session_after1h']].dropna();ci1=block_ci(a1[s],a1.btc_next_session_after1h)
    summary.append(dict(asset=s,n=len(a),pearson=a.BTC.corr(a[s]),spearman=spearmanr(a.BTC,a[s]).statistic,
      lo=ci[0],hi=ci[1],lead_n=len(a1),lead_next_session=a1[s].corr(a1.btc_next_session_after1h),lead_lo=ci1[0],lead_hi=ci1[1],
      lead24=sample[s].corr(sample.btc_next24_after1h),rolling20_min=t20.loc[sample.index].min(),rolling20_max=t20.loc[sample.index].max(),
      latest20=t20.loc[sample.index].dropna().iloc[-1],latest60=t60.loc[sample.index].dropna().iloc[-1],
      first_half=sample.loc[:'2026-06-30','BTC'].corr(sample.loc[:'2026-06-30',s]),
      second_half=sample.loc['2026-07-01':,'BTC'].corr(sample.loc['2026-07-01':,s])))
pd.DataFrame(summary).to_csv(P/'correlations.csv',index=False)
windows=pd.read_csv(PREV/'windows.csv')
wr=[]
for row in windows.itertuples():
    z=r.loc[(r.index>=row.start)&(r.index<row.end_exclusive),['BTC','SP500','GOLD_F','WTI_F']].dropna()
    out={'name':row.name,'n':len(z),'first_anchor':str(z.index.min()),'last_anchor':str(z.index.max())}
    for s in z:
        out[s+'_change_pct']=np.expm1(z[s].sum())*100
        if s!='BTC':out[s+'_corr']=z.BTC.corr(z[s]) if len(z)>=10 else None
    wr.append(out)
pd.DataFrame(wr).to_csv(P/'window_macro.csv',index=False)
monthly=[]
for month,z in sample.groupby(sample.index.strftime('%Y-%m')):
    for s in ['SP500','GOLD_F','WTI_F']:
        a=z[['BTC',s]].dropna();monthly.append(dict(month=month,asset=s,n=len(a),corr=a.BTC.corr(a[s]) if len(a)>=10 else None))
pd.DataFrame(monthly).to_csv(P/'monthly.csv',index=False)

# Tests address timing, contamination and the independently evaluated arithmetic.
checks=[]
def check(name,ok):assert bool(ok),name;checks.append({'check':name,'passed':True})
check('Primary session anchors have no missing prices',prices[['BTC','SP500','GOLD_F','WTI_F']].notna().all().all())
check('All May-Sep anchors at NY16:00 / UTC20:00',bool((prices.index.tz_convert('America/New_York').hour==16).all()))
check('Weekend cash sessions are absent',bool((prices.index.dayofweek<5).all()))
check('Five official holiday dates absent',not any(x in set(prices.index.strftime('%Y-%m-%d')) for x in ['2026-04-03','2026-05-25','2026-06-19','2026-07-03','2026-09-07']))
check('BTC close is raw H1 close ending at the anchor',all(btc.loc[t]==prices.loc[t,'BTC'] for t in prices.index))
for s in ['SP500','GOLD_F','WTI_F','GLD','USO']:
    a=sample[['BTC',s]].dropna();x=a.BTC.to_numpy();y=a[s].to_numpy()
    manual=np.sum((x-x.mean())*(y-y.mean()))/np.sqrt(np.sum((x-x.mean())**2)*np.sum((y-y.mean())**2))
    check('Independent Pearson '+s,abs(manual-a.BTC.corr(a[s]))<1e-12)
    for cut in [50,90]:
        c=r.iloc[:cut];got=c.BTC.rolling(20,min_periods=20).corr(c[s])
        full=r.BTC.rolling(20,min_periods=20).corr(r[s]).iloc[:cut]
        check('Past-only rolling prefix '+s+' '+str(cut),np.allclose(got,full,equal_nan=True))
check('Lead sample begins after one-hour delay, checked from raw prices',all(abs(r.loc[t,'btc_next24_after1h']-np.log(btc.loc[t+pd.Timedelta(hours=25)]/btc.loc[t+pd.Timedelta(hours=1)]))<1e-12 for t in sample.index if pd.notna(r.loc[t,'btc_next24_after1h'])))
check('All tiny-window correlations suppressed',all(pd.isna(x[s+'_corr']) for x in wr if x['n']<10 for s in ['SP500','GOLD_F','WTI_F']))
(P/'checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
fig,ax=plt.subplots(2,1,figsize=(15,9),sharex=True,layout='constrained')
pp=prices.loc['2026-04-30':'2026-09-15',['BTC','SP500','GOLD_F','WTI_F']]
colors={'BTC':'#222222','SP500':'#285fc1','GOLD_F':'#bc941f','WTI_F':'#bc3e50'}
labels={'BTC':'BTC Binance','SP500':'S&P 500','GOLD_F':'Золото GC=F','WTI_F':'Нефть WTI CL=F'}
for s in pp:
    ax[0].plot(pp.index,pp[s]/pp[s].iloc[0]*100,label=labels[s],color=colors[s],lw=1.6)
for s in ['SP500','GOLD_F','WTI_F']:
    a=r.BTC.rolling(20,min_periods=20).corr(r[s]).loc['2026-05-01':'2026-09-15']
    ax[1].plot(a.index,a,label=labels[s],color=colors[s],lw=1.5)
ax[0].set_ylabel('Индекс цены: 30 апреля = 100')
ax[1].set_ylabel('Корреляция доходностей с BTC\nпоследние 20 общих сессий');ax[1].set_ylim(-1,1);ax[1].axhline(0,c='gray',lw=.8)
for a in ax:a.grid(alpha=.2);a.legend(loc='best',ncol=4)
fig.suptitle('BTC и внешний рынок: одинаковое время наблюдения, меняющаяся связь\nЗакрытие 16:00 Нью-Йорк; фьючерсы GC/CL требуют отдельного контроля смены контрактов',fontsize=14)
fig.savefig(P/'macro_context.png',dpi=150)
meta={'checks_passed':len(checks),'primary_rows':len(sample[['BTC','SP500','GOLD_F','WTI_F']].dropna()),
 'start':str(sample.index[0]),'end':str(sample.index[-1]),'calendar_anchor':'16:00 America/New_York',
 'events':{s:json.loads((P/'public_data'/(s+'.json')).read_text())['chart']['result'][0].get('events',{}) for s in ['GLD','USO']}}
(P/'results.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
print(pd.DataFrame(summary).round(4).to_string(index=False));print(pd.DataFrame(wr).round(3).to_string(index=False));print('CHECKS',len(checks))
```


