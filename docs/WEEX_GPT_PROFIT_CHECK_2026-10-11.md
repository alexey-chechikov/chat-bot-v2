# Где заработок: первый законченный расчёт и решение, 11.10.2026

**Готового доказанного прибыльного скальпера по имеющимся проверкам нет. Это не утверждение, что прибыльных стратегий вообще не существует. Предложенный ограниченный4ч/2R/8ч вариант я проверил: строить живого бота на его результате не предлагаю.** Ни исправление учёта, ни rebate, ни большой тейк сами по себе не создают доход. Ниже денежный масштаб результатов и конкретное направление продолжения.

Только исследование, без ключей, приватного state и торговых действий. Новый эксперимент использует локальные Binance USD-M цены/выплаты, отдельно прочитаны public GET funding/quotes WEEX и Bybit. Код и конфиги живых ботов не менялись.

## Ограниченный пробой ETH/XRP: посчитан, не принят

07.05.2026–06.10.2026 exclusive, **152 дня**. Закрытый4ч Donchian30/ADX14≥20, simple ATR14×3, S без дополнительного1.5%, одна попытка входа bar_close+1мин при отклонении≤0.05%, stop-distance≥0.5%, TP2 ценовыхR, обязательный выход8ч. Minute OHLC hard fills, gap-price, stop-first при двойном касании, fees0.05%/ногу, adverse slip0.02%/ногу, actual Binance funding. Начальный капитал$3000, риск≤0.25% актуальной equity/вход, общийstop-budget1%, gross-budget1×equity, ETHqty-step.001/XRP10. Это отдельный эксперимент, а не пересчёт старой многодневной Chandelier-стратегии.

| На счёте$3000 | Основной ADX20 | Контроль без ADX | Операционный stress slip0.04%/ногу |
|---|---:|---:|---:|
| Сделок | 22 | 28 | 21 |
| Итог после fees/funding/slip | **+$0.85** | +$5.15 | +$0.93 |
| Доходность стартового счёта | +0.0283% | +0.1716% | +0.0311% |
| Minute-close liquidation DD | $19.25 | $17.99 | $15.35 |
| Первая непрерывная половина | **−$14.98** | −$12.47 | −$10.74 |
| Вторая непрерывная половина | +$15.83 | +$17.62 | +$11.68 |
| Недельный CI95 mean netR | **[−0.1339;+0.2303]** | [−0.1008;+0.2015] | [−0.1338;+0.1818] |

Денежная сверка основного: price PnL после slippage+$4.734319 −fees$3.787143 −funding$0.098393 = **+$0.848783**. ETH−$4.156787, XRP+$5.005570. Все22 сделки учтены общим equity ledger; их net в точности равен изменению денег. Возможный реально полученный полный fee refund добавил бы$3.787143: **+$4.635927 за весь срок**, без реинвестирования cashback. Это условный сценарий, не подтверждение выплаты/выводимости бонуса WEEX.

**Почему эта рекомендация оказалась слабой:** медианный stop-distance4.0196%, target8.0391%, медианное удержание8ч. **21 выход по времени, только1 TP**, 0SL в конкретной выборке. Большой тейк геометрически перекрывает fee, но за8ч обычно не достигается. Средний entry-notional≈$171.62: широкий стоп уменьшает размер, поэтому от депозитного риска не получается большой денежный доход. Это нельзя исправлять плечом, сохранив тот же денежный риск. 49 сигналов пропущены из-за price-deviation, один из-за открытой позиции.

Операционный stress изменяет и отбор входов (22→21), поскольку более дорогой fill проверяется против того же допуска0.05%. Поэтому его чуть больший итог **не доказательство устойчивости к издержкам**. Дополнительная проверка на том же исходном журнале: оставить quantities/exit events/funding, заменить adverse slip0.02% на0.04%/ногу → **−$0.666074**. Это чувствительность цены исполнения, не новый replay triggers и не выбор более прибыльной версии.

99 заранее заданных общих дневных сдвигов signed signals с теми же current causal ATR/size/exits/cost: **p(net)=0.27**, median control−$11.74. Частота событий, calendar phases и отсутствие позиции учитываются одинаково; это диагностический time-control, не99 независимых рынков. N<100, отрицательная первая половина, CI пересекает0, контроль не пройден. Контроль noADX не становится новым выбранным ботом после просмотра+$5.15.

Бюджетная чувствительность при тех же правилах: начальные$1000 →+$0.19/DD$6.24; $5000 →+$0.63/DD$32.35, также22 сделки. Qty rounding и почти нулевой общий результат не дают линейного масштабирования. Это не прогноз дохода с такого депозита.

**Решение: этот конкретный ограниченный вход/выход не принимается для live.** Не увеличивать количество ордеров или плечо ради красивой денежной суммы и не менять параметры после просмотра этого результата. Положительное ожидание нового периода не установлено.

## Межбиржевая разница funding: проверен денежный порог

Публичный срез **11.10.2026 12:25:37 UTC**. История11.09–11.10, шесть пар, по90 settlement records/биржу/пару, maximum gap8ч. Проверяется одинаковая календарная длительность, а не сравнение несопоставимых процентов за разные интервалы. WEEX пришлось читать7-дневными страницами, большие интервалы public API отвергает.

Только скрининг: сумма funding rates на **условном постоянном нотионале$1000 каждой ноги**, лучший знак пары выбран задним числом. Не портфельный backtest: изменение mark/qty, basis PnL, margin/liquidation, реализация двух ног и будущая смена rate не учтены. Отрицательный порог не доказывает убыточность любой иной basis-стратегии.

Затраты сценария: four taker executions, WEEX0.048% из последнего state-document, Bybit0.055% как публичный non-VIP сценарий (не замер твоего Bybit-аккаунта), текущие две spread-дистанции за round-trip и adverse0.02% на каждое из4 исполнений. Cashback в эту стоимость не включён. Цена будущего выхода/spread неизвестна, поэтому это оценка порога, не точные realized fees.

| Пара | Лучшая задним числом разница funding за30д, % нотионала | Оценка полной round cost, % того же нотионала | Разница минусcost на$1000 |
|---|---:|---:|---:|
| DOGE | 0.18126 | 0.30946 | −$1.28 |
| AAVE | 0.128858 | 0.297994 | −$1.69 |
| SOL | 0.081026 | 0.304258 | −$2.23 |
| XRP | 0.047417 | 0.300352 | −$2.53 |
| ETH | 0.035176 | 0.286799 | −$2.52 |
| BTC | 0.014114 | 0.286241 | −$2.72 |

Не предлагаю держать такую пару30д ради этих выплат: даже gross funding-screen не преодолел выбранный порог. Для другой maker/VIP модели нужно настоящее другое исполнение, нельзя просто заменить тариф и оставить гарантированные taker fills.

Документация: [WEEX funding/current/history/collectCycle](https://www.weex.io/api-doc/catalog/core-trading-futures/api/rest-api/market-api), [Bybit futures fees](https://www.bybit.com/en/help-center/article/?id=000001584), [Binance funding market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data). Публичные данные и raw JSON среза приложены; rates меняются, «сегодня» после времени среза не утверждается.

## Что из уже посчитанного действительно давало плюс

Старые расчёты не выданы за результаты нового теста:

- BTC spot+short perpetual cash&carry на Binance: альтернативный капитал$2700, net+$248.86 за01.2024–05.10.2026, современное May–Oct окно **+$17.59**, stress+$11.76. ETH вместоBTC+$12.42 в современном окне. Механизм — выплаты funding с хеджем. Свежие CI пересекают0, локальный запас маржи и исполнениеWEEX не доказаны. Это небольшой carry, не заработок сотен долларов в месяц с нескольких тысяч.
- ETH4ч Donchian30/ADX20/Chandelier3ATR с **многодневным** удержанием: fixed entry-notional$1000, directUSD-M historical net+$1288.68 full, May–Oct+$145.60 (12 сделок). Но последняя треть всего+$4.65, stress−$8.38, нестабильные соседи/CI. Это направленный кандидат для дальнейшей проверки, а не готовый месячный доход. Его плюс нельзя перенести на TP2R/8ч или15м-интрадей.

Обе суммы имеют разные знаменатели: капитал carry и торговый нотионал trend. Они не суммируются и не сравниваются как доход одного счёта. Источники — ранее сохранённые локальные `research/expectancy_20261006/carry/REPORT.md` и `trend/REPORT.md`; их содержимое для проверки приведено в приложении. История уже исследована.

## Мой практический приоритет для WEEX

**Продолжать один maker/inventory эксперимент из предыдущего ответа, начиная с quote/trade записи и paper.** Возможный источник дохода — spread, действительно получаемая плата/возврат за предоставление ликвидности и контроль неблагоприятного отбора. Он отличается от новых индикаторов и постоянного сеточного мешка: позиции имеют конечную жизнь и не усредняются бесконечно. У данного режима ещё нет измеренного положительного ожидания. Нулевой тариф уменьшает hurdle, но сам не является выплатой сверхcost.

Проверяемый контракт: одна параBTC, own-order registry, independent counterparties; post-only quote допускается только при положительном conservative capture. Quote freshness ограничена реальным API budget. На fill уменьшается inventory-limit; после30сек либо adverse0.5% — выход остатка с реальными затратами. Экспериментальный денежный бюджет≤0.2%C (на$3000 —$6), quote-notional≤1%C, net остаток≤5%C, размер из worst-fill loss. Неоднозначность/unknown→запрет новых входов иreconcile. Эти числа — ограниченный исследовательский бюджет, не гарантия maximum loss приgap.

Данные, которые нужны для допуска: quote/trade/fill timestamp, depth/queue, latency, отдельные successful/cancelled/unfilled, signed markout1/5/30сек, forced exits, grossfee и фактически полученныйrebate. Touch candle не означает maker fill; paper fill требует консервативной модели очереди. Итог — cash+marked/liquidated inventory+funding−fees+received rebates. Нельзя ещё раз вычесть markout из этого cashPNL.

Решение только после≥1000 fills нескольких сессий с зависимостью учтённой блоками: net положителен, CI не включает0, net не обеспечен только предполагаемым неполученнымbonus, цена$1Mоборота укладывается в бюджет.1000fills не1000 независимых наблюдений. Если необходимая freshness не укладывается в ORDERS/APIлимиты, частоту нельзя считать исполненной; нужен другой режим/официальные условия, а не скрытый обход.

Партнёрские контакты полезнее использовать для **письменных условий maker/liquidity программы и фактического API-тарифа**. Возврат ровно уплаченной комиссии — экономия, не положительная maker-выплата. Отрицательнаяmakerfee или отдельнаяплата за реальную ликвидность может быть новым внешним источником денег, но такого договора здесь нет. Никаких собственных встречных/согласованных сделок, сообщений бирже или денежных действий из этой сессии не выполнялось.

Моя конкретная помощь: причинный replay/бумажное исполнение, расчёт dollars/net/R/DD и стоимостиоборота, фильтр допуска по полномуaccount-risk, затем точнаяавтоматизация правил прошедшего режима. Сейчас выполнены два расчёта и отказ по их недостаточной денежной/статистической базе. Готовая доходнаяintraday-система или обещанныймесячныйдоход из этих результатов не следуют.

## Проверка и ограничения

Данные исходных8 файлов ETH/XRP прошли hash/coverage/duplicates/OHLC; minute152д полностью совпадают сhourlyагрегацией. Старые15msource имеют4 несовпадающихasset-hours2024-10-28 и не используются. **May–Oct уже просмотрен прежними4h/1h/manual/MTF исследованиями: это диагностический исторический тест, не untouched holdout.** Модель1мин также не book/tick/queue replayWEEX.

QA проверил7 содержательных сценариев cash/funding/firstminute/gaps/stopfirst/8ч/совместногоразмера; дополнительно исправленzero-trade guard и проверен. Порядокfunding консервативно объявлен перед exits старогоinventory наcanonicalboundary; последний искусственныйEND перед внешнимfundingboundary, primaryENDсделок нет. DD — по минутным close c оценкой liquidation cost, не все внутриминутные экстремумы. Maximum risk/gross вJSON — maxima при admission, а не непрерывные maxima market-risk. Дневной/peak stopaccountcontroller в данном тесте не реализован; это диагностика модели входа/выхода, не весь livecontract.

Результаты воспроизводимы из приложенных скриптов и исходныхCSVmanifest; scripts не productionpatch. Перезапуск бота, `/weex stop`, открытие или закрытие живых позиций не выполнялись.


## Приложение: полный расчёт, правила, ledger и публичный срез

Для повтора сохранить Python/JSON/CSV-блоки с указанными именами в `research/weex_profit_test_20261011/`
репозитория, подготовить inputCSV в соседней `research/expectancy_20261006/public_data/`.
Точный список/хеши источников — input_manifest/data_provenance. Это BinanceUSD-M, не spotCSV.
Использованы Python bundled runtime, pandas3.0.1/numpy2.3.5. Запуск: `python bounded_breakout.py`,
затем `python economic_sensitivity.py`; QA: `python qa_trend/qa_execution.py`.
Нужны только общедоступные исторические данные, доступ к аккаунтам не нужен.

`funding_screen.py` при повторном запуске читает новый current30d-срез. Для воспроизведения
зафиксированного чтения использовать raw JSON ниже и recorded window. Это public GET-only.
Исходные CSV не изменены. Ledger/control CSV — промежуточные расчёты, не торговые команды.


<details>
<summary>PROTOCOL.md</summary>

SHA256 UTF-8/LF: `c7df7c8af38e80ad48663fd4981818ad88684947a3907116ea78eb88be52e8b8`

```markdown
# Один замороженный тест прибыли ETH/XRP, 11.10.2026

Записано до просмотра результатов этого варианта. Это дополнительная гипотеза в уже исследованной семье, не независимое подтверждение и не новый untouched holdout. История May–Oct уже использовалась в прежних исследованиях. Никаких торговых действий.

Данные: Binance USD-M ETHUSDT/XRPUSDT 1h из research/expectancy_20261006/public_data для закрытых4ч признаков, 1m из того же каталога для исполнения May7 2026–Oct6 2026 exclusive, фактические funding rate/markPrice. 15m source не используется из-за несовпадений с1h/1m. Не подмена отсутствующего raw-cache исходного WEEX-исследования. При переносе на WEEX нужен новый execution check.

Сигнал: текущий завершённый4ч close выше maxhigh предыдущих30 полных4ч баров (LONG), ниже minlow (SHORT); ADX14 как в закреплённом tools/trend_state.py, ≥20; ATR14 = simple rolling true range. EventID symbol/side/bar-close-time. Только flat по инструменту; нет повторного того жеeventID.

Вход: одна попытка на open первой полной минуты после готовности сигнала, то есть bar_close+1min. Это модель исполнения, не обещание реального fill. Исходный reference=signalclose. Если итоговая цена с adverse slip ушла от reference больше0.05%, событие пропущено; нет ожидания возврата цены. Такая попытка внутри исходного TTL15мин. Если hard-stop-distance относительно фактическогоE<0.5%, неверная сторона стопа или недостаточный risk/gross room — пропуск.

S LONG=signalhigh−3ATR, SHORT=signallow+3ATR, без дополнительного1.5%; S фиксирован. TP=actualentry±2*abs(actualentry−S). Выход по hard stop, TP либо nextavailableopen ровно через8ч послеfill, что наступило первым. Неисполненные выходы не считаются гарантированными. При выходе внутри минутки: opening gap учитывается; если обе границы touched в минутке, STOP first. TP моделируется aggressive exit с комиссией/slip, не идеальный maker fill. Никакого Chandelier trailing/усреднения. Финальный остаток mark/exit с затратами на lastclose, помечен END отдельно.

Комиссияgross0.05% с каждой фактической ноги (консервативно к измеренным0.048%), adverse slip0.02% на каждую ногу; stress0.04%. Дополнительный условный сценарий full received fee refund использует те же размеры/исполнения, возвращает paid fees послеexit; cashback не финансирует допуск/размер. No-fee wealth не приравнивается к доказанному payout бонуса.

Funding: исторические выплаты q*markPrice*rate, знак −side. Raw timestamps сохранены в source, canonical boundary=floorsecond (все отклонения≤26ms). Позиция, существовавшая перед минутой settlement, платит до внутриминутного touch-выхода; новые входы послеcharge. На opening-gap exit chargeконсервативно такжедоexit. Это явно объявленная конвенция OHLC tie-breaking, не точный subsecond replay.

Капитал начальный3000USDT, без довнесений. На вход R≤0.25% актуальной marked equity, sum-stopped-risk≤1%, instrumentgross≤0.5equity, combinedgross≤equity. Размер по actualentry и adverse stopfill с двумя grossfees плюс резервfunding0.05% entry-notional. Futuresqty округляется вниз:ETH.001, XRP10 по существующему WEEX-конфигу; размернеувеличиваетсяcashback. Лимит исполненияstopприgap не гарантирован. Никакой установки плеча/дополнительного заработка от множителя плеча. Equity отмечается каждуюминуту; DD initialzero/initialcapital included. Ledgergross,fees,funding иусловныйrefund раздельно. Комбинированный ETH+XRP риск учитывается во времени. Дневной/peakkillcontroller в этом тесте не применяется: это изолированная проверка входа/выхода с positionbudgets, не весь livecontract.

Основной вариант ADX20, контроль noADX с темижеtime/risk/exits/cost. Stress того же ADX20. Отчёт total идве календарныеполовины Jul22cut с непрерывнымinventory/equity. ≥100эпизодов, netpositive обеихполовин иstress, weeklyblock CI95 meanR>0, timingplacebo advantage. 99 circular signed-signal shifts общейUTC-дневнойфазы ETH/XRP, offset≥7d, seed20261011; currentcausalATR/stopgeometry итежеrisk/exits/cost, безсновафильтраcurrentADX. Это контроль времени, а не 99независимыхстратегий. Случайныеcontrols не используютсядляподбора. Еслиосновнойвариантnegative—проверкуотвергнуть; нет дальнейшегопереборапараметроввэтомпрогоне.

Пройденная диагностика ещё не разрешаетlive: нужна новаяпоследующаяпроверка иactualWEEXисполнение. Еслинепройдена—непревращатьnoADX/однумонету/положительнуюполовину ввыбраннуюстратегию. Отдельно показатьпрактическиймасштабденег, календарныйсрок, DD истоимостьоборота.
```

</details>


<details>
<summary>results.json</summary>

SHA256 UTF-8/LF: `29e6cc0c22d5b0095f4ca9d9ded22b3027536b44c475d37f847557669c508771`

```json
{
  "primary": {
    "N": 22,
    "net": 0.8487833180806774,
    "return_pct": 0.028292777269355914,
    "DD_usd": 19.254201985452255,
    "net_half1": -14.981483482387375,
    "net_half2": 15.830266800468053,
    "gross": 4.734319240639964,
    "fees": 3.7871432734823194,
    "funding": -0.09839264907582455,
    "if_full_received_fee_refund": 4.635926591562997,
    "win_pct": 27.27272727272727,
    "PF": 1.0473166440255541,
    "mean_R": 0.0029693764616081668,
    "median_hold_h": 8.0,
    "worst_trade_usd": -3.937195406949452,
    "turnover": 7574.286546964641,
    "cost_per_million_turnover": -112.06115755164072,
    "maximum_reserved_risk_frac": 0.004827239805469889,
    "maximum_gross_frac": 0.12075282286115059,
    "ambiguous_stop_target_minutes": 0,
    "skip_counts": {
      "price_departed_over_005pct": 49,
      "position_already_open": 1
    },
    "exit_counts": {
      "TIME": 21,
      "TP": 1
    },
    "weekly_CI95_mean_R": [
      -0.13386957216152942,
      0.23031285945464333
    ]
  },
  "no_adx": {
    "N": 28,
    "net": 5.147021072409643,
    "return_pct": 0.17156736908032144,
    "DD_usd": 17.992866619102642,
    "net_half1": -12.470917630372696,
    "net_half2": 17.61793870278234,
    "gross": 10.173592284639977,
    "fees": 4.874310076068321,
    "funding": -0.15226113616192072,
    "if_full_received_fee_refund": 10.021331148477964,
    "win_pct": 32.142857142857146,
    "PF": 1.2515057538282923,
    "mean_R": 0.023146177890084014,
    "median_hold_h": 8.0,
    "worst_trade_usd": -3.937195406949452,
    "turnover": 9748.620152136638,
    "cost_per_million_turnover": -527.974317604482,
    "maximum_reserved_risk_frac": 0.004951864035220243,
    "maximum_gross_frac": 0.13831914281968125,
    "ambiguous_stop_target_minutes": 0,
    "skip_counts": {
      "price_departed_over_005pct": 67,
      "position_already_open": 3
    },
    "exit_counts": {
      "TIME": 27,
      "TP": 1
    },
    "weekly_CI95_mean_R": [
      -0.10083769172933282,
      0.2014894406005457
    ]
  },
  "stress": {
    "N": 21,
    "net": 0.9318469159984488,
    "return_pct": 0.03106156386661496,
    "DD_usd": 15.346323003110228,
    "net_half1": -10.743736260029436,
    "net_half2": 11.675583176027885,
    "gross": 4.663292574080023,
    "fees": 3.64096376718704,
    "funding": -0.09048189089400023,
    "if_full_received_fee_refund": 4.572810683185489,
    "win_pct": 28.57142857142857,
    "PF": 1.044046479708262,
    "mean_R": 0.006234242394551641,
    "median_hold_h": 8.0,
    "worst_trade_usd": -4.016599772949423,
    "turnover": 7281.927534374079,
    "cost_per_million_turnover": -127.9670680049614,
    "maximum_reserved_risk_frac": 0.004927526176874272,
    "maximum_gross_frac": 0.1199819092002602,
    "ambiguous_stop_target_minutes": 0,
    "skip_counts": {
      "price_departed_over_005pct": 48,
      "position_already_open": 3
    },
    "exit_counts": {
      "TIME": 20,
      "TP": 1
    },
    "weekly_CI95_mean_R": [
      -0.1337755926068969,
      0.18182117467561365
    ]
  },
  "timing_controls": {
    "N": 99,
    "p_net": 0.27,
    "net_median": -11.744528394136978,
    "net_CI95": [
      -44.41708140312492,
      23.82229687370229
    ]
  },
  "gate": {
    "N_at_least100": false,
    "net_positive": true,
    "both_halves_positive": false,
    "stress_positive": true,
    "CI_positive": false,
    "timing_p_at_most005": false,
    "untouched_confirmation_available": false
  }
}
```

</details>


<details>
<summary>economic_sensitivity.json</summary>

SHA256 UTF-8/LF: `52d24eed322b0ae0966c70f6bb5f00367f63b3357eefde74d9e02676ef22ffd3`

```json
{
  "same_fills_slip_004pct": {
    "N": 22,
    "net": -0.6660736163605177,
    "fees": 3.7871426485646396,
    "scope": "Reprice the original admitted quantities/exit events only; not a new trigger replay. Extra adverse2bps per execution, funding unchanged. Operational stress separately changes admitted cohort."
  },
  "capital_sensitivity": {
    "1000": {
      "N": 22,
      "net": 0.19275517432345168,
      "return_pct": 0.01927551743234517,
      "DD_usd": 6.24441031874494,
      "if_full_received_fee_refund": 1.4190153405953716
    },
    "5000": {
      "N": 22,
      "net": 0.6271617668644467,
      "return_pct": 0.012543235337288933,
      "DD_usd": 32.34954834426753,
      "if_full_received_fee_refund": 7.016682862000606
    }
  }
}
```

</details>


<details>
<summary>bounded_breakout.py</summary>

SHA256 UTF-8/LF: `ff439361ad67d45a98f1d864826bd7dafdc479903938b6baecafd1d81603918c`

```python
"""Frozen, offline 4h entry / minute execution experiment. No API or live state."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'expectancy_20261006/public_data'
SYMBOLS = ['ETHUSDT', 'XRPUSDT']
FEE = .0005
START = pd.Timestamp('2026-05-07', tz='UTC')
END = pd.Timestamp('2026-10-06', tz='UTC')
CUT = pd.Timestamp('2026-07-22', tz='UTC')
INITIAL = 3000.
STEPS = [.001, 10.]
TICKS = [.01, .0001]


def indicators(d):
    tr = pd.concat([d.high-d.low, (d.high-d.close.shift()).abs(),
                    (d.low-d.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    up, dn = d.high.diff(), -d.low.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.)
    minus = np.where((dn > up) & (dn > 0), dn, 0.)
    a = tr.ewm(alpha=1/14, adjust=False).mean()
    pdi = 100*pd.Series(plus, index=d.index).ewm(alpha=1/14, adjust=False).mean()/a
    mdi = 100*pd.Series(minus, index=d.index).ewm(alpha=1/14, adjust=False).mean()/a
    dx = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1/14, adjust=False).mean()
    return atr, adx


def load():
    assets, meta = [], []
    common = None
    for si, symbol in enumerate(SYMBOLS):
        hp, mp, fp = [DATA/f'binance_futures_{symbol}_{kind}.csv' for kind in ['1h', '1m', 'funding']]
        h = pd.read_csv(hp)
        h.index = pd.to_datetime(h.ts, unit='ms', utc=True)
        d = h.resample('4h').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last', 'volume':'sum'})
        assert h.resample('4h').size().eq(4).all()
        atr, adx = indicators(d)
        hh, ll = d.high.rolling(30).max().shift(), d.low.rolling(30).min().shift()
        sides = np.where(d.close>hh, 1, np.where(d.close<ll, -1, 0))
        slots = d.index + pd.Timedelta(hours=4)
        choose = (slots >= START) & (slots < END)
        feat = d.loc[choose].copy()
        feat['atr'], feat['adx'], feat['side'] = atr.loc[choose], adx.loc[choose], sides[choose]
        feat.index = slots[choose]
        m = pd.read_csv(mp)
        ms = m.ts.to_numpy(dtype=np.int64)
        expected = np.arange(START.value//10**6, END.value//10**6, 60000)
        assert np.array_equal(ms, expected)
        if common is None:
            common = ms
        assert np.array_equal(common, ms)
        funding = pd.read_csv(fp)
        funding['canonical'] = (funding.fundingTime//1000)*1000
        funding = funding[(funding.canonical>=common[0]) & (funding.canonical<END.value//10**6)]
        assert len(funding) == 456 and funding.canonical.is_unique
        fr = {int((r.canonical-common[0])//60000):(float(r.fundingRate), float(r.markPrice))
              for r in funding.itertuples()}
        entries = {}
        for ft, r in feat.iterrows():
            idx = int((ft.value//10**6-common[0])//60000)+1
            if 0 <= idx < len(common):
                entries[idx] = {'ref':float(r.close), 'high':float(r.high), 'low':float(r.low),
                                'atr':float(r.atr), 'adx':float(r.adx), 'side':int(r.side)}
        assets.append({'symbol':symbol, 'o':m.open.to_numpy(), 'h':m.high.to_numpy(),
                       'l':m.low.to_numpy(), 'c':m.close.to_numpy(), 'entries':entries, 'funding':fr})
        for p in [hp, mp, fp]:
            meta.append({'path':str(p), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    return common, assets, meta


def stop_price(raw, side, tick):
    return (math.floor(raw/tick+1e-9) if side == 1 else math.ceil(raw/tick-1e-9))*tick


def intrabar_exit(pos, o, h, l):
    d, s, t = pos['side'], pos['stop'], pos['target']
    if d*(o-s) <= 0:
        return o, 'SL_GAP'
    if d*(o-t) >= 0:
        return o, 'TP_GAP'
    stopped = l <= s if d == 1 else h >= s
    target = h >= t if d == 1 else l <= t
    if stopped:
        return s, 'SL_BOTH' if target else 'SL'
    if target:
        return t, 'TP'
    return None


def signals(assets, adx=True, offset_days=0):
    result = []
    for a in assets:
        keys = sorted(a['entries'])
        flags = np.array([a['entries'][k]['side'] if not adx or a['entries'][k]['adx']>=20 else 0 for k in keys])
        if offset_days:
            flags = np.roll(flags, offset_days*6)
        result.append({k:int(s) for k, s in zip(keys, flags) if s})
    return result


def simulate(ms, assets, adx=True, slip=.0002, offset_days=0, detailed=True, initial=INITIAL):
    sigs = signals(assets, adx, offset_days)
    positions = [None, None]
    cash = initial
    trades, reasons = [], Counter()
    n = len(ms)
    eq = np.empty(n) if detailed else None
    peak, maxdd, maxrisk, maxgross = initial, 0., 0., 0.
    total_fees, total_funding, turnover, ambig = 0., 0., 0., 0
    cut_equity = initial
    cut_idx = int((CUT.value//10**6-ms[0])//60000)-1

    def liquid_equity(i, field):
        val = cash
        for k, p in enumerate(positions):
            if p:
                x = float(assets[k][field][i])*(1-p['side']*slip)
                val += p['side']*p['qty']*(x-p['entry']) - FEE*p['qty']*x
        return val

    def close(k, i, raw, why, timestamp):
        nonlocal cash, total_fees, turnover, ambig
        p = positions[k]
        x = raw*(1-p['side']*slip)
        exit_fee = FEE*p['qty']*x
        gross = p['side']*p['qty']*(x-p['entry'])
        cash += gross-exit_fee
        total_fees += exit_fee
        turnover += p['qty']*x
        net = gross-p['entry_fee']-exit_fee+p['funding']
        trades.append({'symbol':assets[k]['symbol'], 'side':p['side'], 'entry_ms':int(ms[p['start']]),
                       'exit_ms':int(timestamp), 'entry':p['entry'], 'exit':x, 'stop':p['stop'],
                       'target':p['target'], 'qty':p['qty'], 'risk_reserved':p['risk'], 'gross':gross,
                       'fees':p['entry_fee']+exit_fee, 'funding':p['funding'], 'net':net,
                       'R':net/p['risk'], 'reason':why, 'hold_h':(timestamp-ms[p['start']])/3600000})
        if why == 'SL_BOTH':
            ambig += 1
        positions[k] = None

    for i in range(n):
        # Settlement on positions present before this minute; entry comes afterwards.
        for k, a in enumerate(assets):
            p = positions[k]
            if p and i in a['funding']:
                rate, mark = a['funding'][i]
                flow = -p['side']*p['qty']*mark*rate
                cash += flow
                p['funding'] += flow
                total_funding += flow
        # Only open-price exits occur before the scheduled entry; no intrabar lookahead.
        for k, a in enumerate(assets):
            p = positions[k]
            if not p:
                continue
            o = float(a['o'][i])
            if i >= p['deadline']:
                close(k, i, o, 'TIME', ms[i])
            elif p['side']*(o-p['stop']) <= 0:
                close(k, i, o, 'SL_GAP', ms[i])
            elif p['side']*(o-p['target']) >= 0:
                close(k, i, o, 'TP_GAP', ms[i])
        # ETH precedes XRP for simultaneous events, consistently in all controls.
        for k, a in enumerate(assets):
            side = sigs[k].get(i)
            if not side:
                continue
            if positions[k]:
                reasons['position_already_open'] += 1
                continue
            f = a['entries'][i]
            entry = float(a['o'][i])*(1+side*slip)
            if abs(entry/f['ref']-1) > .0005:
                reasons['price_departed_over_005pct'] += 1
                continue
            stop = stop_price(f['high']-3*f['atr'] if side == 1 else f['low']+3*f['atr'], side, TICKS[k])
            distance = side*(entry-stop)
            if distance <= 0 or distance/entry < .005:
                reasons['stop_invalid_or_under_05pct'] += 1
                continue
            equity = liquid_equity(i, 'o')
            existing_risk = sum(p['risk'] for p in positions if p)
            gross_now = sum(p['qty']*float(assets[j]['o'][i]) for j, p in enumerate(positions) if p)
            budget = min(.0025*equity, .01*equity-existing_risk)
            stop_exec = stop*(1-side*slip)
            loss = side*(entry-stop_exec) + FEE*(entry+stop_exec) + .0005*entry
            qty = min(max(budget, 0.)/loss, max(.5*equity, 0.)/entry, max(equity-gross_now, 0.)/entry)
            qty = math.floor(qty/STEPS[k]+1e-9)*STEPS[k]
            if qty < STEPS[k]:
                reasons['risk_or_min_qty'] += 1
                continue
            fee = FEE*qty*entry
            risk = qty*loss
            positions[k] = {'side':side, 'entry':entry, 'stop':stop, 'target':entry+side*2*distance,
                            'qty':qty, 'start':i, 'deadline':i+480, 'entry_fee':fee, 'funding':0., 'risk':risk}
            cash -= fee
            total_fees += fee
            turnover += qty*entry
            maxrisk = max(maxrisk, (existing_risk+risk)/equity)
            maxgross = max(maxgross, (gross_now+qty*entry)/equity)
        # New entries are exposed to their first minute; simultaneous touches are stop-first.
        for k, a in enumerate(assets):
            p = positions[k]
            if p:
                outcome = intrabar_exit(p, float(a['o'][i]), float(a['h'][i]), float(a['l'][i]))
                if outcome:
                    raw, why = outcome
                    close(k, i, raw, why, ms[i]+60000)
        if i == n-1:
            for k, a in enumerate(assets):
                if positions[k]:
                    close(k, i, float(a['c'][i]), 'END', ms[i]+60000)
        marked = liquid_equity(i, 'c')
        peak = max(peak, marked)
        maxdd = max(maxdd, peak-marked)
        if detailed:
            eq[i] = marked
        if i == cut_idx:
            cut_equity = marked
    columns = ['symbol','side','entry_ms','exit_ms','entry','exit','stop','target','qty',
               'risk_reserved','gross','fees','funding','net','R','reason','hold_h']
    t = pd.DataFrame(trades, columns=columns)
    net = cash-initial
    assert abs(t.net.sum()-net)<1e-7
    assert abs(t.fees.sum()-total_fees)<1e-7
    assert abs(t.funding.sum()-total_funding)<1e-7
    assert maxrisk<=.01+1e-9 and maxgross<=1.+1e-9
    losses = -float(t.loc[t.net<0,'net'].sum())
    stats = {'N':len(t), 'net':net, 'return_pct':net/initial*100, 'DD_usd':maxdd,
             'net_half1':cut_equity-initial, 'net_half2':cash-cut_equity,
             'gross':float(t.gross.sum()), 'fees':total_fees, 'funding':total_funding,
             'if_full_received_fee_refund':net+total_fees, 'win_pct':float((t.net>0).mean()*100) if len(t) else None,
             'PF':float(t.loc[t.net>0,'net'].sum()/losses) if losses>0 else None,
             'mean_R':float(t.R.mean()) if len(t) else None, 'median_hold_h':float(t.hold_h.median()) if len(t) else None,
             'worst_trade_usd':float(t.net.min()) if len(t) else None, 'turnover':turnover,
             'cost_per_million_turnover':-net/turnover*1e6 if turnover>0 else None,
             'maximum_reserved_risk_frac':maxrisk, 'maximum_gross_frac':maxgross,
             'ambiguous_stop_target_minutes':ambig, 'skip_counts':dict(reasons),
             'exit_counts':t.reason.value_counts().to_dict()}
    return stats, t, eq


def weekly_ci(t, seed=20261011):
    if t.empty:
        return [None, None]
    d = t.copy()
    d['week'] = pd.to_datetime(d.exit_ms, unit='ms', utc=True).dt.to_period('W').astype(str)
    grouped = d.groupby('week').agg(n=('R','size'), r=('R','sum'))
    # Include inactive complete calendar weeks; do not select only winning weeks.
    allweeks = pd.date_range(START, END-pd.Timedelta(minutes=1), freq='D').to_period('W').astype(str).unique()
    grouped = grouped.reindex(allweeks, fill_value=0)
    rng = np.random.default_rng(seed)
    ids = rng.integers(0, len(grouped), size=(5000, len(grouped)))
    nr = grouped.n.to_numpy()[ids].sum(axis=1)
    rr = grouped.r.to_numpy()[ids].sum(axis=1)
    return np.quantile(rr[nr>0]/nr[nr>0], [.025, .975]).tolist()


def main():
    start = time.time()
    ms, assets, meta = load()
    (HERE/'input_manifest.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    results = {}
    for label, adx, slip in [('primary', True, .0002), ('no_adx', False, .0002), ('stress', True, .0004)]:
        stats, trades, eq = simulate(ms, assets, adx=adx, slip=slip)
        stats['weekly_CI95_mean_R'] = weekly_ci(trades)
        results[label] = stats
        trades.to_csv(HERE/f'{label}_trades.csv', index=False)
        pd.Series(eq, index=pd.to_datetime(ms+60000, unit='ms', utc=True), name='equity').resample('1D', closed='right', label='right').last().to_csv(HERE/f'{label}_daily_equity.csv')
        (HERE/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps({'case':label, 'result':stats}, ensure_ascii=True), flush=True)
    rng = np.random.default_rng(20261011)
    offsets = rng.choice(np.arange(7, 146), size=99, replace=False)
    controls = []
    for j, offset in enumerate(offsets):
        stats, _, _ = simulate(ms, assets, offset_days=int(offset), detailed=False)
        controls.append({'offset_days':int(offset), **stats})
        if (j+1)%10 == 0:
            print(json.dumps({'controls_completed':j+1, 'seconds':round(time.time()-start,1)}), flush=True)
    pd.DataFrame(controls).to_csv(HERE/'timing_controls.csv', index=False)
    observed = results['primary']['net']
    results['timing_controls'] = {'N':99, 'p_net':(1+sum(c['net']>=observed for c in controls))/100,
                                 'net_median':float(np.median([c['net'] for c in controls])),
                                 'net_CI95':np.quantile([c['net'] for c in controls], [.025,.975]).tolist()}
    results['gate'] = {'N_at_least100':results['primary']['N']>=100,
                       'net_positive':observed>0, 'both_halves_positive':min(results['primary']['net_half1'], results['primary']['net_half2'])>0,
                       'stress_positive':results['stress']['net']>0,
                       'CI_positive':results['primary']['weekly_CI95_mean_R'][0] is not None and results['primary']['weekly_CI95_mean_R'][0]>0,
                       'timing_p_at_most005':results['timing_controls']['p_net']<=.05,
                       'untouched_confirmation_available':False}
    (HERE/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({'gate':results['gate'], 'timing_controls':results['timing_controls'], 'seconds':round(time.time()-start,1)}), flush=True)


if __name__ == '__main__':
    main()
```

</details>


<details>
<summary>economic_sensitivity.py</summary>

SHA256 UTF-8/LF: `e234540be7c519f565011f0154c74b00d2ece950426ed85c39fcf059cca56c56`

```python
"""Fixed-rule capital sensitivity and fixed-fill execution-cost sensitivity."""
import json
from pathlib import Path
import pandas as pd
import bounded_breakout as b

HERE = Path(__file__).resolve().parent
tr = pd.read_csv(HERE/'primary_trades.csv')
old, new = .0002, .0004
entry = tr.entry/(1+tr.side*old)*(1+tr.side*new)
exit_px = tr.exit/(1-tr.side*old)*(1-tr.side*new)
fees = b.FEE*tr.qty*(entry+exit_px)
net = tr.side*tr.qty*(exit_px-entry)-fees+tr.funding
out = {'same_fills_slip_004pct': {
    'N':len(tr), 'net':float(net.sum()), 'fees':float(fees.sum()),
    'scope':'Reprice the original admitted quantities/exit events only; not a new trigger replay. Extra adverse2bps per execution, funding unchanged. Operational stress separately changes admitted cohort.'}}
ms, assets, _ = b.load()
out['capital_sensitivity'] = {}
for capital in [1000., 5000.]:
    stats, _, _ = b.simulate(ms, assets, initial=capital)
    out['capital_sensitivity'][str(int(capital))] = {k:stats[k] for k in ['N','net','return_pct','DD_usd','if_full_received_fee_refund']}
(HERE/'economic_sensitivity.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out))
```

</details>


<details>
<summary>primary_trades.csv</summary>

SHA256 UTF-8/LF: `5370a3761181619cb56f8b230ae30e3d9b94f00958fc7d7c7f2d08bbb8a1920b`

```csv
symbol,side,entry_ms,exit_ms,entry,exit,stop,target,qty,risk_reserved,gross,fees,funding,net,R,reason,hold_h
ETHUSDT,-1,1778212860000,1778241660000,2278.014306,2294.748858,2369.11,2095.822918,0.078,7.412521132926001,-1.3052950559999918,0.178337763396,-0.005066781065858311,-1.48869960046185,-0.20083579847740743,TIME,8.0
ETHUSDT,-1,1778932860000,1778961660000,2174.9449240000004,2180.466006,2251.4500000000003,2021.9347720000005,0.093,7.46383227941697,-0.5134606259999769,0.20252660824500002,0.013188066184983046,-0.7027991680599939,-0.0941606324673325,TIME,8.0
XRPUSDT,-1,1779220860000,1779249660000,1.35612872,1.35787152,1.4260000000000002,1.2163861599999999,100.0,7.222575132000007,-0.17427999999999333,0.135700012,-0.0034401024,-0.31342011439999334,-0.04339451077654681,TIME,8.0
ETHUSDT,-1,1779480060000,1779508860000,2065.5868,2070.283974,2144.33,1908.1004000000003,0.091,7.490212933202966,-0.4274428339999913,0.188182120217,0.010748633895999999,-0.6048763203209913,-0.08075555738070772,TIME,8.0
XRPUSDT,-1,1779480060000,1779508860000,1.33783238,1.34056806,1.3892,1.2350971400000001,130.0,6.978144068999975,-0.35563840000000235,0.1740960286,-0.006632248502958001,-0.5363666771029604,-0.07686380100487465,TIME,8.0
XRPUSDT,-1,1779523260000,1779552060000,1.3109377599999998,1.3358671199999999,1.3571,1.2186132799999996,150.0,7.263492520500023,-3.7394040000000017,0.19851036599999997,0.00071895905055,-3.937195406949452,-0.5420526552257554,TIME,8.0
ETHUSDT,-1,1779940860000,1779969660000,1980.20388,1988.407602,2071.81,1796.9916400000002,0.078,7.412870248757992,-0.6398903159999977,0.154775847798,0.003955823241363544,-0.7907103405566341,-0.10666723064377334,TIME,8.0
XRPUSDT,-1,1779940860000,1779969660000,1.27854424,1.28765748,1.3302,1.17523272,130.0,7.002525043800017,-1.184721200000003,0.16680311180000001,-0.01950602225,-1.371030334050003,-0.1957908505109743,TIME,8.0
XRPUSDT,-1,1780632060000,1780660860000,1.13337328,1.1177234999999999,1.2382,0.9237198400000002,60.0,6.409617425999994,0.9389868000000101,0.0675329034,-0.007917918134688,0.863535978465322,0.13472504224081638,TIME,8.0
XRPUSDT,1,1783008060000,1783036860000,1.09351866,1.08708254,1.0529,1.17475598,170.0,7.216347572900017,-1.0941404000000077,0.185351102,-0.005085443579999999,-1.2845769455800078,-0.17800929522907913,TIME,8.0
ETHUSDT,1,1783080060000,1783108860000,1742.29839,1744.40105,1644.5900000000001,1937.7151699999995,0.074,7.444528532893978,0.15559684000000107,0.12900787928,-0.006711208332956562,0.01987775238704452,0.0026701156828419412,TIME,8.0
ETHUSDT,1,1783123260000,1783152060000,1758.2415780000001,1757.428444,1678.89,1916.9447340000002,0.09,7.405638722009991,-0.07318206000001964,0.15820515099,-0.012088548172727658,-0.2434757591627473,-0.032877077629931244,TIME,8.0
XRPUSDT,-1,1783526460000,1783555260000,1.0732853,1.0909181399999999,1.129,0.9618559,120.0,6.909407783999994,-2.1159407999999846,0.1298522064,0.0055670718,-2.2402259345999846,-0.32422835713758863,TIME,8.0
ETHUSDT,1,1784044860000,1784073660000,1873.57464,1889.5020240000001,1797.28,2026.1639200000002,0.094,7.466056305727998,1.497174096000007,0.17686460320800002,-0.006814331528400001,1.3134951612636072,0.1759289117945557,TIME,8.0
ETHUSDT,1,1784073660000,1784102460000,1890.257976,1870.065912,1804.02,2062.7339280000006,0.083,7.419442008642003,-1.6759413120000062,0.15605344135200003,-0.007766436662628679,-1.839761190014635,-0.24796489922985065,TIME,8.0
ETHUSDT,1,1784131260000,1784160060000,1930.355994,1917.6064020000001,1851.27,2088.527982,0.09,7.408084848029996,-1.1474632799999904,0.17315830782,-0.007505043933156299,-1.3281266317531468,-0.17928069926282372,TIME,8.0
ETHUSDT,1,1784620860000,1784649660000,1933.096542,1930.223878,1863.77,2071.749626,0.10200000000000001,7.40153729883,-0.2930117279999986,0.19702934142000003,-0.007086882070482648,-0.4971279514904813,-0.06716549973598929,TIME,8.0
XRPUSDT,-1,1786435260000,1786464060000,1.0042991,1.00250046,1.034,0.9448972999999996,230.0,7.228693575000021,0.41368719999996584,0.23078194940000002,0.0071005387890319994,0.19000578938899784,0.02628494172807668,TIME,8.0
XRPUSDT,1,1787155260000,1787176740000,1.06761348,1.1316140719119996,1.0355,1.1318404399999995,220.0,7.459284784599936,14.080130220639933,0.24191503071031994,0.0,13.838215189929613,1.855166492436285,TP,5.966666666666667
ETHUSDT,1,1787184060000,1787212860000,2252.660442,2250.459818,2193.92,2370.1413259999995,0.11900000000000001,7.4409066189499695,-0.26187425600000735,0.26793565547,-0.026793116103873003,-0.5566030275738804,-0.074803119576365,TIME,8.0
XRPUSDT,-1,1789516860000,1789545660000,1.2826434199999999,1.2847568999999999,1.4005,1.0469302599999994,60.0,7.207182808200007,-0.12680880000000005,0.0770220096,0.0004593734999759999,-0.20337143610002406,-0.02821788228663178,TIME,8.0
ETHUSDT,1,1789992060000,1790020860000,2723.79465,2762.367416,2624.8,2921.783949999999,0.07200000000000001,7.455999036239955,2.777239152000017,0.19750183437600005,-0.0177170328,2.562020284824017,0.3436186448484358,TIME,8.0
```

</details>


<details>
<summary>primary_daily_equity.csv</summary>

SHA256 UTF-8/LF: `d373a3940c27dfd52595cde614c2c11ce1f2983987dec05c0e490c0235507cb8`

```csv
,equity
2026-05-07 00:00:00+00:00,
2026-05-08 00:00:00+00:00,3000.0
2026-05-09 00:00:00+00:00,2998.511300399538
2026-05-10 00:00:00+00:00,2998.511300399538
2026-05-11 00:00:00+00:00,2998.511300399538
2026-05-12 00:00:00+00:00,2998.511300399538
2026-05-13 00:00:00+00:00,2998.511300399538
2026-05-14 00:00:00+00:00,2998.511300399538
2026-05-15 00:00:00+00:00,2998.511300399538
2026-05-16 00:00:00+00:00,2998.511300399538
2026-05-17 00:00:00+00:00,2997.808501231478
2026-05-18 00:00:00+00:00,2997.808501231478
2026-05-19 00:00:00+00:00,2997.808501231478
2026-05-20 00:00:00+00:00,2997.1883041884785
2026-05-21 00:00:00+00:00,2997.4950811170784
2026-05-22 00:00:00+00:00,2997.4950811170784
2026-05-23 00:00:00+00:00,2997.6406148562605
2026-05-24 00:00:00+00:00,2992.4166427127047
2026-05-25 00:00:00+00:00,2992.4166427127047
2026-05-26 00:00:00+00:00,2992.4166427127047
2026-05-27 00:00:00+00:00,2992.4166427127047
2026-05-28 00:00:00+00:00,2992.4166427127047
2026-05-29 00:00:00+00:00,2990.2549020380984
2026-05-30 00:00:00+00:00,2990.2549020380984
2026-05-31 00:00:00+00:00,2990.2549020380984
2026-06-01 00:00:00+00:00,2990.2549020380984
2026-06-02 00:00:00+00:00,2990.2549020380984
2026-06-03 00:00:00+00:00,2990.2549020380984
2026-06-04 00:00:00+00:00,2990.2549020380984
2026-06-05 00:00:00+00:00,2990.2549020380984
2026-06-06 00:00:00+00:00,2991.1184380165637
2026-06-07 00:00:00+00:00,2991.1184380165637
2026-06-08 00:00:00+00:00,2991.1184380165637
2026-06-09 00:00:00+00:00,2991.1184380165637
2026-06-10 00:00:00+00:00,2991.1184380165637
2026-06-11 00:00:00+00:00,2991.1184380165637
2026-06-12 00:00:00+00:00,2991.1184380165637
2026-06-13 00:00:00+00:00,2991.1184380165637
2026-06-14 00:00:00+00:00,2991.1184380165637
2026-06-15 00:00:00+00:00,2991.1184380165637
2026-06-16 00:00:00+00:00,2991.1184380165637
2026-06-17 00:00:00+00:00,2991.1184380165637
2026-06-18 00:00:00+00:00,2991.1184380165637
2026-06-19 00:00:00+00:00,2991.1184380165637
2026-06-20 00:00:00+00:00,2991.1184380165637
2026-06-21 00:00:00+00:00,2991.1184380165637
2026-06-22 00:00:00+00:00,2991.1184380165637
2026-06-23 00:00:00+00:00,2991.1184380165637
2026-06-24 00:00:00+00:00,2991.1184380165637
2026-06-25 00:00:00+00:00,2991.1184380165637
2026-06-26 00:00:00+00:00,2991.1184380165637
2026-06-27 00:00:00+00:00,2991.1184380165637
2026-06-28 00:00:00+00:00,2991.1184380165637
2026-06-29 00:00:00+00:00,2991.1184380165637
2026-06-30 00:00:00+00:00,2991.1184380165637
2026-07-01 00:00:00+00:00,2991.1184380165637
2026-07-02 00:00:00+00:00,2991.1184380165637
2026-07-03 00:00:00+00:00,2989.8389465145638
2026-07-04 00:00:00+00:00,2989.853738823371
2026-07-05 00:00:00+00:00,2989.6102630642076
2026-07-06 00:00:00+00:00,2989.6102630642076
2026-07-07 00:00:00+00:00,2989.6102630642076
2026-07-08 00:00:00+00:00,2989.6102630642076
2026-07-09 00:00:00+00:00,2987.4125036626074
2026-07-10 00:00:00+00:00,2987.3700371296077
2026-07-11 00:00:00+00:00,2987.3700371296077
2026-07-12 00:00:00+00:00,2987.3700371296077
2026-07-13 00:00:00+00:00,2987.3700371296077
2026-07-14 00:00:00+00:00,2987.3700371296077
2026-07-15 00:00:00+00:00,2988.8068250420556
2026-07-16 00:00:00+00:00,2985.426017543316
2026-07-17 00:00:00+00:00,2985.515644469103
2026-07-18 00:00:00+00:00,2985.515644469103
2026-07-19 00:00:00+00:00,2985.515644469103
2026-07-20 00:00:00+00:00,2985.515644469103
2026-07-21 00:00:00+00:00,2985.515644469103
2026-07-22 00:00:00+00:00,2985.0185165176126
2026-07-23 00:00:00+00:00,2985.0185165176126
2026-07-24 00:00:00+00:00,2985.0185165176126
2026-07-25 00:00:00+00:00,2985.0185165176126
2026-07-26 00:00:00+00:00,2985.0185165176126
2026-07-27 00:00:00+00:00,2985.0185165176126
2026-07-28 00:00:00+00:00,2985.0185165176126
2026-07-29 00:00:00+00:00,2985.0185165176126
2026-07-30 00:00:00+00:00,2985.0185165176126
2026-07-31 00:00:00+00:00,2985.0185165176126
2026-08-01 00:00:00+00:00,2985.0185165176126
2026-08-02 00:00:00+00:00,2985.0185165176126
2026-08-03 00:00:00+00:00,2985.0185165176126
2026-08-04 00:00:00+00:00,2985.0185165176126
2026-08-05 00:00:00+00:00,2985.0185165176126
2026-08-06 00:00:00+00:00,2985.0185165176126
2026-08-07 00:00:00+00:00,2985.0185165176126
2026-08-08 00:00:00+00:00,2985.0185165176126
2026-08-09 00:00:00+00:00,2985.0185165176126
2026-08-10 00:00:00+00:00,2985.0185165176126
2026-08-11 00:00:00+00:00,2985.0185165176126
2026-08-12 00:00:00+00:00,2985.2085223070017
2026-08-13 00:00:00+00:00,2985.2085223070017
2026-08-14 00:00:00+00:00,2985.2085223070017
2026-08-15 00:00:00+00:00,2985.2085223070017
2026-08-16 00:00:00+00:00,2985.2085223070017
2026-08-17 00:00:00+00:00,2985.2085223070017
2026-08-18 00:00:00+00:00,2985.2085223070017
2026-08-19 00:00:00+00:00,2985.2085223070017
2026-08-20 00:00:00+00:00,2999.046737496931
2026-08-21 00:00:00+00:00,2998.490134469357
2026-08-22 00:00:00+00:00,2998.490134469357
2026-08-23 00:00:00+00:00,2998.490134469357
2026-08-24 00:00:00+00:00,2998.490134469357
2026-08-25 00:00:00+00:00,2998.490134469357
2026-08-26 00:00:00+00:00,2998.490134469357
2026-08-27 00:00:00+00:00,2998.490134469357
2026-08-28 00:00:00+00:00,2998.490134469357
2026-08-29 00:00:00+00:00,2998.490134469357
2026-08-30 00:00:00+00:00,2998.490134469357
2026-08-31 00:00:00+00:00,2998.490134469357
2026-09-01 00:00:00+00:00,2998.490134469357
2026-09-02 00:00:00+00:00,2998.490134469357
2026-09-03 00:00:00+00:00,2998.490134469357
2026-09-04 00:00:00+00:00,2998.490134469357
2026-09-05 00:00:00+00:00,2998.490134469357
2026-09-06 00:00:00+00:00,2998.490134469357
2026-09-07 00:00:00+00:00,2998.490134469357
2026-09-08 00:00:00+00:00,2998.490134469357
2026-09-09 00:00:00+00:00,2998.490134469357
2026-09-10 00:00:00+00:00,2998.490134469357
2026-09-11 00:00:00+00:00,2998.490134469357
2026-09-12 00:00:00+00:00,2998.490134469357
2026-09-13 00:00:00+00:00,2998.490134469357
2026-09-14 00:00:00+00:00,2998.490134469357
2026-09-15 00:00:00+00:00,2998.490134469357
2026-09-16 00:00:00+00:00,2998.490134469357
2026-09-17 00:00:00+00:00,2998.2867630332566
2026-09-18 00:00:00+00:00,2998.2867630332566
2026-09-19 00:00:00+00:00,2998.2867630332566
2026-09-20 00:00:00+00:00,2998.2867630332566
2026-09-21 00:00:00+00:00,2998.2867630332566
2026-09-22 00:00:00+00:00,3000.8487833180807
2026-09-23 00:00:00+00:00,3000.8487833180807
2026-09-24 00:00:00+00:00,3000.8487833180807
2026-09-25 00:00:00+00:00,3000.8487833180807
2026-09-26 00:00:00+00:00,3000.8487833180807
2026-09-27 00:00:00+00:00,3000.8487833180807
2026-09-28 00:00:00+00:00,3000.8487833180807
2026-09-29 00:00:00+00:00,3000.8487833180807
2026-09-30 00:00:00+00:00,3000.8487833180807
2026-10-01 00:00:00+00:00,3000.8487833180807
2026-10-02 00:00:00+00:00,3000.8487833180807
2026-10-03 00:00:00+00:00,3000.8487833180807
2026-10-04 00:00:00+00:00,3000.8487833180807
2026-10-05 00:00:00+00:00,3000.8487833180807
2026-10-06 00:00:00+00:00,3000.8487833180807
2026-10-07 00:00:00+00:00,
```

</details>


<details>
<summary>timing_controls.csv</summary>

SHA256 UTF-8/LF: `5054c982516c1c16586515ea743cc1f358ab686176764f2a43f9469392302a57`

```csv
offset_days,N,net,return_pct,DD_usd,net_half1,net_half2,gross,fees,funding,if_full_received_fee_refund,win_pct,PF,mean_R,median_hold_h,worst_trade_usd,turnover,cost_per_million_turnover,maximum_reserved_risk_frac,maximum_gross_frac,ambiguous_stop_target_minutes,skip_counts,exit_counts
79,39,1.3092002697871976,0.043640008992906584,18.054819916192628,-12.35369133570839,13.662891605495588,9.381806007550171,8.123053093022225,0.050447355259266524,9.432253362809423,41.02564102564102,1.030589983059035,0.003831551293813438,8.0,-7.178954978299973,16246.106186044448,-80.58548028645858,0.004983190590001448,0.29119413109241127,0,"{'price_departed_over_005pct': 28, 'position_already_open': 5}","{'TIME': 37, 'TP': 1, 'SL': 1}"
30,39,-25.739287407930078,-0.8579762469310026,43.03955487349185,-24.36050690136244,-1.3787805065676366,-17.547427441999638,8.169995032943,-0.021864932987005377,-17.56929237498708,43.58974358974359,0.48243295459731333,-0.08626143893006909,8.0,-7.3995624508413815,16339.990065885995,1575.2327451941098,0.004963907908693805,0.3428512077453452,0,"{'position_already_open': 7, 'price_departed_over_005pct': 26}","{'TIME': 35, 'SL': 4}"
19,30,-29.296342988736797,-0.9765447662912266,35.08678153703613,-13.805146457568753,-15.491196531168043,-22.86891620599979,6.323317548959,-0.10410923377713927,-22.973025439777796,23.333333333333332,0.3105434539888602,-0.1337411267545723,8.0,-7.328125312899005,12646.635097917999,2316.532639860845,0.0049710565362526375,0.213792273698198,0,"{'price_departed_over_005pct': 36, 'position_already_open': 6}","{'TIME': 28, 'SL': 2}"
73,32,-29.239464791459795,-0.9746488263819932,29.321360839459885,-17.882402639414977,-11.357062152044819,-20.86573447999988,8.587437943075999,0.21370763161576892,-20.652026848383798,34.375,0.3575905474794113,-0.12448449306911324,8.0,-7.178954978299973,17174.875886151996,1702.455667527438,0.004979712737966084,0.4850947242375038,0,"{'price_departed_over_005pct': 35, 'position_already_open': 4, 'stop_invalid_or_under_05pct': 1}","{'TIME': 29, 'SL': 3}"
95,38,-41.994626843707465,-1.3998208947902488,51.028719031126,-17.064374632249837,-24.930252211457628,-32.71885025799942,9.387053541403002,0.11127695569394044,-32.60757330230446,28.947368421052634,0.3409928019562179,-0.14893508868647184,8.0,-7.285170106933005,18774.107082806007,2236.8375048935154,0.004973076269533482,0.37788978365045506,0,"{'position_already_open': 8, 'price_departed_over_005pct': 26}","{'TIME': 34, 'SL': 3, 'END': 1}"
107,35,-4.4532045252367425,-0.14844015084122475,16.951214961802634,4.6847838609969585,-9.137988386233701,1.9717528000003082,6.4321175455400015,0.007160220301715851,1.978913020303259,31.428571428571427,0.8234826712373494,-0.018191977719918123,8.0,-3.1234136537109722,12864.235091080001,346.16939862398607,0.004989643362648847,0.18312284809119414,0,"{'price_departed_over_005pct': 32, 'position_already_open': 5}",{'TIME': 35}
64,37,-19.530687347457842,-0.651022911581928,31.1225078267521,-23.16480703843854,3.6341196909806968,-12.211780997999528,7.323678423231001,0.004772073772092587,-12.207008924226841,40.54054054054054,0.5093764108819467,-0.07141710086654718,8.0,-7.403969076174007,14647.356846462002,1333.393290829491,0.00498631410406952,0.18808134002260896,0,"{'price_departed_over_005pct': 29, 'position_already_open': 6}","{'TIME': 34, 'SL': 3}"
143,35,-3.038955483965765,-0.10129851613219217,21.420244868953432,9.194098031075555,-12.23305351504132,5.239375178320098,8.320040197460843,0.041709535175312104,5.281084713495078,48.57142857142857,0.9215604184802709,-0.011766955191411205,8.0,-7.392920826729985,16640.080394921682,182.6286539392689,0.004974028165046944,0.3120667795217811,0,"{'price_departed_over_005pct': 30, 'position_already_open': 7}","{'TIME': 32, 'SL': 2, 'TP': 1}"
52,37,-3.680999760782015,-0.12269999202606716,25.638583459749043,-21.156357752814984,17.47535799203297,3.871315512249951,7.611957407766123,0.05964213473492569,3.9309576469841083,40.54054054054054,0.9115178101134154,-0.014457186184053096,8.0,-7.336271881699988,15223.914815532253,241.79061728764154,0.004988227304176084,0.23271079630547414,0,"{'price_departed_over_005pct': 26, 'position_already_open': 9}","{'TIME': 34, 'SL': 2, 'TP': 1}"
106,34,-37.82394934957438,-1.2607983116524792,41.66380605002951,-22.483699508371956,-15.340249841202422,-30.9033410379998,6.914930408737002,-0.005677902835943504,-30.909018940837377,20.588235294117645,0.12658396644254652,-0.15161571563306078,8.0,-7.077924370699991,13829.860817474007,2734.9479397351474,0.0049754840028108215,0.1740273785554534,0,"{'price_departed_over_005pct': 33, 'position_already_open': 5}","{'TIME': 33, 'SL': 1}"
46,33,11.008733245243548,0.3669577748414516,17.96795073229987,-3.63316832090959,14.641901566153138,17.98170867464011,7.023193234301322,0.05021780490344832,18.03192647954487,42.42424242424242,1.359010079702944,0.04561947754658026,8.0,-7.351484736857966,14046.386468602643,-783.7413038471462,0.004953709678070813,0.2697046592934156,0,"{'price_departed_over_005pct': 32, 'position_already_open': 7}","{'TIME': 31, 'TP': 1, 'SL': 1}"
49,26,3.352411868123454,0.1117470622707818,14.716718707928976,-1.1435339852091602,4.495945853332614,7.980117360000141,4.712305613496,0.08460012161936623,8.064717481619454,42.30769230769231,1.1534137148392958,0.014952693655085855,8.0,-3.5068353405000043,9424.611226991998,-355.70823956347164,0.004928463533076536,0.1530404182965506,0,"{'price_departed_over_005pct': 41, 'position_already_open': 5}",{'TIME': 26}
114,38,-11.10102547682709,-0.370034182560903,31.868363956484245,3.6576763584939727,-14.758701835321062,-3.553494463999683,7.6474362094520005,0.0999051966251076,-3.453589267375089,44.73684210526316,0.7131013655537889,-0.03946502718275078,8.0,-7.402737632499494,15294.872418903995,725.8004625855239,0.004969333029618384,0.19534790908769833,0,"{'position_already_open': 9, 'price_departed_over_005pct': 24, 'stop_invalid_or_under_05pct': 1}","{'TIME': 37, 'SL': 1}"
123,29,-24.96400757034644,-0.8321335856782146,32.113330861203394,-20.41739647600116,-4.54661109434528,-19.289087629999692,5.698745775958999,0.02382583561168503,-19.265261794387442,41.37931034482759,0.38598872926567473,-0.11644374652174551,8.0,-7.346108729392989,11397.491551917998,2190.3071791393813,0.004923150370296621,0.18644383692208044,0,"{'price_departed_over_005pct': 33, 'position_already_open': 10}","{'TIME': 27, 'SL': 2}"
7,33,2.209310529393406,0.07364368431311352,12.041933745240385,5.987547626725245,-3.7782370973318393,8.733659545760222,6.502572002131122,-0.021777014235029896,8.711882531524527,39.39393939393939,1.0816354808219908,0.008765409165938877,8.0,-4.413914310067023,13005.144004262242,-169.87974363600566,0.00497172478770978,0.15496961095760176,0,"{'price_departed_over_005pct': 35, 'position_already_open': 4}","{'TIME': 32, 'TP': 1}"
47,34,2.391232402872447,0.0797077467624149,30.21514289357947,-19.413866363570833,21.80509876644328,10.201253705278587,7.8593984223026405,0.049377119897148415,10.250630825175087,35.294117647058826,1.0581515717348011,0.009118763889357352,8.0,-7.351484736857966,15718.796844605278,-152.12566372044705,0.004982485833072448,0.2326276514067507,0,"{'position_already_open': 4, 'price_departed_over_005pct': 34}","{'TIME': 29, 'SL': 2, 'TP': 2, 'END': 1}"
109,37,-34.00681277693502,-1.133560425897834,34.205402927972045,-24.106784740519743,-9.900028036415279,-25.526078187999683,8.515797681975998,0.03506309304092474,-25.491015094959025,51.35135135135135,0.39300869614620754,-0.12485017343254481,8.0,-7.361113804115999,17031.595363952,1996.6898021139987,0.004981375098879738,0.4159750585247778,0,"{'position_already_open': 7, 'price_departed_over_005pct': 28}","{'TIME': 32, 'SL': 5}"
99,40,-26.6206255222628,-0.8873541840754267,46.46788685326692,-10.650856452728021,-15.969769069534777,-19.259617919999435,7.444246428191998,0.08323882592928612,-19.1763790940708,35.0,0.42661984980932305,-0.09217024274544576,8.0,-7.361113804115999,14888.492856384,1788.0000198171977,0.004940988420254299,0.20444187766530783,0,"{'position_already_open': 8, 'price_departed_over_005pct': 24}","{'TIME': 38, 'SL': 2}"
13,34,-16.42067486320593,-0.5473558287735311,28.660209046113778,-1.5815047932774178,-14.839170069928514,-9.9028641799997,6.4866611808200005,-0.031149502385050265,-9.934013682385931,52.94117647058824,0.5852634598937966,-0.06429572253068574,8.0,-7.357825389319962,12973.322361640001,1265.7262654444778,0.004992571681398908,0.2287447140406509,0,"{'price_departed_over_005pct': 30, 'position_already_open': 8}","{'TIME': 31, 'SL': 3}"
124,30,-36.66442811274419,-1.2221476037581396,42.59758062102219,-9.945279883022977,-26.719148229721213,-31.062729309999774,5.731351152018998,0.12965234927277977,-30.93307696072519,23.333333333333332,0.22353029275673764,-0.16670733292013165,8.0,-7.276915983903947,11462.702304038003,3198.585040442714,0.004907423552127958,0.1844642829632726,0,"{'price_departed_over_005pct': 35, 'position_already_open': 7}","{'TIME': 27, 'SL': 2, 'END': 1}"
36,40,-23.595262407182418,-0.7865087469060805,39.29168664900044,-8.076846624360769,-15.518415782821648,-15.963941177999924,7.471029242553002,-0.16029198662974548,-16.124233164629416,25.0,0.4531048775229457,-0.08021435209463659,8.0,-3.8766456257448323,14942.058485106001,1579.1172568827642,0.0049796432842968445,0.20619218121462196,0,"{'position_already_open': 7, 'price_departed_over_005pct': 25}",{'TIME': 40}
29,35,16.078225569384813,0.5359408523128271,16.064341726242674,-5.116372691677498,21.19459826106231,23.032551853668203,6.818196939846835,-0.13612934443675637,22.89642250923165,54.285714285714285,1.4616497548646379,0.06159643039457164,8.0,-7.178954978299973,13636.393879693664,-1179.0672601007332,0.004983628779189836,0.1780526376055583,0,"{'price_departed_over_005pct': 32, 'position_already_open': 5}","{'TIME': 32, 'TP': 2, 'SL': 1}"
17,39,-1.6054244605297754,-0.053514148684325843,17.652883841813946,2.877008870689224,-4.482433331218999,6.637034650000358,8.122787386385,-0.11967172414630839,6.517362925855224,41.02564102564102,0.9525543918090577,-0.004576559524048245,8.0,-7.098795733680035,16245.574772770005,98.82226286143505,0.00498057149730259,0.21394945677331437,0,"{'position_already_open': 6, 'price_departed_over_005pct': 27}","{'TIME': 37, 'SL': 1, 'END': 1}"
139,35,-24.97944625678747,-0.8326482085595823,35.10230154986675,-15.728330345130871,-9.251115911656598,-17.639082861999672,7.419033622146998,0.07867022735918756,-17.56041263464047,34.285714285714285,0.4157795814308663,-0.09761557404394493,8.0,-7.1343046592,14838.067244293996,1683.4703499806121,0.004974136928928845,0.2029984535721062,0,"{'price_departed_over_005pct': 31, 'position_already_open': 6}","{'TIME': 33, 'SL': 1, 'END': 1}"
98,32,-9.074758495414699,-0.3024919498471566,34.884609111537884,-2.229849234749963,-6.8449092606647355,-2.447182607999929,6.588256501188,-0.039319386225803714,-2.486501994226699,46.875,0.7662798955348079,-0.03735425186231607,8.0,-7.371708825600028,13176.513002376,688.7071331981633,0.004985041522618534,0.20428811998943358,0,"{'position_already_open': 8, 'price_departed_over_005pct': 31, 'stop_invalid_or_under_05pct': 1}","{'TIME': 30, 'SL': 2}"
45,39,-37.170242725020216,-1.2390080908340073,43.52248854886875,-16.32176511658463,-20.848477608435587,-28.12897025800005,9.094203094129004,0.05293062710953213,-28.076039630891213,35.8974358974359,0.347305043299727,-0.12911441138144178,8.0,-7.341935165855985,18188.406188258003,2043.622862844158,0.004985958229512045,0.2910809861467596,0,"{'position_already_open': 8, 'price_departed_over_005pct': 25}","{'TIME': 36, 'SL': 3}"
27,31,-6.422256889345135,-0.21407522964483786,28.590502082678995,-18.063767589939744,11.641510700594608,-0.038285611999504976,6.231713784559998,-0.15225749278291387,-0.19054310478513692,45.16129032258064,0.7956996453063189,-0.026927239149864574,8.0,-7.341935165855985,12463.427569120002,515.2881784507846,0.004978274964573362,0.2165745723867091,0,"{'price_departed_over_005pct': 33, 'position_already_open': 7, 'stop_invalid_or_under_05pct': 1}","{'TIME': 29, 'SL': 2}"
101,35,-18.925374701126657,-0.6308458233708886,22.80656653649612,-5.509638024905598,-13.415736676221059,-11.148615415999542,7.75628934461,-0.020469940518201488,-11.169085356516657,48.57142857142857,0.5520560234587069,-0.0704951784524372,8.0,-7.328706101469991,15512.578689220003,1220.0018501294226,0.004973558624359618,0.22899778458974995,0,"{'position_already_open': 7, 'price_departed_over_005pct': 30}","{'TIME': 32, 'SL': 3}"
22,32,-9.840289307481726,-0.3280096435827242,20.189180715278326,2.520925421037191,-12.361214728518917,-3.49162228399986,6.377905804046001,0.029238780564872693,-3.462383503435725,31.25,0.7012684609601434,-0.0432838564623875,8.0,-7.14701467199999,12755.811608092004,771.4357666774621,0.004934621341294801,0.15658007176928931,0,"{'price_departed_over_005pct': 34, 'position_already_open': 6}","{'TIME': 31, 'SL': 1}"
67,32,4.353858263821621,0.14512860879405404,12.781243873806034,-4.9451024795339436,9.298960743355565,11.33955133800031,7.138195235517001,0.152502161335794,11.492053499338622,40.625,1.2163813816091273,0.01860948473537808,8.0,-4.254248739679918,14276.390471034,-304.969121757727,0.0049775210631136345,0.18435851935000386,0,"{'price_departed_over_005pct': 36, 'position_already_open': 4}",{'TIME': 32}
113,40,-21.974630485145553,-0.7324876828381851,32.50091184973826,-23.63495477649667,1.6603242913511167,-14.104266659999581,7.936467742968001,0.06610391782190214,-14.038162742177551,42.5,0.406337025260205,-0.0747898241319078,8.0,-4.254248739679918,15872.935485936005,1384.408731744413,0.004971412074999401,0.2505863421822532,0,"{'position_already_open': 8, 'price_departed_over_005pct': 24}",{'TIME': 40}
74,33,-21.593341894017158,-0.7197780631339052,41.327109855788876,-7.7112815544933255,-13.882060339523832,-13.23298884999957,8.451698110231003,0.09134506621168893,-13.141643783786154,39.39393939393939,0.4539768870209064,-0.0886879368837623,8.0,-7.139178317668795,16903.396220462,1277.4558208531996,0.004986733740954326,0.27157546590418913,0,"{'price_departed_over_005pct': 34, 'position_already_open': 5}","{'TIME': 31, 'SL': 2}"
115,34,-28.20940599812093,-0.9403135332706977,32.72077590287881,-16.28441187842691,-11.92499411969402,-20.804293535999985,7.387785624917998,-0.01732683720216624,-20.82162037320293,44.11764705882353,0.36079367753347436,-0.11168186394604895,8.0,-7.337801337477569,14775.571249836003,1909.1922417844949,0.004975728078356418,0.20812326148572877,0,"{'position_already_open': 6, 'price_departed_over_005pct': 32}","{'TIME': 31, 'SL': 3}"
111,44,-14.10621585234776,-0.4702071950782587,30.647628350347986,-9.872041196477767,-4.234174655869992,-5.320993647999733,8.66448430552,-0.12073789882620468,-5.441731546827759,50.0,0.7297663450136098,-0.04457779924795183,8.0,-7.371708825600028,17328.96861104,814.02512572854,0.004975865871236671,0.23276077031468065,0,"{'price_departed_over_005pct': 24, 'position_already_open': 4}","{'TIME': 39, 'SL': 5}"
116,36,11.819737699802772,0.39399125666009244,19.019816799374894,12.388182193881676,-0.5684444940789035,20.168561388490108,8.344513053138243,-0.004310635549609632,20.164250752941015,50.0,1.3565677589629843,0.04359507432569975,8.0,-7.193132798499977,16689.026106276488,-708.2341189074867,0.004991273944194228,0.2960635134941896,0,"{'price_departed_over_005pct': 26, 'position_already_open': 10}","{'TIME': 34, 'TP': 1, 'SL': 1}"
39,33,-45.20377123676644,-1.5067923745588814,50.10578812789072,-11.220303116513605,-33.98346812025284,-37.52957615199975,7.637693827450002,-0.03650125731684092,-37.56607740931644,33.33333333333333,0.2772731088176461,-0.18720497849537268,8.0,-7.336271881699988,15275.3876549,2959.2552580664683,0.004959101133237773,0.3458159911514732,0,"{'price_departed_over_005pct': 34, 'position_already_open': 4, 'stop_invalid_or_under_05pct': 1}","{'TIME': 30, 'SL': 3}"
63,35,-27.23670002521112,-0.9078900008403707,40.96292103655924,-28.643206436864602,1.4065064116534813,-19.88281972799968,7.4199010114859965,0.06602071427377282,-19.816799013725124,31.428571428571427,0.44263785688431617,-0.10449661663396616,8.0,-7.207468887229621,14839.802022972002,1835.3816299603411,0.004969225491498447,0.1641877927195073,0,"{'price_departed_over_005pct': 33, 'position_already_open': 4}","{'TIME': 34, 'SL': 1}"
58,34,-23.61290172129975,-0.7870967240433249,32.13781968725243,-15.412597754130275,-8.200303967169475,-17.10410585599986,6.552366088315998,0.043570223017184904,-17.06053563298375,44.11764705882353,0.4225786987374224,-0.09723077536333391,8.0,-7.244307515315029,13104.732176631998,1801.8606868903155,0.004992321325463895,0.2374821308062655,0,"{'price_departed_over_005pct': 34, 'position_already_open': 4}","{'TIME': 32, 'SL': 2}"
145,35,26.49827558882589,0.8832758529608631,16.57912449042942,19.755584716028352,6.742690872797539,33.63813364600043,7.174937234189001,0.035079177013306054,33.67321282301489,54.285714285714285,2.0045070088014443,0.10289654814285731,8.0,-7.403969076174007,14349.874468377999,-1846.5858810973316,0.004998219797439837,0.18219849758451967,0,"{'position_already_open': 6, 'price_departed_over_005pct': 31}","{'TIME': 34, 'SL': 1}"
44,32,8.589555567851221,0.28631851892837407,14.85997271539054,6.552576833255898,2.0369787345953227,16.145444349697605,7.657865984896852,0.10197720304898865,16.247421552748072,56.25,1.430900945328109,0.0360824040782083,8.0,-7.178954978299973,15315.7319697937,-560.8321942948522,0.004964905071226531,0.30674881821988986,0,"{'price_departed_over_005pct': 33, 'position_already_open': 7}","{'TIME': 30, 'TP': 1, 'SL': 1}"
126,37,-14.224877443513833,-0.4741625814504611,18.741345019212076,-6.4004812463863345,-7.8243961971274985,-7.289324983999639,7.079512905751999,0.14396044623771773,-7.145364537761834,35.13513513513514,0.5039799120183063,-0.05080531585842132,8.0,-3.806118545439987,14159.025811504001,1004.6508589564352,0.004950374716311933,0.18917348837548267,0,"{'price_departed_over_005pct': 29, 'position_already_open': 6}",{'TIME': 37}
121,33,-31.80664509658982,-1.0602215032196607,38.622489284455696,-13.707264531289184,-18.099380565300635,-25.040499157999914,6.802425126953,0.03627918836174465,-25.004219969636818,24.242424242424242,0.13291718012639753,-0.13239385645313367,8.0,-7.1343046592,13604.850253906001,2337.8901276372385,0.004971635641942535,0.13734648707678634,0,"{'position_already_open': 5, 'price_departed_over_005pct': 34}","{'TIME': 32, 'SL': 1}"
91,40,-32.2348402482462,-1.07449467494154,33.58965948026389,-8.123141913119525,-24.111698335126675,-23.737216327999626,8.509342853348002,0.011718933101731433,-23.7254973948982,35.0,0.3994379705382847,-0.10887765358428234,8.0,-7.327975836875967,17018.685706696,1894.0851722506047,0.004962858115246422,0.24177414622796128,0,"{'price_departed_over_005pct': 26, 'position_already_open': 6}","{'TIME': 37, 'SL': 3}"
32,34,-2.622150239774328,-0.0874050079924776,21.84844936966465,-6.502367420984683,3.880217181210355,5.840470956000284,8.457821687640001,-0.0047995081341191455,5.835671447865673,47.05882352941176,0.9260638516397594,-0.01048338333561532,8.0,-7.295920093570019,16915.643375279997,155.01333183733692,0.004979436124362855,0.29968890433063855,0,"{'price_departed_over_005pct': 32, 'position_already_open': 6}","{'TIME': 32, 'SL': 1, 'END': 1}"
41,38,-3.4860374446088827,-0.11620124815362942,25.934270559467677,4.327509460371857,-7.81354690498074,4.403144270000414,7.853613570540999,-0.035568144068725174,4.367576125932116,36.84210526315789,0.8832264686118438,-0.011036980715179986,8.0,-3.5477511344,15707.227141082007,221.93843721093242,0.0049845349776351305,0.2686127962136199,0,"{'position_already_open': 8, 'price_departed_over_005pct': 26}",{'TIME': 38}
48,31,17.166663734895792,0.5722221244965264,21.750903176343854,-16.561100450649974,33.727764185545766,23.24321730527859,6.102238188392637,0.02568461800948654,23.26890192328843,35.483870967741936,1.595243276754244,0.07372747392212149,8.0,-4.2234919013264305,12204.47637678528,-1406.5874851910341,0.0049754660697495885,0.17670730523294692,0,"{'price_departed_over_005pct': 35, 'position_already_open': 6}","{'TIME': 29, 'TP': 2}"
56,27,-24.428856833837017,-0.8142952277945672,32.99802211397946,-4.468247876340229,-19.960608957496788,-19.27875527799969,5.236214913427002,0.08611335758898603,-19.192641920410015,29.629629629629626,0.3715512613567546,-0.12155666937460341,8.0,-7.321249840203007,10472.429826854,2332.682790692486,0.004955186611095269,0.23297662477384165,0,"{'price_departed_over_005pct': 37, 'position_already_open': 5, 'stop_invalid_or_under_05pct': 3}","{'TIME': 25, 'SL': 2}"
69,28,28.939333426915255,0.9646444475638418,9.563716931243562,2.2849347929713986,26.654398633943856,34.785692718000064,5.921789489558999,0.07543019847502805,34.86112291647425,64.28571428571429,3.9434571664140794,0.13978718728134218,8.0,-2.708559772199975,11843.578979118,-2443.461852024597,0.004968299727821329,0.18213941548068954,0,"{'price_departed_over_005pct': 40, 'position_already_open': 4}",{'TIME': 28}
25,34,5.449335924752177,0.18164453082507256,24.36624958872926,1.0937028699713665,4.35563305478081,13.738478350000204,8.224077422189,-0.06506500306173535,13.673413346941176,44.11764705882353,1.1701784716002264,0.023886564601669557,8.0,-7.1501274754399375,16448.154844378005,-331.30378308754587,0.004981728482703026,0.23191752277495997,0,"{'price_departed_over_005pct': 30, 'position_already_open': 7, 'stop_invalid_or_under_05pct': 1}","{'TIME': 33, 'SL': 1}"
127,29,-28.604087594118482,-0.953469586470616,31.322022399123398,-9.510023021351117,-19.094064572767365,-22.30256484599975,6.453089087133001,0.15156633901272773,-22.15099850698548,31.03448275862069,0.1536880012100425,-0.13331019993478346,8.0,-6.940014963199829,12906.178174266,2216.30967803877,0.0049402520207336665,0.3134340138533987,0,"{'position_already_open': 4, 'price_departed_over_005pct': 39}","{'TIME': 28, 'SL': 1}"
9,42,-11.744528394136978,-0.3914842798045659,23.177846570601105,-6.271571877061433,-5.472956517075545,-4.096090137999676,7.586400451153004,-0.06203780498218536,-4.158127942983974,38.095238095238095,0.6826167765199199,-0.038163221174723594,8.0,-7.207468887229621,15172.800902306002,774.0514404530289,0.004951660133708114,0.16739499901820917,0,"{'price_departed_over_005pct': 24, 'position_already_open': 6}","{'TIME': 41, 'SL': 1}"
137,34,9.381514333455925,0.3127171444485309,12.143008441618804,-5.685638425594334,15.06715275905026,16.892312832640613,7.603007925048322,0.09220942586398478,16.98452225850425,32.35294117647059,1.3307388121753507,0.036537138823646474,8.0,-3.7986844875000036,15206.015850096643,-616.960709888797,0.004994030183396561,0.22653142913269392,0,"{'price_departed_over_005pct': 31, 'position_already_open': 7}","{'TIME': 33, 'TP': 1}"
65,35,2.7748194104956383,0.09249398034985461,28.456595509821454,-13.516787564706647,16.291606975202285,10.652959278640036,7.907617421799318,0.0294775536531839,10.682436832294957,45.714285714285715,1.0789013866725818,0.01212352336156594,8.0,-7.295920093570019,15815.234843598648,-175.45230519411288,0.004968501566458907,0.22330669302855524,0,"{'price_departed_over_005pct': 31, 'position_already_open': 6}","{'TIME': 32, 'SL': 2, 'TP': 1}"
26,27,-21.493683634072113,-0.7164561211357371,32.372125901550135,-9.209406157824105,-12.284277476248008,-15.620332499999607,5.8461325781880005,-0.027218555884790063,-15.647551055884112,44.44444444444444,0.5132134954172384,-0.10750828373042234,8.0,-7.247868667999973,11692.265156376001,1838.2822615300702,0.004984167362198811,0.17898001899608984,0,"{'position_already_open': 3, 'price_departed_over_005pct': 39, 'stop_invalid_or_under_05pct': 3}","{'TIME': 25, 'SL': 2}"
120,34,-11.470351248090992,-0.38234504160303306,27.497178648252884,-13.128249746052916,1.6578984979619236,-4.882016071999567,6.538190406673999,-0.05014476941888903,-4.9321608414169935,50.0,0.6659251275101984,-0.045636980365414165,8.0,-7.3797312471110335,13076.380813348002,877.1808814547815,0.004953747007311122,0.17962173506928475,0,"{'price_departed_over_005pct': 32, 'position_already_open': 6}","{'TIME': 32, 'SL': 2}"
80,38,13.923532504440118,0.46411775014800394,16.924814001199138,9.493612277868579,4.429920226571539,21.974019956000284,7.983847593243998,-0.06663985831674998,21.907380097684115,63.1578947368421,1.808115666614214,0.049441315796235216,8.0,-3.285679710999967,15967.695186487992,-871.9813562211743,0.0049848293183585544,0.310057323534189,0,"{'price_departed_over_005pct': 29, 'position_already_open': 5}",{'TIME': 38}
24,33,22.57435739707944,0.752478579902648,14.814362210478066,7.845127439069529,14.72922995800991,30.15658159832008,7.618571683798843,0.03634748255905922,30.19292908087828,51.515151515151516,1.9971326584012055,0.09306687579537945,8.0,-7.392920826729985,15237.143367597688,-1481.5347504759054,0.004973314209582548,0.3122495376,0,"{'price_departed_over_005pct': 31, 'position_already_open': 6, 'stop_invalid_or_under_05pct': 2}","{'TIME': 31, 'TP': 1, 'SL': 1}"
57,34,-20.036513681872293,-0.6678837893957431,24.06506488806417,-12.546832019933845,-7.489681661938448,-13.67581968999969,6.3894753370030015,0.028781345130708905,-13.64703834486929,38.23529411764706,0.38421843599791894,-0.07878922696070093,8.0,-7.282131107264966,12778.950674006006,1567.931060460941,0.004958186644999161,0.18520892557428256,0,"{'price_departed_over_005pct': 31, 'position_already_open': 7}","{'TIME': 33, 'SL': 1}"
66,39,24.370140251473913,0.8123380083824637,15.691609287985102,3.5224235479709023,20.84771670350301,32.63405290361026,8.276834271496195,0.012921619360130346,32.64697452297011,48.717948717948715,1.9830580355296763,0.08486757327017837,8.0,-4.222217837359989,16553.668542992396,-1472.1896954853814,0.004986736542748873,0.2764295076233817,0,"{'price_departed_over_005pct': 26, 'position_already_open': 7}","{'TIME': 38, 'TP': 1}"
8,37,-2.4644912361200113,-0.08214970787066704,26.318726992252323,18.873587471487554,-21.338078707607565,4.782107722000244,7.218354928054998,-0.02824403006661451,4.753863691934987,48.64864864864865,0.931318737916894,-0.007757670822602629,8.0,-7.2661326839999765,14436.709856110001,170.71003439727457,0.004954746283957004,0.13399099862663036,0,"{'price_departed_over_005pct': 28, 'position_already_open': 6, 'stop_invalid_or_under_05pct': 1}","{'TIME': 36, 'SL': 1}"
21,37,-20.216680331219777,-0.6738893443739926,24.232788822547263,-9.543174188926514,-10.673506142293263,-13.241952399999587,6.982932044877997,0.008204113656289463,-13.233748286341779,35.13513513513514,0.4821667965937166,-0.07432225139915198,8.0,-7.328706101469991,13965.864089755998,1447.5781950397736,0.004978147695646332,0.18278100544815334,0,"{'position_already_open': 4, 'price_departed_over_005pct': 31}","{'TIME': 36, 'SL': 1}"
88,38,-25.262187472891583,-0.8420729157630527,42.33402112454223,2.9105462615511897,-28.172733734442772,-16.961885400239645,8.37081186195612,0.07050978930348342,-16.891375610935462,31.57894736842105,0.5050929468181026,-0.09124878765234821,8.0,-7.3315724643020035,16741.62372391224,1508.9448842891704,0.004978178639679399,0.20293525342698276,0,"{'price_departed_over_005pct': 30, 'position_already_open': 4}","{'TIME': 34, 'SL': 3, 'TP': 1}"
92,43,-52.32572791956818,-1.7441909306522725,57.074991295382006,-15.403362427726279,-36.9223654918419,-43.23084404799951,9.117364078389997,0.022480206820184357,-43.20836384117818,30.23255813953488,0.23728366977173249,-0.16585540521216285,8.0,-7.250018647121967,18234.728156780002,2869.564463461032,0.004988338704749912,0.18178135051570754,0,"{'price_departed_over_005pct': 21, 'position_already_open': 8}","{'TIME': 40, 'SL': 3}"
76,43,-13.412872767117278,-0.4470957589039093,35.5047495850813,2.7112506354815196,-16.124123402598798,-4.510712363999316,8.969531002290001,0.06737059917430664,-4.443341764827277,41.86046511627907,0.7383475324511826,-0.04206996192589685,8.0,-7.357825389319962,17939.06200458,747.6908638641672,0.004980225556393621,0.2051122244416292,0,"{'price_departed_over_005pct': 24, 'position_already_open': 5}","{'TIME': 40, 'SL': 2, 'END': 1}"
42,37,-43.45557160645194,-1.448519053548398,47.29819390933153,-22.27081409461607,-21.18475751183587,-35.54700516599941,7.989441150122998,0.08087470967157254,-35.46613045632894,24.324324324324326,0.24059040296462408,-0.15938585559589216,8.0,-7.27384607903998,15978.882300246007,2719.5626571317134,0.004989833008004653,0.2583689105518003,0,"{'position_already_open': 7, 'price_departed_over_005pct': 25, 'stop_invalid_or_under_05pct': 3}","{'TIME': 34, 'SL': 3}"
125,39,-36.55570242127396,-1.2185234140424654,39.56581014937683,-15.932301737122089,-20.623400684151875,-29.9942799619998,6.593627640683003,0.032205181407756335,-29.96207478059096,30.76923076923077,0.280278085888063,-0.1276790530575595,8.0,-7.271036698719973,13187.255281366,2772.0478326470484,0.0049863968543740365,0.18515747181446124,0,"{'position_already_open': 6, 'price_departed_over_005pct': 27}","{'TIME': 37, 'SL': 2}"
55,35,16.53453564002666,0.5511511880008887,17.91766394543629,-4.236844287491749,20.77137992751841,23.499942684000402,7.004490659825999,0.03908361585102582,23.539026299852658,51.42857142857142,1.7453666567555652,0.06414151489813369,8.0,-3.896942199701612,14008.981319651999,-1180.2810827388125,0.0049903670836230745,0.26869238519133504,0,"{'price_departed_over_005pct': 31, 'position_already_open': 5, 'stop_invalid_or_under_05pct': 1}",{'TIME': 35}
75,39,-9.583493486142288,-0.3194497828714096,32.189550449664694,0.4092462404523758,-9.992739726594664,-0.21607040399960975,9.425775654576,0.05835257243357136,-0.15771783156628771,51.28205128205128,0.7825286586414189,-0.03367954193432435,8.0,-7.3315724643020035,18851.551309152,508.3663051904763,0.004982910667720268,0.34727991256071244,0,"{'price_departed_over_005pct': 29, 'position_already_open': 3, 'stop_invalid_or_under_05pct': 1}","{'TIME': 36, 'SL': 3}"
38,30,-10.345312694211316,-0.3448437564737105,28.685344145187628,3.6381942253779016,-13.983506919589217,-2.484343421999548,7.728533494292999,-0.13243577792187058,-2.6167791999183168,53.333333333333336,0.7093471758926445,-0.044237700645061356,8.0,-7.263306483125961,15457.066988586,669.2933854689658,0.0049781991292857045,0.23222493243674677,0,"{'position_already_open': 9, 'price_departed_over_005pct': 33}","{'TIME': 27, 'SL': 3}"
28,33,-14.778341709065444,-0.4926113903021815,28.672368809734508,-7.340360796016739,-7.437980913048705,-8.115761941999587,6.567480403876999,-0.0950993631875259,-8.210861305188445,42.42424242424242,0.542867092693032,-0.059696523094950056,8.0,-7.27384607903998,13134.960807754,1125.1150213056824,0.004994606038801851,0.237590813432324,0,"{'price_departed_over_005pct': 35, 'position_already_open': 4}","{'TIME': 32, 'SL': 1}"
85,37,-21.51179554447026,-0.7170598514823421,26.75048731220795,-7.118694401967332,-14.393101142502928,-12.796177473999899,8.749669614630998,0.03405154416243031,-12.762125929839263,29.72972972972973,0.3094735191612854,-0.07948952534179403,8.0,-7.0642131574999505,17499.339229262005,1229.291875689724,0.004973823001949217,0.29867289362744986,0,"{'price_departed_over_005pct': 31, 'position_already_open': 4}","{'TIME': 36, 'SL': 1}"
70,35,0.3629493073685808,0.01209831024561936,23.32471793995046,-4.432174148725153,4.795123456093734,7.01310209101327,6.662406144661507,0.012253361019899028,7.025355452030087,42.857142857142854,1.0118163490818846,0.0019888560406032523,8.0,-6.077513501802257,13324.81228932302,-27.238605654460653,0.004993331999455029,0.2016458303980536,0,"{'price_departed_over_005pct': 32, 'position_already_open': 5}","{'TIME': 34, 'TP': 1}"
37,38,-35.06597417138482,-1.1688658057128274,41.949621759729325,-5.266600296971319,-29.799373874413504,-27.161777817999674,7.767071950495001,-0.13712440289135489,-27.298902220889822,28.947368421052634,0.26967767616509275,-0.12714372973335444,8.0,-7.247868667999973,15534.143900989997,2257.3483543660273,0.004978777885149005,0.21876650506202672,0,"{'price_departed_over_005pct': 26, 'position_already_open': 6, 'stop_invalid_or_under_05pct': 2}","{'TIME': 36, 'SL': 2}"
51,37,9.9161045565329,0.3305368185510967,16.961693650360303,11.310801161156178,-1.3946966046232774,17.132135556000325,7.155159110579997,-0.060871888888379314,17.0712636671129,43.24324324324324,1.413002492556245,0.03494498811523549,8.0,-2.8061219779319524,14310.31822116,-692.9338958983051,0.004959588128616725,0.21752647998459243,0,"{'price_departed_over_005pct': 30, 'position_already_open': 5}",{'TIME': 37}
141,37,-3.3915695008172406,-0.11305231669390803,19.73951870868177,2.6895317247067396,-6.08110122552398,4.449716846000129,7.8698821252330005,0.028595778415377214,4.47831262441576,45.94594594594595,0.8973763386057515,-0.012152917843970669,8.0,-7.3797312471110335,15739.764250465996,215.47778269403423,0.004956848932789981,0.2119852202546624,0,"{'price_departed_over_005pct': 30, 'position_already_open': 5}","{'TIME': 36, 'SL': 1}"
31,34,-9.155334551779106,-0.30517781839263686,23.35267652991206,1.940504043267083,-11.095838595046189,-1.8566573759996938,7.149343339692001,-0.14933383608785614,-2.005991212087105,41.17647058823529,0.7373373266733954,-0.03765318158419784,8.0,-7.109851789699972,14298.686679384,640.2919902412692,0.004967781028495215,0.20795658190559901,0,"{'position_already_open': 6, 'price_departed_over_005pct': 32}","{'TIME': 33, 'SL': 1}"
71,32,-6.042755926685913,-0.2014251975561971,22.77045494879576,-6.337343892776062,0.29458796609014826,0.529650079013039,6.657386823207507,0.08498081750752466,0.6146308965215939,40.625,0.8313727018401177,-0.026551664038649253,8.0,-7.304348882510746,13314.773646415015,453.83842693509985,0.00497566496694738,0.2088414728430754,0,"{'price_departed_over_005pct': 37, 'position_already_open': 3}","{'TIME': 30, 'SL': 1, 'TP': 1}"
110,35,-32.22305179875002,-1.0741017266250006,38.54173847065522,-10.929944696636994,-21.293107102113026,-25.28896461199969,6.847963784977999,-0.08612340177238278,-25.37508801377202,51.42857142857142,0.39966714628793637,-0.12337398684161142,8.0,-7.3240567115470805,13695.927569955995,2352.746948621133,0.0049651089395561865,0.2519533509101468,0,"{'price_departed_over_005pct': 29, 'position_already_open': 7, 'stop_invalid_or_under_05pct': 1}","{'TIME': 31, 'SL': 4}"
10,41,1.60230552758685,0.05341018425289501,32.45083334674064,-0.296702379360795,1.899007906947645,9.932064116000202,8.435688379366004,0.10592979095402955,10.037993906952854,51.21951219512195,1.0427944402418912,0.005886827840397206,8.0,-7.373793306705998,16871.376758732004,-94.97183012984141,0.004971373033534576,0.3241010856877576,0,"{'price_departed_over_005pct': 24, 'position_already_open': 7}","{'TIME': 40, 'SL': 1}"
131,32,-7.030122852514523,-0.2343374284171508,17.768882545925862,-6.291284095573701,-0.7388387569408223,-1.439921487999663,5.56955364121,-0.020647723302719863,-1.4605692113045237,37.5,0.7592028888410529,-0.02856843315773135,8.0,-5.21933018879999,11139.10728242,631.1208496581793,0.0049752354612806315,0.1446216490205149,0,"{'price_departed_over_005pct': 35, 'position_already_open': 5}",{'TIME': 32}
23,37,-22.249523332709487,-0.7416507777569828,42.12940850394398,-21.25200518805741,-0.9975181446520764,-14.362526759999792,7.845118022448002,-0.04187855026289308,-14.404405310261485,40.54054054054054,0.5812652730829712,-0.08103973754274274,8.0,-7.331519337174031,15690.236044896,1418.0489872201258,0.0049833942116852435,0.22842994137199615,0,"{'position_already_open': 6, 'price_departed_over_005pct': 28, 'stop_invalid_or_under_05pct': 1}","{'TIME': 32, 'SL': 5}"
128,36,-18.84511909679759,-0.6281706365599197,39.26921519869575,-15.231160731713317,-3.6139583650842724,-11.828760953999652,7.086178284428999,0.06982014163040419,-11.75894081236859,36.11111111111111,0.6167437367073034,-0.07250094923910066,8.0,-7.361113804115999,14172.356568858006,1329.709636166465,0.004981598309821776,0.1721018044455166,0,"{'price_departed_over_005pct': 30, 'position_already_open': 5, 'stop_invalid_or_under_05pct': 1}","{'TIME': 34, 'SL': 2}"
132,27,-14.72399459392227,-0.49079981979740905,28.36843078879747,-1.5119645040435898,-13.21203008987868,-9.490696219999787,5.334841285676001,0.10154291175468441,-9.38915330824627,33.33333333333333,0.5598302654819777,-0.07447141121864374,8.0,-4.275698808599989,10669.682571352001,1379.9843149463563,0.00496847217538681,0.25074140944011625,0,"{'price_departed_over_005pct': 40, 'position_already_open': 5}",{'TIME': 27}
100,32,12.54568458975018,0.418189486325006,21.17769347643889,12.012845193491103,0.5328393962590781,19.136480180000454,6.571697373484,-0.019098216765876003,19.11738196323418,56.25,1.8021149402294672,0.05249565665768893,8.0,-2.3827028445136924,13143.394746967999,-954.5239134390525,0.004978783997781181,0.18347176690347466,0,"{'position_already_open': 8, 'price_departed_over_005pct': 32}",{'TIME': 32}
18,33,-0.8224232548814143,-0.027414108496047144,21.51520775482868,4.0198948840625235,-4.842318138943938,6.269395264000416,6.988160933534001,-0.10365758534926926,6.165737678652587,48.484848484848484,0.9748139272777199,-0.004013214891644168,8.0,-3.9366141552099765,13976.321867067998,58.84404085020869,0.004974023898160982,0.1870599617379899,0,"{'price_departed_over_005pct': 35, 'position_already_open': 4}",{'TIME': 33}
119,33,9.210605559777832,0.30702018532592773,23.37455703081787,-5.6102424543837515,14.820848014161584,16.846161257438624,7.683776884436719,0.04822118677721808,16.89438244421455,39.39393939393939,1.2328450473228538,0.037809361417070586,8.0,-7.130754634076977,15367.553768873438,-599.3540480355216,0.0049798719910600885,0.23491961605223427,0,"{'price_departed_over_005pct': 31, 'position_already_open': 8}","{'TIME': 29, 'SL': 2, 'TP': 2}"
104,33,-23.983215090243903,-0.7994405030081302,27.561920096282392,-19.979764971680652,-4.003450118563251,-17.35690847999952,6.635622670266002,0.009316060021306059,-17.3475924199779,42.42424242424242,0.5100219346666964,-0.10033379954917929,8.0,-7.290874829171989,13271.245340532005,1807.156334982086,0.004956458149723825,0.1859380937069043,0,"{'price_departed_over_005pct': 33, 'position_already_open': 5, 'stop_invalid_or_under_05pct': 1}","{'TIME': 29, 'SL': 4}"
97,29,23.152710523092537,0.7717570174364179,14.696388046086668,4.673968718702326,18.47874180439021,29.14663558600025,6.000532880315002,0.006607817406558376,29.15324340340754,72.41379310344827,2.9667885777207794,0.10973809472736942,8.0,-7.29497817750002,12001.065760630003,-1929.2212029239913,0.004978652240952742,0.16649125786203484,0,"{'position_already_open': 7, 'price_departed_over_005pct': 36}","{'TIME': 28, 'SL': 1}"
117,40,4.03056702188087,0.13435223406269567,15.054552792750655,4.780391703372516,-0.7498246814916456,12.156505270000295,8.003860289195002,-0.12207795892244713,12.034427311075872,42.5,1.1910298867345541,0.011662681691974635,8.0,-2.9996259006072967,16007.720578389999,-251.78894160121894,0.004976809359091544,0.2999163287551091,0,"{'price_departed_over_005pct': 23, 'position_already_open': 9}",{'TIME': 40}
87,33,-28.63039709359009,-0.9543465697863364,34.81596367527936,-13.775499549785309,-14.854897543804782,-21.34301301799967,7.351959385223,0.06457530963464352,-21.27843770836709,42.42424242424242,0.4379024896147312,-0.11897633745138127,8.0,-7.107264244999935,14703.918770445998,1947.1269897882928,0.004937816764061074,0.15794892680335437,0,"{'price_departed_over_005pct': 32, 'position_already_open': 7}","{'TIME': 31, 'SL': 2}"
103,40,-46.82414469079504,-1.5608048230265013,61.840822234956704,-17.482933993819188,-29.34121069697585,-38.280976789999784,8.465470464478997,-0.07769743631700593,-38.35867422631604,47.5,0.2599012321916564,-0.15861242517336768,8.0,-7.382611545479976,16930.940928958003,2765.596128842957,0.004947320102318899,0.18418265312615684,0,"{'position_already_open': 8, 'price_departed_over_005pct': 24}","{'TIME': 34, 'SL': 5, 'END': 1}"
86,40,-5.679868945267117,-0.1893289648422372,41.1548564094669,6.774195314639655,-12.454064259906772,4.479834763610016,10.167282361300195,0.007578652422745486,4.487413416033078,42.5,0.8843584984109928,-0.01941638667675764,8.0,-7.2307062448183945,20334.56472260039,279.32090127084723,0.004981165453129227,0.33956619093084717,0,"{'price_departed_over_005pct': 26, 'position_already_open': 6}","{'TIME': 37, 'SL': 2, 'TP': 1}"
140,33,20.50453903995185,0.6834846346650617,13.047608239847705,23.293580720158843,-2.789041680206992,28.082381586319947,7.567671923254842,-0.010170623112918397,28.072210963206693,48.484848484848484,1.9971922513859528,0.08103316431566561,8.0,-4.3056520052400025,15135.343846509682,-1354.7455048191946,0.0049602947769335146,0.46930261253296596,0,"{'price_departed_over_005pct': 33, 'position_already_open': 5, 'stop_invalid_or_under_05pct': 1}","{'TIME': 32, 'TP': 1}"
72,36,-18.954703760894063,-0.6318234586964687,32.95973493481415,-20.545866108602695,1.5911623477086323,-10.334977481999482,8.608619394153,-0.011106884743689583,-10.346084366741064,41.66666666666667,0.5771985999808745,-0.07314127726939695,8.0,-7.0642131574999505,17217.238788306004,1100.9142635442886,0.004955232940236389,0.28922050424295126,0,"{'price_departed_over_005pct': 32, 'position_already_open': 4}","{'TIME': 35, 'SL': 1}"
112,36,-14.178017673124486,-0.4726005891041495,31.31397005251256,-7.945852833574463,-6.232164839550023,-6.149224815999412,7.964262336352001,-0.06453052077471888,-6.213755336772485,36.11111111111111,0.5978851836487422,-0.054737723826918466,8.0,-7.072190285999975,15928.524672704001,890.1023769904265,0.0049811895623553025,0.4607661125829915,0,"{'price_departed_over_005pct': 31, 'position_already_open': 5}","{'TIME': 33, 'END': 2, 'SL': 1}"
118,37,0.8351031088782292,0.027836770295940977,21.270174407964078,3.913361132308637,-3.0782580234304078,8.28692551136014,7.433393095571682,-0.018429306910038454,8.26849620444991,59.45945945945946,1.0269017705641819,0.004906831914382099,8.0,-7.371708825600028,14866.786191143365,-56.172403244470395,0.004975439064191662,0.19847052241177152,0,"{'price_departed_over_005pct': 26, 'position_already_open': 9}","{'TIME': 34, 'SL': 2, 'TP': 1}"
59,37,-30.722363679140017,-1.0240787893046672,39.46622652445194,-25.615244715534118,-5.107118963605899,-23.3087095859996,7.435250998461002,0.021596905319708377,-23.287112680679016,32.432432432432435,0.3890627802994325,-0.11313233234775008,8.0,-7.336271881699988,14870.501996922003,2065.9937159820925,0.0049604890489387,0.1400241815079682,0,"{'price_departed_over_005pct': 27, 'position_already_open': 8}","{'TIME': 33, 'SL': 4}"
144,28,-11.41837224051551,-0.38061240801718366,21.866044255745237,-6.280047567240672,-5.1383246732748376,-5.463147045999842,6.006692921047,0.05146772653173288,-5.41167931946851,53.57142857142857,0.6596364500096066,-0.054756626217497925,8.0,-7.403969076174007,12013.385842094,950.4707823922871,0.00497807683615466,0.14371150944270664,0,"{'price_departed_over_005pct': 38, 'position_already_open': 6}","{'TIME': 26, 'SL': 1, 'END': 1}"
34,32,-22.58621877119731,-0.7528739590399103,35.83756435947589,-6.109561708821275,-16.476657062376034,-15.503889721999629,7.0404505737709995,-0.04187847542409773,-15.545768197426309,34.375,0.5152547233334731,-0.09465441127979199,8.0,-7.337801337477569,14080.901147542,1604.0321947107784,0.004972606171485187,0.23310436752953873,0,"{'position_already_open': 9, 'price_departed_over_005pct': 31}","{'TIME': 30, 'SL': 2}"
```

</details>


<details>
<summary>qa_trend/qa_execution.py</summary>

SHA256 UTF-8/LF: `835c24305950302c72c7917dd6f4d1606b94942159d2ea98bc3e83a78c30aed5`

```python
"""Independent small causal/cash probes; never changes the experiment source."""
from pathlib import Path
import hashlib
import importlib.util
import json

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "bounded_breakout.py"
spec = importlib.util.spec_from_file_location("qa_bounded", SOURCE)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
out = {"source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest()}


def arrays(n=5):
    ms = np.arange(b.START.value // 10**6, b.START.value // 10**6 + 60000*n, 60000)
    assets = []
    for symbol, price in zip(b.SYMBOLS, [100., 1.]):
        assets.append({"symbol": symbol, "o": np.full(n, price), "h": np.full(n, price),
                       "l": np.full(n, price), "c": np.full(n, price), "entries": {}, "funding": {}})
    return ms, assets


def event(a, i, side=1):
    price = a["o"][i]
    a["entries"][i] = {"ref": price, "high": price, "low": price,
                       "atr": price/300, "adx": 25., "side": side}


# New fill sees its first minute and a double touch must pick the stop, not profit.
ms, a = arrays()
event(a[0], 1)
a[0]["h"][1], a[0]["l"][1] = 103., 98.
s, t, eq = b.simulate(ms, a)
assert len(t) == 1 and t.iloc[0].reason == "SL_BOTH" and t.iloc[0].net < 0
assert t.iloc[0].entry_ms == ms[1] and t.iloc[0].exit_ms == ms[1]+60000
out["first_minute_double_touch"] = {"reason": t.iloc[0].reason, "net": float(t.iloc[0].net)}

# Funding at entry-minute is not paid; old inventory pays funding before gap exit.
ms, a = arrays()
event(a[0], 1)
a[0]["funding"] = {1: (.001, 100.), 3: (.001, 100.)}
a[0]["o"][3], a[0]["h"][3], a[0]["l"][3], a[0]["c"][3] = 95., 96., 94., 95.
s, t, eq = b.simulate(ms, a)
p = t.iloc[0]
assert p.reason == "SL_GAP" and abs(p.funding + p.qty*100*.001) < 1e-10
assert abs(p.exit - 95*(1-.0002)) < 1e-10
out["settlement_before_gap_exit"] = {"funding": float(p.funding), "exit": float(p.exit),
                                      "reason": p.reason, "R": float(p.R)}

# An intraminute profit later at this minute cannot make the current open flat.
ms, a = arrays()
event(a[0], 1)
event(a[0], 3, side=-1)
a[0]["h"][3] = 104.
s, t, eq = b.simulate(ms, a)
assert len(t) == 1 and s["skip_counts"]["position_already_open"] == 1 and t.iloc[0].reason == "TP"
out["no_intrabar_lookahead_entry"] = s["skip_counts"]

# Short double touch is also stop-first with adverse buy slippage.
ms, a = arrays()
event(a[0], 1, side=-1)
a[0]["h"][1], a[0]["l"][1] = 102., 97.
s, t, eq = b.simulate(ms, a)
assert t.iloc[0].reason == "SL_BOTH" and abs(t.iloc[0].exit-101*1.0002) < 1e-10
out["short_double_touch"] = {"reason": t.iloc[0].reason, "exit": float(t.iloc[0].exit)}

# The deadline is exactly 480 minutes after entry, priced at that minute's open.
ms, a = arrays(482)
event(a[0], 1)
a[0]["o"][481], a[0]["h"][481], a[0]["l"][481], a[0]["c"][481] = 100.5, 100.5, 100.5, 100.5
s, t, eq = b.simulate(ms, a)
assert t.iloc[0].reason == "TIME" and t.iloc[0].hold_h == 8
assert abs(t.iloc[0].exit - 100.5*(1-.0002)) < 1e-10
out["deadline"] = {"reason": t.iloc[0].reason, "hold_h": float(t.iloc[0].hold_h), "exit": float(t.iloc[0].exit)}

# Final liquidation includes adverse exit and fees, so no terminal bag is omitted.
ms, a = arrays()
event(a[0], 1)
s, t, eq = b.simulate(ms, a)
assert t.iloc[0].reason == "END" and eq[-1] == b.INITIAL + t.net.sum()
assert t.iloc[0].exit == 100*(1-.0002)
assert t.iloc[0].fees > 0 and t.iloc[0].net < 0
out["terminal_cash"] = {"reason": t.iloc[0].reason, "net": float(t.iloc[0].net), "last_equity": float(eq[-1])}

# Concurrent entries use combined cash/equity, and quantity is rounded down.
ms, a = arrays()
event(a[0], 1)
event(a[1], 1)
s, t, eq = b.simulate(ms, a)
assert len(t) == 2 and s["maximum_gross_frac"] <= 1 and s["maximum_reserved_risk_frac"] <= .01
for p in t.itertuples():
    step = b.STEPS[b.SYMBOLS.index(p.symbol)]
    assert abs(p.qty/step-round(p.qty/step)) < 1e-8
out["combined_and_rounding"] = {"max_entry_gross_frac": s["maximum_gross_frac"],
                                "max_entry_reserved_risk_frac": s["maximum_reserved_risk_frac"],
                                "qty": t[["symbol", "qty"]].to_dict("records")}

# Known robustness defect: a zero-trade window/control currently throws rather
# than reporting N=0, net=0, undefined PF/CI. It doesn't alter nonempty results.
ms, a = arrays()
try:
    b.simulate(ms, a)
except (AttributeError, ZeroDivisionError) as exc:
    out["empty_trades_guard"] = {"error": type(exc).__name__, "message": str(exc)}
else:
    out["empty_trades_guard"] = {"fixed": True}

(HERE/"qa_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps(out, indent=2))
```

</details>


<details>
<summary>qa_trend/qa_results.json</summary>

SHA256 UTF-8/LF: `6669e3cf3576006575ec5401ede1d0b2289f5d26dc8876b71353c3c645eb6303`

```json
{
  "source_sha256": "ff439361ad67d45a98f1d864826bd7dafdc479903938b6baecafd1d81603918c",
  "first_minute_double_touch": {
    "reason": "SL_BOTH",
    "net": -7.184426430599998
  },
  "settlement_before_gap_exit": {
    "funding": -0.6306,
    "exit": 94.98100000000001,
    "reason": "SL_GAP",
    "R": -4.402973202699607
  },
  "no_intrabar_lookahead_entry": {
    "position_already_open": 1
  },
  "short_double_touch": {
    "reason": "SL_BOTH",
    "exit": 101.0202
  },
  "deadline": {
    "reason": "TIME",
    "hold_h": 8.0,
    "exit": 100.4799
  },
  "terminal_cash": {
    "reason": "END",
    "net": -0.8828399999999498,
    "last_equity": 2999.1171600000002
  },
  "combined_and_rounding": {
    "max_entry_gross_frac": 0.42036570521973204,
    "max_entry_reserved_risk_frac": 0.004998952131833336,
    "qty": [
      {
        "symbol": "ETHUSDT",
        "qty": 6.306
      },
      {
        "symbol": "XRPUSDT",
        "qty": 630.0
      }
    ]
  },
  "empty_trades_guard": {
    "fixed": true
  }
}
```

</details>


<details>
<summary>input_manifest.json</summary>

SHA256 UTF-8/LF: `d4c91c748adabdf3034788450dc7d6f666aed485d245bbb5ad87ecfc4da87b09`

```json
[
  {
    "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_1h.csv",
    "sha256": "2def2f3139787b03bc628d006b25f8325834a6d2a4b51ad0ffa006af4bb035b8"
  },
  {
    "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_1m.csv",
    "sha256": "352556b14ffcc1e3d6811e96c823c57c8ee9633002385701d78226cfd9f5f3c8"
  },
  {
    "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_funding.csv",
    "sha256": "46bb8603c2988336deb0ed7eb75477a2cc0981b848b3816aa21e44920bdd449a"
  },
  {
    "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_1h.csv",
    "sha256": "febec2c5f2e0d1cab42e08629beb57aeed94d1de3d011b84b7ebec53234d319d"
  },
  {
    "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_1m.csv",
    "sha256": "d6e61c811e0d7e2f8b98e66fd67928ad2d574790a051cb52cdbb8783050c42f6"
  },
  {
    "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_funding.csv",
    "sha256": "148a92ce5743d8fc59ec40703fbce7ecfcde356e041690fcdee663a32781d4bf"
  }
]
```

</details>


<details>
<summary>data_provenance.json</summary>

SHA256 UTF-8/LF: `ad07fe5314033b14aa2ab1bce7d97f6536dd144b6a1701edf38fc9b3d278bac2`

```json
{
  "source_files": [
    {
      "path": "research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_1h.csv",
      "rows": 24216,
      "start_open_time": "2024-01-01 00:00:00+00:00",
      "end_open_time": "2026-10-05 23:00:00+00:00",
      "end_exclusive": "2026-10-06 00:00:00+00:00",
      "timestamp_step_ms": 3600000,
      "duplicates": 0,
      "unsorted_or_nonincreasing": 0,
      "gaps_missing_bars": 0,
      "off_grid_timestamps": 0,
      "nonfinite_ohlcv_rows": 0,
      "invalid_ohlc_rows": 0,
      "nonpositive_prices_rows": 0,
      "negative_volume_rows": 0,
      "sha256": "2def2f3139787b03bc628d006b25f8325834a6d2a4b51ad0ffa006af4bb035b8",
      "manifest_sha256_match": true,
      "incorrect_close_ts_rows": 0
    },
    {
      "path": "research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_1m.csv",
      "rows": 218880,
      "start_open_time": "2026-05-07 00:00:00+00:00",
      "end_open_time": "2026-10-05 23:59:00+00:00",
      "end_exclusive": "2026-10-06 00:00:00+00:00",
      "timestamp_step_ms": 60000,
      "duplicates": 0,
      "unsorted_or_nonincreasing": 0,
      "gaps_missing_bars": 0,
      "off_grid_timestamps": 0,
      "nonfinite_ohlcv_rows": 0,
      "invalid_ohlc_rows": 0,
      "nonpositive_prices_rows": 0,
      "negative_volume_rows": 0,
      "sha256": "352556b14ffcc1e3d6811e96c823c57c8ee9633002385701d78226cfd9f5f3c8",
      "manifest_sha256_match": true,
      "incorrect_close_ts_rows": 0
    },
    {
      "path": "research\\manual15_20261006\\data\\futures_ETHUSDT_15m.csv",
      "rows": 96864,
      "start_open_time": "2024-01-01 00:00:00+00:00",
      "end_open_time": "2026-10-05 23:45:00+00:00",
      "end_exclusive": "2026-10-06 00:00:00+00:00",
      "timestamp_step_ms": 900000,
      "duplicates": 0,
      "unsorted_or_nonincreasing": 0,
      "gaps_missing_bars": 0,
      "off_grid_timestamps": 0,
      "nonfinite_ohlcv_rows": 0,
      "invalid_ohlc_rows": 0,
      "nonpositive_prices_rows": 0,
      "negative_volume_rows": 0,
      "sha256": "0291f7ad7c3f3d6040098490a5f997f8b8a7cde1e48b0af658459d7a4b0910cd",
      "manifest_sha256_match": true,
      "incorrect_close_ts_rows": 0
    },
    {
      "path": "research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_1h.csv",
      "rows": 24216,
      "start_open_time": "2024-01-01 00:00:00+00:00",
      "end_open_time": "2026-10-05 23:00:00+00:00",
      "end_exclusive": "2026-10-06 00:00:00+00:00",
      "timestamp_step_ms": 3600000,
      "duplicates": 0,
      "unsorted_or_nonincreasing": 0,
      "gaps_missing_bars": 0,
      "off_grid_timestamps": 0,
      "nonfinite_ohlcv_rows": 0,
      "invalid_ohlc_rows": 0,
      "nonpositive_prices_rows": 0,
      "negative_volume_rows": 0,
      "sha256": "febec2c5f2e0d1cab42e08629beb57aeed94d1de3d011b84b7ebec53234d319d",
      "manifest_sha256_match": true,
      "incorrect_close_ts_rows": 0
    },
    {
      "path": "research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_1m.csv",
      "rows": 218880,
      "start_open_time": "2026-05-07 00:00:00+00:00",
      "end_open_time": "2026-10-05 23:59:00+00:00",
      "end_exclusive": "2026-10-06 00:00:00+00:00",
      "timestamp_step_ms": 60000,
      "duplicates": 0,
      "unsorted_or_nonincreasing": 0,
      "gaps_missing_bars": 0,
      "off_grid_timestamps": 0,
      "nonfinite_ohlcv_rows": 0,
      "invalid_ohlc_rows": 0,
      "nonpositive_prices_rows": 0,
      "negative_volume_rows": 0,
      "sha256": "d6e61c811e0d7e2f8b98e66fd67928ad2d574790a051cb52cdbb8783050c42f6",
      "manifest_sha256_match": true,
      "incorrect_close_ts_rows": 0
    },
    {
      "path": "research\\manual15_20261006\\data\\futures_XRPUSDT_15m.csv",
      "rows": 96864,
      "start_open_time": "2024-01-01 00:00:00+00:00",
      "end_open_time": "2026-10-05 23:45:00+00:00",
      "end_exclusive": "2026-10-06 00:00:00+00:00",
      "timestamp_step_ms": 900000,
      "duplicates": 0,
      "unsorted_or_nonincreasing": 0,
      "gaps_missing_bars": 0,
      "off_grid_timestamps": 0,
      "nonfinite_ohlcv_rows": 0,
      "invalid_ohlc_rows": 0,
      "nonpositive_prices_rows": 0,
      "negative_volume_rows": 0,
      "sha256": "2c258931beff9f123cc30fa19a1da4787e90e1dbee781eda2888dd707d23ab14",
      "manifest_sha256_match": true,
      "incorrect_close_ts_rows": 0
    }
  ],
  "aggregation_checks": [
    {
      "symbol": "ETHUSDT",
      "source_interval": "1m",
      "target_interval": "1h",
      "common_hours": 3648,
      "start": "2026-05-07 00:00:00+00:00",
      "end_open": "2026-10-05 23:00:00+00:00",
      "incomplete_hour_groups": 0,
      "mismatching_hour_counts": {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 0,
        "volume": 0
      },
      "max_abs_difference": {
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "volume": 2.3283064365386963e-10
      },
      "mismatch_details": []
    },
    {
      "symbol": "ETHUSDT",
      "source_interval": "15m",
      "target_interval": "1h",
      "common_hours": 24216,
      "start": "2024-01-01 00:00:00+00:00",
      "end_open": "2026-10-05 23:00:00+00:00",
      "incomplete_hour_groups": 0,
      "mismatching_hour_counts": {
        "open": 0,
        "high": 1,
        "low": 0,
        "close": 2,
        "volume": 2
      },
      "max_abs_difference": {
        "open": 0.0,
        "high": 30.0,
        "low": 0.0,
        "close": 24.779999999999745,
        "volume": 142412.27099999998
      },
      "mismatch_details": [
        {
          "hour_open": "2024-10-28 20:00:00+00:00",
          "source_aggregated": {
            "open": 2505.93,
            "high": 2516.49,
            "low": 2504.13,
            "close": 2515.97,
            "volume": 55135.34
          },
          "direct_1h": {
            "open": 2505.93,
            "high": 2516.49,
            "low": 2504.13,
            "close": 2516.41,
            "volume": 47283.244
          }
        },
        {
          "hour_open": "2024-10-28 21:00:00+00:00",
          "source_aggregated": {
            "open": 2515.96,
            "high": 2550.0,
            "low": 2514.54,
            "close": 2543.7,
            "volume": 158698.31399999998
          },
          "direct_1h": {
            "open": 2515.96,
            "high": 2520.0,
            "low": 2514.54,
            "close": 2518.92,
            "volume": 16286.043
          }
        }
      ]
    },
    {
      "symbol": "ETHUSDT",
      "source_interval": "1m",
      "target_interval": "15m",
      "common_bars": 14592,
      "start": "2026-05-07 00:00:00+00:00",
      "end_open": "2026-10-05 23:45:00+00:00",
      "incomplete_groups": 0,
      "mismatching_bar_counts": {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 0,
        "volume": 0
      }
    },
    {
      "symbol": "XRPUSDT",
      "source_interval": "1m",
      "target_interval": "1h",
      "common_hours": 3648,
      "start": "2026-05-07 00:00:00+00:00",
      "end_open": "2026-10-05 23:00:00+00:00",
      "incomplete_hour_groups": 0,
      "mismatching_hour_counts": {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 0,
        "volume": 0
      },
      "max_abs_difference": {
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "volume": 2.9802322387695312e-08
      },
      "mismatch_details": []
    },
    {
      "symbol": "XRPUSDT",
      "source_interval": "15m",
      "target_interval": "1h",
      "common_hours": 24216,
      "start": "2024-01-01 00:00:00+00:00",
      "end_open": "2026-10-05 23:00:00+00:00",
      "incomplete_hour_groups": 0,
      "mismatching_hour_counts": {
        "open": 0,
        "high": 1,
        "low": 1,
        "close": 2,
        "volume": 2
      },
      "max_abs_difference": {
        "open": 0.0,
        "high": 0.0004999999999999449,
        "low": 0.0010000000000000009,
        "close": 0.0019000000000000128,
        "volume": 9007138.799999999
      },
      "mismatch_details": [
        {
          "hour_open": "2024-10-28 20:00:00+00:00",
          "source_aggregated": {
            "open": 0.5174,
            "high": 0.5192,
            "low": 0.517,
            "close": 0.5182,
            "volume": 11735968.3
          },
          "direct_1h": {
            "open": 0.5174,
            "high": 0.5192,
            "low": 0.517,
            "close": 0.5185,
            "volume": 9686296.5
          }
        },
        {
          "hour_open": "2024-10-28 21:00:00+00:00",
          "source_aggregated": {
            "open": 0.5182,
            "high": 0.5192,
            "low": 0.516,
            "close": 0.5191,
            "volume": 12131479.7
          },
          "direct_1h": {
            "open": 0.5182,
            "high": 0.5187,
            "low": 0.517,
            "close": 0.5172,
            "volume": 3124340.9
          }
        }
      ]
    },
    {
      "symbol": "XRPUSDT",
      "source_interval": "1m",
      "target_interval": "15m",
      "common_bars": 14592,
      "start": "2026-05-07 00:00:00+00:00",
      "end_open": "2026-10-05 23:45:00+00:00",
      "incomplete_groups": 0,
      "mismatching_bar_counts": {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 0,
        "volume": 0
      }
    }
  ],
  "funding_checks": [
    {
      "path": "research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_funding.csv",
      "rows": 3027,
      "start": "2024-01-01 00:00:00+00:00",
      "end": "2026-10-05 16:00:00+00:00",
      "sha256": "46bb8603c2988336deb0ed7eb75477a2cc0981b848b3816aa21e44920bdd449a",
      "manifest_sha256_match": true,
      "duplicate_actual_timestamps": 0,
      "duplicate_canonical_events": 0,
      "max_abs_ms_offset_from_canonical8h": 26,
      "missing_canonical8h_events_full": 0,
      "nonfinite_rate_or_mark_rows": 0,
      "nonpositive_mark_rows": 0,
      "minute_window": {
        "start": "2026-05-07 00:00:00+00:00",
        "end_exclusive": "2026-10-06 00:00:00+00:00",
        "funding_rows": 456,
        "expected8h_events": 456,
        "missing_events": 0
      }
    },
    {
      "path": "research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_funding.csv",
      "rows": 3027,
      "start": "2024-01-01 00:00:00+00:00",
      "end": "2026-10-05 16:00:00+00:00",
      "sha256": "148a92ce5743d8fc59ec40703fbce7ecfcde356e041690fcdee663a32781d4bf",
      "manifest_sha256_match": true,
      "duplicate_actual_timestamps": 0,
      "duplicate_canonical_events": 0,
      "max_abs_ms_offset_from_canonical8h": 26,
      "missing_canonical8h_events_full": 0,
      "nonfinite_rate_or_mark_rows": 0,
      "nonpositive_mark_rows": 0,
      "minute_window": {
        "start": "2026-05-07 00:00:00+00:00",
        "end_exclusive": "2026-10-06 00:00:00+00:00",
        "funding_rows": 456,
        "expected8h_events": 456,
        "missing_events": 0
      }
    }
  ],
  "declared_provenance": "Local manifests and fetch scripts say Binance USD-M public REST; not fetched anew",
  "holdout_status": "Previously inspected historical data; not globally untouched/OOS for the new hypothesis",
  "funding_convention_notes": [
    "Use actual fundingRate and markPrice per event; positive rate is debit for LONG, credit for SHORT",
    "State exact same-time entry/exit convention; changing it can change an8h strategy result",
    "Rates/markPrice are Binance, not actual WEEX funding; report transfer limitation",
    "Execution-minute files end exclusive2026-10-06T00:00Z; do not invent funding/event prices after that"
  ]
}
```

</details>


<details>
<summary>funding_screen.py</summary>

SHA256 UTF-8/LF: `324b460a222f7b53a8d4fa1dc02a670bdc0571c6dce1ba499fd2014d8c5957e2`

```python
"""Public WEEX/Bybit funding screen. GET-only; no accounts, trades or secrets."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
WEEX = 'https://api-contract.weex.com'
BYBIT = 'https://api.bybit.com'
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'DOGEUSDT', 'AAVEUSDT']


def get(base, path, args=None):
    url = base+path+('?' + urlencode(args) if args else '')
    try:
        with urlopen(Request(url, headers={'User-Agent':'Public-funding-research/1.0'}), timeout=12) as r:
            return json.load(r)
    except HTTPError as e:
        raise ValueError(f'Public GET {url}: HTTP{e.code}; {e.read().decode(errors="replace")[:300]}') from None


def first(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def bybit_list(data):
    if data.get('retCode') != 0:
        raise ValueError(f'Bybit public API {data.get("retCode")}: {data.get("retMsg")}')
    return data['result']['list']


def weex_history(symbol, start, end):
    # Actual public endpoint rejects intervals >7 days; retain every page.
    found = {}
    a = start
    while a <= end:
        b = min(a+7*86400000-1, end)
        chunk = get(WEEX, '/capi/v3/market/fundingRate',
                    {'symbol':symbol, 'startTime':a, 'endTime':b, 'limit':1000})
        if not isinstance(chunk, list) or len(chunk)>=1000:
            raise ValueError('Incomplete/unexpected WEEX funding page')
        for r in chunk:
            stamp = int(r['fundingTime'])
            if a <= stamp <= b:
                if stamp in found and found[stamp] != r:
                    raise ValueError('Conflicting duplicate funding event')
                found[stamp] = r
        a = b+1
    return [found[t] for t in sorted(found)]


def one(symbol, end):
    start = end-30*86400000
    raw = {}
    jobs = {
        'weex_current':(WEEX, '/capi/v3/market/premiumIndex', {'symbol':symbol}),
        'weex_book':(WEEX, '/capi/v3/market/ticker/bookTicker', {'symbol':symbol}),
        'bybit_current':(BYBIT, '/v5/market/tickers', {'category':'linear','symbol':symbol}),
        'bybit_instrument':(BYBIT, '/v5/market/instruments-info', {'category':'linear','symbol':symbol}),
        'bybit_history':(BYBIT, '/v5/market/funding/history', {'category':'linear','symbol':symbol,'startTime':start,'endTime':end,'limit':200}),
    }
    for key, (base, path, args) in jobs.items():
        raw[key] = get(base, path, args)
    raw['weex_history'] = weex_history(symbol, start, end)
    (HERE/'funding_raw').mkdir(exist_ok=True)
    (HERE/'funding_raw'/f'{symbol}.json').write_text(json.dumps(raw, indent=2), encoding='utf-8')
    w, wb = first(raw['weex_current']), first(raw['weex_book'])
    b, bi = first(bybit_list(raw['bybit_current'])), first(bybit_list(raw['bybit_instrument']))
    wh = raw['weex_history']
    bh = bybit_list(raw['bybit_history'])
    if not isinstance(wh, list) or not wh or not bh:
        raise ValueError('Funding history missing or unexpected response')
    wh = [r for r in wh if start <= int(r['fundingTime']) <= end]
    bh = [r for r in bh if start <= int(r['fundingRateTimestamp']) <= end]
    if not wh or not bh or len(wh)>=1000 or len(bh)>=200:
        raise ValueError('Empty history or unpaginated full page; refuse sum')
    wr = sum(float(r['fundingRate']) for r in wh)
    br = sum(float(r['fundingRate']) for r in bh)
    difference = wr-br
    wm = (float(wb['bidPrice'])+float(wb['askPrice']))/2
    bm = (float(b['bid1Price'])+float(b['ask1Price']))/2
    spread_cost = (float(wb['askPrice'])-float(wb['bidPrice']))/wm + (float(b['ask1Price'])-float(b['bid1Price']))/bm
    # Four taker executions: measured WEEX .048%, illustrative Bybit non-VIP .055%.
    fees = 2*(.00048+.00055)
    # Adverse execution buffer .02% on each of four executions, in addition to observed spread.
    costs = fees + .0008 + spread_cost
    periods = {}
    for venue, rows, field in [('WEEX',wh,'fundingTime'), ('Bybit',bh,'fundingRateTimestamp')]:
        ts = sorted(int(r[field]) for r in rows)
        periods[venue] = {'N':len(ts),'first_ms':ts[0],'last_ms':ts[-1],
                          'maximum_gap_hours':max((y-x)/3600000 for x,y in zip(ts,ts[1:])) if len(ts)>1 else None}
    return {'symbol':symbol, 'history_window_UTC':[datetime.fromtimestamp(start/1000,timezone.utc).isoformat(), datetime.fromtimestamp(end/1000,timezone.utc).isoformat()],
            'weex_30d_sum_rate_pct':wr*100,'bybit_30d_sum_rate_pct':br*100,
            'signed_difference_30d_pct':difference*100,
            'in_hindsight_best_side':'SHORT_WEEX_LONG_BYBIT' if difference>0 else 'LONG_WEEX_SHORT_BYBIT',
            'absolute_difference_30d_pct':abs(difference)*100,
            'four_leg_round_cost_pct_estimate':costs*100,
            'hypothetical_30d_difference_less_round_cost_USD_per_1000':1000*(abs(difference)-costs),
            'historical_days_to_cover_round_cost_if_rate_persisted':costs/(abs(difference)/30) if difference else None,
            'observed_basis_mid_pct':(wm/bm-1)*100,
            'weex_interval_minutes':w.get('collectCycle'), 'bybit_interval_minutes':bi.get('fundingInterval'),
            'weex_forecast_rate':w.get('forecastFundingRate'), 'bybit_current_rate':b.get('fundingRate'),
            'history_coverage':periods,
            'warning':'Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included.'}


def main():
    started = time.time()
    errors, rows = {}, []
    try:
        server = get(WEEX, '/capi/v3/market/time')
        end = int(server['serverTime'])
    except Exception as e:
        end = int(time.time()*1000)
        errors['server_time'] = str(e)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(one, s, end):s for s in SYMBOLS}
        for f in as_completed(futures):
            s = futures[f]
            try:
                rows.append(f.result())
                print(json.dumps({'symbol':s,'status':'read'}, ensure_ascii=True), flush=True)
            except Exception as e:
                errors[s] = str(e)
                print(json.dumps({'symbol':s,'status':'error','error':str(e)}, ensure_ascii=True), flush=True)
    out = {'read_only':True,'queried_at_UTC':datetime.fromtimestamp(end/1000,timezone.utc).isoformat(),
           'seconds':round(time.time()-started,1),'rows':sorted(rows,key=lambda r:-r['absolute_difference_30d_pct']), 'errors':errors}
    (HERE/'funding_screen.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out, ensure_ascii=True),flush=True)


if __name__ == '__main__':
    main()
```

</details>


<details>
<summary>funding_screen.json</summary>

SHA256 UTF-8/LF: `d5396c17648c1e3cf5b77ff2f37c1f40218e494f7d2aea6a7279a64f00da7021`

```json
{
  "read_only": true,
  "queried_at_UTC": "2026-10-11T12:25:37.122000+00:00",
  "seconds": 7.8,
  "rows": [
    {
      "symbol": "DOGEUSDT",
      "history_window_UTC": [
        "2026-09-11T12:25:37.122000+00:00",
        "2026-10-11T12:25:37.122000+00:00"
      ],
      "weex_30d_sum_rate_pct": 0.534069,
      "bybit_30d_sum_rate_pct": 0.35280900000000004,
      "signed_difference_30d_pct": 0.18126,
      "in_hindsight_best_side": "SHORT_WEEX_LONG_BYBIT",
      "absolute_difference_30d_pct": 0.18126,
      "four_leg_round_cost_pct_estimate": 0.3094604106378944,
      "hypothetical_30d_difference_less_round_cost_USD_per_1000": -1.282004106378944,
      "historical_days_to_cover_round_cost_if_rate_persisted": 51.21820765274651,
      "observed_basis_mid_pct": -0.011729517330361094,
      "weex_interval_minutes": 480,
      "bybit_interval_minutes": 480,
      "weex_forecast_rate": "-0.00000679",
      "bybit_current_rate": "0.00000565",
      "history_coverage": {
        "WEEX": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        },
        "Bybit": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        }
      },
      "warning": "Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included."
    },
    {
      "symbol": "AAVEUSDT",
      "history_window_UTC": [
        "2026-09-11T12:25:37.122000+00:00",
        "2026-10-11T12:25:37.122000+00:00"
      ],
      "weex_30d_sum_rate_pct": 0.48629500000000003,
      "bybit_30d_sum_rate_pct": 0.357437,
      "signed_difference_30d_pct": 0.12885800000000006,
      "in_hindsight_best_side": "SHORT_WEEX_LONG_BYBIT",
      "absolute_difference_30d_pct": 0.12885800000000006,
      "four_leg_round_cost_pct_estimate": 0.29799364341215195,
      "hypothetical_30d_difference_less_round_cost_USD_per_1000": -1.6913564341215188,
      "historical_days_to_cover_round_cost_if_rate_persisted": 69.37721602356513,
      "observed_basis_mid_pct": 0.011994362649536683,
      "weex_interval_minutes": 480,
      "bybit_interval_minutes": 480,
      "weex_forecast_rate": "0.00004990",
      "bybit_current_rate": "0.00005045",
      "history_coverage": {
        "WEEX": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        },
        "Bybit": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        }
      },
      "warning": "Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included."
    },
    {
      "symbol": "SOLUSDT",
      "history_window_UTC": [
        "2026-09-11T12:25:37.122000+00:00",
        "2026-10-11T12:25:37.122000+00:00"
      ],
      "weex_30d_sum_rate_pct": 0.306186,
      "bybit_30d_sum_rate_pct": 0.22516000000000003,
      "signed_difference_30d_pct": 0.08102599999999997,
      "in_hindsight_best_side": "SHORT_WEEX_LONG_BYBIT",
      "absolute_difference_30d_pct": 0.08102599999999997,
      "four_leg_round_cost_pct_estimate": 0.3042581705693501,
      "hypothetical_30d_difference_less_round_cost_USD_per_1000": -2.2323217056935016,
      "historical_days_to_cover_round_cost_if_rate_persisted": 112.65205140424688,
      "observed_basis_mid_pct": -0.009128668583691102,
      "weex_interval_minutes": 480,
      "bybit_interval_minutes": 480,
      "weex_forecast_rate": "0.00004961",
      "bybit_current_rate": "-0.00000898",
      "history_coverage": {
        "WEEX": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        },
        "Bybit": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        }
      },
      "warning": "Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included."
    },
    {
      "symbol": "XRPUSDT",
      "history_window_UTC": [
        "2026-09-11T12:25:37.122000+00:00",
        "2026-10-11T12:25:37.122000+00:00"
      ],
      "weex_30d_sum_rate_pct": 0.330098,
      "bybit_30d_sum_rate_pct": 0.377515,
      "signed_difference_30d_pct": -0.04741699999999999,
      "in_hindsight_best_side": "LONG_WEEX_SHORT_BYBIT",
      "absolute_difference_30d_pct": 0.04741699999999999,
      "four_leg_round_cost_pct_estimate": 0.300352350215821,
      "hypothetical_30d_difference_less_round_cost_USD_per_1000": -2.52935350215821,
      "historical_days_to_cover_round_cost_if_rate_persisted": 190.02827058807247,
      "observed_basis_mid_pct": 0.007176432595334958,
      "weex_interval_minutes": 480,
      "bybit_interval_minutes": 480,
      "weex_forecast_rate": "0.00006238",
      "bybit_current_rate": "0.00002805",
      "history_coverage": {
        "WEEX": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        },
        "Bybit": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        }
      },
      "warning": "Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included."
    },
    {
      "symbol": "ETHUSDT",
      "history_window_UTC": [
        "2026-09-11T12:25:37.122000+00:00",
        "2026-10-11T12:25:37.122000+00:00"
      ],
      "weex_30d_sum_rate_pct": 0.333226,
      "bybit_30d_sum_rate_pct": 0.29805,
      "signed_difference_30d_pct": 0.035176,
      "in_hindsight_best_side": "SHORT_WEEX_LONG_BYBIT",
      "absolute_difference_30d_pct": 0.035176,
      "four_leg_round_cost_pct_estimate": 0.28679857374726847,
      "hypothetical_30d_difference_less_round_cost_USD_per_1000": -2.516225737472685,
      "historical_days_to_cover_round_cost_if_rate_persisted": 244.5973735620325,
      "observed_basis_mid_pct": 0.0,
      "weex_interval_minutes": 480,
      "bybit_interval_minutes": 480,
      "weex_forecast_rate": "-0.00002113",
      "bybit_current_rate": "0.0000208",
      "history_coverage": {
        "WEEX": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        },
        "Bybit": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        }
      },
      "warning": "Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included."
    },
    {
      "symbol": "BTCUSDT",
      "history_window_UTC": [
        "2026-09-11T12:25:37.122000+00:00",
        "2026-10-11T12:25:37.122000+00:00"
      ],
      "weex_30d_sum_rate_pct": 0.347235,
      "bybit_30d_sum_rate_pct": 0.333121,
      "signed_difference_30d_pct": 0.014113999999999967,
      "in_hindsight_best_side": "SHORT_WEEX_LONG_BYBIT",
      "absolute_difference_30d_pct": 0.014113999999999967,
      "four_leg_round_cost_pct_estimate": 0.2862407279148356,
      "hypothetical_30d_difference_less_round_cost_USD_per_1000": -2.7212672791483565,
      "historical_days_to_cover_round_cost_if_rate_persisted": 608.4187216554548,
      "observed_basis_mid_pct": 0.01709314258027117,
      "weex_interval_minutes": 480,
      "bybit_interval_minutes": 480,
      "weex_forecast_rate": "-0.00000079",
      "bybit_current_rate": "0.00003882",
      "history_coverage": {
        "WEEX": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        },
        "Bybit": {
          "N": 90,
          "first_ms": 1789142400000,
          "last_ms": 1791705600000,
          "maximum_gap_hours": 8.0
        }
      },
      "warning": "Screen, not portfolio PnL: best direction selected in hindsight; assumes constant leg notional, omits changing marks/quantities, basis PnL, margin, queue and transfer risk. No future rate guarantee or WEEX rebate included."
    }
  ],
  "errors": {}
}
```

</details>


<details>
<summary>funding_raw/AAVEUSDT.json</summary>

SHA256 UTF-8/LF: `4f79339f4da15195c59e0517c69050f24fdd44fc82293b4ad9bdb44f22ced9f0`

```json
{
  "weex_current": [
    {
      "symbol": "AAVEUSDT",
      "markPrice": "166.83",
      "indexPrice": "166.9415",
      "forecastFundingRate": "0.00004990",
      "lastFundingRate": "0.00007384",
      "interestRate": "0.0003",
      "nextFundingTime": 1791734400000,
      "time": 1791721541383,
      "collectCycle": 480
    }
  ],
  "weex_book": [
    {
      "symbol": "AAVEUSDT",
      "bidPrice": "166.76",
      "bidQty": "39.5",
      "askPrice": "166.77",
      "askQty": "3.8",
      "time": 1791721541268
    }
  ],
  "bybit_current": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "AAVEUSDT",
          "lastPrice": "166.75",
          "indexPrice": "166.89",
          "markPrice": "166.75",
          "prevPrice24h": "172.33",
          "price24hPcnt": "-0.032379",
          "highPrice24h": "173.85",
          "lowPrice24h": "166.48",
          "prevPrice1h": "166.78",
          "openInterest": "354812.19",
          "openInterestValue": "59164932.68",
          "singleOpenInterest": "177406.1",
          "singleOpenInterestValue": "29582467.18",
          "turnover24h": "14852425.8941",
          "volume24h": "87618.5600",
          "fundingRate": "0.00005045",
          "nextFundingTime": "1791734400000",
          "predictedDeliveryPrice": "",
          "basisRate": "",
          "deliveryFeeRate": "",
          "deliveryTime": "0",
          "ask1Size": "9.01",
          "bid1Price": "166.74",
          "ask1Price": "166.75",
          "bid1Size": "0.09",
          "basis": "",
          "preOpenPrice": "",
          "preQty": "",
          "curPreListingPhase": "",
          "fundingIntervalHour": "8",
          "basisRateYear": "",
          "fundingCap": "0.0058"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721541920
  },
  "bybit_instrument": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "AAVEUSDT",
          "contractType": "LinearPerpetual",
          "status": "Trading",
          "baseCoin": "AAVE",
          "quoteCoin": "USDT",
          "launchTime": "1620897660000",
          "deliveryTime": "0",
          "deliveryFeeRate": "",
          "priceScale": "2",
          "leverageFilter": {
            "minLeverage": "1",
            "maxLeverage": "75.00",
            "leverageStep": "0.01"
          },
          "priceFilter": {
            "minPrice": "0.01",
            "maxPrice": "199999.98",
            "tickSize": "0.01"
          },
          "lotSizeFilter": {
            "maxOrderQty": "1200.00",
            "minOrderQty": "0.01",
            "qtyStep": "0.01",
            "postOnlyMaxOrderQty": "1200.00",
            "maxMktOrderQty": "460.00",
            "minNotionalValue": "5"
          },
          "unifiedMarginTrade": true,
          "fundingInterval": 480,
          "settleCoin": "USDT",
          "copyTrading": "both",
          "upperFundingRate": "0.0058",
          "lowerFundingRate": "-0.0058",
          "isPreListing": false,
          "preListingInfo": null,
          "riskParameters": {
            "priceLimitRatioX": "0.05",
            "priceLimitRatioY": "0.1"
          },
          "displayName": "AAVEUSDT",
          "symbolType": "",
          "forbidUplWithdrawal": false,
          "symbolId": 32,
          "fullName": "Aave",
          "marketRegion": "",
          "underlyingTicker": "",
          "tags": []
        }
      ],
      "nextPageCursor": ""
    },
    "retExtInfo": {},
    "time": 1791721542128
  },
  "bybit_history": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00001887",
          "fundingRateTimestamp": "1791705600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00002677",
          "fundingRateTimestamp": "1791676800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000381",
          "fundingRateTimestamp": "1791648000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00001275",
          "fundingRateTimestamp": "1791619200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00016823",
          "fundingRateTimestamp": "1791590400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00000159",
          "fundingRateTimestamp": "1791561600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000752",
          "fundingRateTimestamp": "1791532800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00001528",
          "fundingRateTimestamp": "1791504000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00007177",
          "fundingRateTimestamp": "1791475200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00003329",
          "fundingRateTimestamp": "1791446400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000337",
          "fundingRateTimestamp": "1791417600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002515",
          "fundingRateTimestamp": "1791388800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000341",
          "fundingRateTimestamp": "1791360000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00001678",
          "fundingRateTimestamp": "1791331200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002556",
          "fundingRateTimestamp": "1791302400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00000367",
          "fundingRateTimestamp": "1791273600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00005496",
          "fundingRateTimestamp": "1791244800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791216000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791187200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000398",
          "fundingRateTimestamp": "1791158400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002572",
          "fundingRateTimestamp": "1791129600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00009453",
          "fundingRateTimestamp": "1791100800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791072000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00006691",
          "fundingRateTimestamp": "1791043200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002618",
          "fundingRateTimestamp": "1791014400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790985600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790956800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790928000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002109",
          "fundingRateTimestamp": "1790899200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.0000667",
          "fundingRateTimestamp": "1790870400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00008099",
          "fundingRateTimestamp": "1790841600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790812800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00006479",
          "fundingRateTimestamp": "1790784000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00003757",
          "fundingRateTimestamp": "1790755200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002393",
          "fundingRateTimestamp": "1790726400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790697600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00006686",
          "fundingRateTimestamp": "1790668800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00007068",
          "fundingRateTimestamp": "1790640000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002379",
          "fundingRateTimestamp": "1790611200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00001228",
          "fundingRateTimestamp": "1790582400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790553600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00001874",
          "fundingRateTimestamp": "1790524800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790496000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790467200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790438400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790409600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00002792",
          "fundingRateTimestamp": "1790380800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000831",
          "fundingRateTimestamp": "1790352000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790323200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790294400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00006033",
          "fundingRateTimestamp": "1790265600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.0000019",
          "fundingRateTimestamp": "1790236800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00004649",
          "fundingRateTimestamp": "1790208000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790179200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790150400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790121600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00000271",
          "fundingRateTimestamp": "1790092800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790064000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790035200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00008902",
          "fundingRateTimestamp": "1790006400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00007594",
          "fundingRateTimestamp": "1789977600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00005173",
          "fundingRateTimestamp": "1789948800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.0000224",
          "fundingRateTimestamp": "1789920000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789891200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789862400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789833600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789804800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789776000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789747200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789718400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00009062",
          "fundingRateTimestamp": "1789689600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00005954",
          "fundingRateTimestamp": "1789660800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00001531",
          "fundingRateTimestamp": "1789632000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002739",
          "fundingRateTimestamp": "1789603200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00003163",
          "fundingRateTimestamp": "1789574400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00008883",
          "fundingRateTimestamp": "1789545600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00007204",
          "fundingRateTimestamp": "1789516800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00004381",
          "fundingRateTimestamp": "1789488000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00005143",
          "fundingRateTimestamp": "1789459200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00000492",
          "fundingRateTimestamp": "1789430400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00003318",
          "fundingRateTimestamp": "1789401600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00003131",
          "fundingRateTimestamp": "1789372800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00005078",
          "fundingRateTimestamp": "1789344000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.0000437",
          "fundingRateTimestamp": "1789315200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00002782",
          "fundingRateTimestamp": "1789286400000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.00005581",
          "fundingRateTimestamp": "1789257600000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "-0.0000167",
          "fundingRateTimestamp": "1789228800000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00000852",
          "fundingRateTimestamp": "1789200000000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00000559",
          "fundingRateTimestamp": "1789171200000"
        },
        {
          "symbol": "AAVEUSDT",
          "fundingRate": "0.00001551",
          "fundingRateTimestamp": "1789142400000"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721542351
  },
  "weex_history": [
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00005407",
      "fundingTime": 1789142400000,
      "markPrice": "125.69"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00000336",
      "fundingTime": 1789171200000,
      "markPrice": "124.99"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00000204",
      "fundingTime": 1789200000000,
      "markPrice": "126.22"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00001459",
      "fundingTime": 1789228800000,
      "markPrice": "126.01"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00003058",
      "fundingTime": 1789257600000,
      "markPrice": "125.46"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006568",
      "fundingTime": 1789286400000,
      "markPrice": "126.47"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006558",
      "fundingTime": 1789315200000,
      "markPrice": "125.46"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002517",
      "fundingTime": 1789344000000,
      "markPrice": "124.26"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00003481",
      "fundingTime": 1789372800000,
      "markPrice": "126.26"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00007406",
      "fundingTime": 1789401600000,
      "markPrice": "126.29"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00004314",
      "fundingTime": 1789430400000,
      "markPrice": "128.14"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00001992",
      "fundingTime": 1789459200000,
      "markPrice": "126.35"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006297",
      "fundingTime": 1789488000000,
      "markPrice": "125.05"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789516800000,
      "markPrice": "122.11"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00000231",
      "fundingTime": 1789545600000,
      "markPrice": "119.37"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00001747",
      "fundingTime": 1789574400000,
      "markPrice": "115.91"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00000117",
      "fundingTime": 1789603200000,
      "markPrice": "119.45"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006687",
      "fundingTime": 1789632000000,
      "markPrice": "123.35"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789660800000,
      "markPrice": "126.07"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789689600000,
      "markPrice": "128.52"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789718400000,
      "markPrice": "134.16"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789747200000,
      "markPrice": "138.05"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789776000000,
      "markPrice": "139.48"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789804800000,
      "markPrice": "142.23"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789833600000,
      "markPrice": "142.46"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789862400000,
      "markPrice": "141.02"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789891200000,
      "markPrice": "136.62"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00000694",
      "fundingTime": 1789920000000,
      "markPrice": "135.94"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00004195",
      "fundingTime": 1789948800000,
      "markPrice": "137.46"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00000640",
      "fundingTime": 1789977600000,
      "markPrice": "138.61"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006677",
      "fundingTime": 1790006400000,
      "markPrice": "143.01"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002779",
      "fundingTime": 1790035200000,
      "markPrice": "145.79"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790064000000,
      "markPrice": "141.53"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00009620",
      "fundingTime": 1790092800000,
      "markPrice": "143.11"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790121600000,
      "markPrice": "147.97"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790150400000,
      "markPrice": "149.75"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790179200000,
      "markPrice": "138.87"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00001936",
      "fundingTime": 1790208000000,
      "markPrice": "138.87"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00004314",
      "fundingTime": 1790236800000,
      "markPrice": "140.06"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00009430",
      "fundingTime": 1790265600000,
      "markPrice": "143.65"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790294400000,
      "markPrice": "146.84"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790323200000,
      "markPrice": "143.65"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790352000000,
      "markPrice": "149.25"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00007641",
      "fundingTime": 1790380800000,
      "markPrice": "153.51"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790409600000,
      "markPrice": "154.02"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790438400000,
      "markPrice": "154.93"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790467200000,
      "markPrice": "155.56"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790496000000,
      "markPrice": "157.23"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006411",
      "fundingTime": 1790524800000,
      "markPrice": "153.45"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790553600000,
      "markPrice": "154.48"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00004805",
      "fundingTime": 1790582400000,
      "markPrice": "146.87"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002944",
      "fundingTime": 1790611200000,
      "markPrice": "145.88"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002650",
      "fundingTime": 1790640000000,
      "markPrice": "149.4"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00008920",
      "fundingTime": 1790668800000,
      "markPrice": "163.83"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790697600000,
      "markPrice": "169.95"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790726400000,
      "markPrice": "165.18"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00000697",
      "fundingTime": 1790755200000,
      "markPrice": "159.2"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00008137",
      "fundingTime": 1790784000000,
      "markPrice": "159.92"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002492",
      "fundingTime": 1790812800000,
      "markPrice": "159.37"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00005973",
      "fundingTime": 1790841600000,
      "markPrice": "164.68"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002810",
      "fundingTime": 1790870400000,
      "markPrice": "168.12"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00001459",
      "fundingTime": 1790899200000,
      "markPrice": "171.27"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790928000000,
      "markPrice": "183.9"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790956800000,
      "markPrice": "182.95"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006858",
      "fundingTime": 1790985600000,
      "markPrice": "179.48"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00003853",
      "fundingTime": 1791014400000,
      "markPrice": "179.75"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006850",
      "fundingTime": 1791043200000,
      "markPrice": "178.79"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791072000000,
      "markPrice": "181.43"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00005213",
      "fundingTime": 1791100800000,
      "markPrice": "182.49"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002659",
      "fundingTime": 1791129600000,
      "markPrice": "178.56"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00008418",
      "fundingTime": 1791158400000,
      "markPrice": "179.03"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00002664",
      "fundingTime": 1791187200000,
      "markPrice": "179.89"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791216000000,
      "markPrice": "182.81"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00001500",
      "fundingTime": 1791244800000,
      "markPrice": "183.92"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00005970",
      "fundingTime": 1791273600000,
      "markPrice": "181.1"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791302400000,
      "markPrice": "180.97"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006180",
      "fundingTime": 1791331200000,
      "markPrice": "179.56"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00004893",
      "fundingTime": 1791360000000,
      "markPrice": "176.33"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791388800000,
      "markPrice": "171.77"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00005026",
      "fundingTime": 1791417600000,
      "markPrice": "173.95"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006854",
      "fundingTime": 1791446400000,
      "markPrice": "172.2"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00005161",
      "fundingTime": 1791475200000,
      "markPrice": "164.79"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00007444",
      "fundingTime": 1791504000000,
      "markPrice": "166.04"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00003291",
      "fundingTime": 1791532800000,
      "markPrice": "167.6"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00006020",
      "fundingTime": 1791561600000,
      "markPrice": "169.88"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00000111",
      "fundingTime": 1791590400000,
      "markPrice": "167.19"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00002134",
      "fundingTime": 1791619200000,
      "markPrice": "173.64"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00001069",
      "fundingTime": 1791648000000,
      "markPrice": "171.51"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "-0.00001844",
      "fundingTime": 1791676800000,
      "markPrice": "168.26"
    },
    {
      "symbol": "AAVEUSDT",
      "fundingRate": "0.00007384",
      "fundingTime": 1791705600000,
      "markPrice": "166.92"
    }
  ]
}
```

</details>


<details>
<summary>funding_raw/BTCUSDT.json</summary>

SHA256 UTF-8/LF: `4e8fc68bedb0e39cb1385e26ab53050c8ca9a49158b2b6c7ba397e8c761148b6`

```json
{
  "weex_current": [
    {
      "symbol": "BTCUSDT",
      "markPrice": "83101.9",
      "indexPrice": "83134.60725",
      "forecastFundingRate": "-0.00000079",
      "lastFundingRate": "-0.00000993",
      "interestRate": "0.0003",
      "nextFundingTime": 1791734400000,
      "time": 1791721537409,
      "collectCycle": 480
    }
  ],
  "weex_book": [
    {
      "symbol": "BTCUSDT",
      "bidPrice": "83088.4",
      "bidQty": "2.8990",
      "askPrice": "83088.5",
      "askQty": "2.4395",
      "time": 1791721537519
    }
  ],
  "bybit_current": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "BTCUSDT",
          "lastPrice": "83074.30",
          "indexPrice": "83124.46",
          "markPrice": "83078.46",
          "prevPrice24h": "82784.60",
          "price24hPcnt": "0.003499",
          "highPrice24h": "83235.90",
          "lowPrice24h": "82730.40",
          "prevPrice1h": "83011.40",
          "openInterest": "56279.046",
          "openInterestValue": "4675576471.95",
          "singleOpenInterest": "28139.523",
          "singleOpenInterestValue": "2337788235.97",
          "turnover24h": "987459909.8864",
          "volume24h": "11899.0900",
          "fundingRate": "0.00003882",
          "nextFundingTime": "1791734400000",
          "predictedDeliveryPrice": "",
          "basisRate": "",
          "deliveryFeeRate": "",
          "deliveryTime": "0",
          "ask1Size": "9.852",
          "bid1Price": "83074.20",
          "ask1Price": "83074.30",
          "bid1Size": "0.040",
          "basis": "",
          "preOpenPrice": "",
          "preQty": "",
          "curPreListingPhase": "",
          "fundingIntervalHour": "8",
          "basisRateYear": "",
          "fundingCap": "0.00333"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721537943
  },
  "bybit_instrument": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "BTCUSDT",
          "contractType": "LinearPerpetual",
          "status": "Trading",
          "baseCoin": "BTC",
          "quoteCoin": "USDT",
          "launchTime": "1584230400000",
          "deliveryTime": "0",
          "deliveryFeeRate": "",
          "priceScale": "2",
          "leverageFilter": {
            "minLeverage": "1",
            "maxLeverage": "150.00",
            "leverageStep": "0.01"
          },
          "priceFilter": {
            "minPrice": "0.10",
            "maxPrice": "1999999.80",
            "tickSize": "0.10"
          },
          "lotSizeFilter": {
            "maxOrderQty": "1500.000",
            "minOrderQty": "0.001",
            "qtyStep": "0.001",
            "postOnlyMaxOrderQty": "1500.000",
            "maxMktOrderQty": "150.000",
            "minNotionalValue": "5"
          },
          "unifiedMarginTrade": true,
          "fundingInterval": 480,
          "settleCoin": "USDT",
          "copyTrading": "both",
          "upperFundingRate": "0.00333",
          "lowerFundingRate": "-0.00333",
          "isPreListing": false,
          "preListingInfo": null,
          "riskParameters": {
            "priceLimitRatioX": "0.01",
            "priceLimitRatioY": "0.02"
          },
          "displayName": "BTCUSDT",
          "symbolType": "",
          "forbidUplWithdrawal": false,
          "symbolId": 5,
          "fullName": "Bitcoin",
          "marketRegion": "",
          "underlyingTicker": "",
          "tags": []
        }
      ],
      "nextPageCursor": ""
    },
    "retExtInfo": {},
    "time": 1791721538317
  },
  "bybit_history": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000326",
          "fundingRateTimestamp": "1791705600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000936",
          "fundingRateTimestamp": "1791676800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000433",
          "fundingRateTimestamp": "1791648000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00001171",
          "fundingRateTimestamp": "1791619200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00001182",
          "fundingRateTimestamp": "1791590400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004363",
          "fundingRateTimestamp": "1791561600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003277",
          "fundingRateTimestamp": "1791532800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008676",
          "fundingRateTimestamp": "1791504000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004085",
          "fundingRateTimestamp": "1791475200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00001339",
          "fundingRateTimestamp": "1791446400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001078",
          "fundingRateTimestamp": "1791417600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001497",
          "fundingRateTimestamp": "1791388800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000357",
          "fundingRateTimestamp": "1791360000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001655",
          "fundingRateTimestamp": "1791331200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005758",
          "fundingRateTimestamp": "1791302400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000088",
          "fundingRateTimestamp": "1791273600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001177",
          "fundingRateTimestamp": "1791244800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003208",
          "fundingRateTimestamp": "1791216000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003074",
          "fundingRateTimestamp": "1791187200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008732",
          "fundingRateTimestamp": "1791158400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005489",
          "fundingRateTimestamp": "1791129600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00002782",
          "fundingRateTimestamp": "1791100800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000204",
          "fundingRateTimestamp": "1791072000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000543",
          "fundingRateTimestamp": "1791043200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.0000342",
          "fundingRateTimestamp": "1791014400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00004579",
          "fundingRateTimestamp": "1790985600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790956800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790928000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005235",
          "fundingRateTimestamp": "1790899200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005283",
          "fundingRateTimestamp": "1790870400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004127",
          "fundingRateTimestamp": "1790841600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004076",
          "fundingRateTimestamp": "1790812800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005495",
          "fundingRateTimestamp": "1790784000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000397",
          "fundingRateTimestamp": "1790755200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00006254",
          "fundingRateTimestamp": "1790726400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000398",
          "fundingRateTimestamp": "1790697600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00002815",
          "fundingRateTimestamp": "1790668800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0000297",
          "fundingRateTimestamp": "1790640000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004941",
          "fundingRateTimestamp": "1790611200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00002442",
          "fundingRateTimestamp": "1790582400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000962",
          "fundingRateTimestamp": "1790553600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003647",
          "fundingRateTimestamp": "1790524800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00002285",
          "fundingRateTimestamp": "1790496000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004892",
          "fundingRateTimestamp": "1790467200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00001027",
          "fundingRateTimestamp": "1790438400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00002446",
          "fundingRateTimestamp": "1790409600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001043",
          "fundingRateTimestamp": "1790380800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000533",
          "fundingRateTimestamp": "1790352000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00000134",
          "fundingRateTimestamp": "1790323200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00002517",
          "fundingRateTimestamp": "1790294400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000951",
          "fundingRateTimestamp": "1790265600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "-0.00001295",
          "fundingRateTimestamp": "1790236800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000678",
          "fundingRateTimestamp": "1790208000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005775",
          "fundingRateTimestamp": "1790179200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008058",
          "fundingRateTimestamp": "1790150400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003927",
          "fundingRateTimestamp": "1790121600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003607",
          "fundingRateTimestamp": "1790092800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00009068",
          "fundingRateTimestamp": "1790064000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790035200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008264",
          "fundingRateTimestamp": "1790006400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789977600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789948800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0000426",
          "fundingRateTimestamp": "1789920000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00007123",
          "fundingRateTimestamp": "1789891200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00006562",
          "fundingRateTimestamp": "1789862400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789833600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008679",
          "fundingRateTimestamp": "1789804800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008884",
          "fundingRateTimestamp": "1789776000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789747200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00008745",
          "fundingRateTimestamp": "1789718400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001879",
          "fundingRateTimestamp": "1789689600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00006259",
          "fundingRateTimestamp": "1789660800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005851",
          "fundingRateTimestamp": "1789632000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005959",
          "fundingRateTimestamp": "1789603200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00006917",
          "fundingRateTimestamp": "1789574400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004262",
          "fundingRateTimestamp": "1789545600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004674",
          "fundingRateTimestamp": "1789516800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003615",
          "fundingRateTimestamp": "1789488000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001124",
          "fundingRateTimestamp": "1789459200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00002656",
          "fundingRateTimestamp": "1789430400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004341",
          "fundingRateTimestamp": "1789401600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00007731",
          "fundingRateTimestamp": "1789372800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003772",
          "fundingRateTimestamp": "1789344000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003959",
          "fundingRateTimestamp": "1789315200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00004304",
          "fundingRateTimestamp": "1789286400000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005721",
          "fundingRateTimestamp": "1789257600000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00003813",
          "fundingRateTimestamp": "1789228800000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00001549",
          "fundingRateTimestamp": "1789200000000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00000219",
          "fundingRateTimestamp": "1789171200000"
        },
        {
          "symbol": "BTCUSDT",
          "fundingRate": "0.00005602",
          "fundingRateTimestamp": "1789142400000"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721538547
  },
  "weex_history": [
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003668",
      "fundingTime": 1789142400000,
      "markPrice": "77690.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006040",
      "fundingTime": 1789171200000,
      "markPrice": "77191.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004368",
      "fundingTime": 1789200000000,
      "markPrice": "77236.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00005153",
      "fundingTime": 1789228800000,
      "markPrice": "77347.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004794",
      "fundingTime": 1789257600000,
      "markPrice": "77244.4"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00005390",
      "fundingTime": 1789286400000,
      "markPrice": "77090.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006450",
      "fundingTime": 1789315200000,
      "markPrice": "77099.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007157",
      "fundingTime": 1789344000000,
      "markPrice": "76807.4"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00008037",
      "fundingTime": 1789372800000,
      "markPrice": "77854"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004265",
      "fundingTime": 1789401600000,
      "markPrice": "78542.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003563",
      "fundingTime": 1789430400000,
      "markPrice": "78166.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006197",
      "fundingTime": 1789459200000,
      "markPrice": "76902.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00009890",
      "fundingTime": 1789488000000,
      "markPrice": "76475"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004000",
      "fundingTime": 1789516800000,
      "markPrice": "75603.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00002833",
      "fundingTime": 1789545600000,
      "markPrice": "75726"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00005240",
      "fundingTime": 1789574400000,
      "markPrice": "75753.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00009369",
      "fundingTime": 1789603200000,
      "markPrice": "76174.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003388",
      "fundingTime": 1789632000000,
      "markPrice": "76422.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00008505",
      "fundingTime": 1789660800000,
      "markPrice": "76755.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007769",
      "fundingTime": 1789689600000,
      "markPrice": "76385.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007908",
      "fundingTime": 1789718400000,
      "markPrice": "77775.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006789",
      "fundingTime": 1789747200000,
      "markPrice": "80690.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006588",
      "fundingTime": 1789776000000,
      "markPrice": "80863.2"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789804800000,
      "markPrice": "81070.4"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789833600000,
      "markPrice": "81609.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789862400000,
      "markPrice": "81225.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789891200000,
      "markPrice": "80286.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007557",
      "fundingTime": 1789920000000,
      "markPrice": "80872.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004200",
      "fundingTime": 1789948800000,
      "markPrice": "81143.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789977600000,
      "markPrice": "81697.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00005597",
      "fundingTime": 1790006400000,
      "markPrice": "85881"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007603",
      "fundingTime": 1790035200000,
      "markPrice": "86586.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790064000000,
      "markPrice": "85324.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00002874",
      "fundingTime": 1790092800000,
      "markPrice": "86367.4"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001021",
      "fundingTime": 1790121600000,
      "markPrice": "86163.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00000332",
      "fundingTime": 1790150400000,
      "markPrice": "86100.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001286",
      "fundingTime": 1790179200000,
      "markPrice": "83965.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00000101",
      "fundingTime": 1790208000000,
      "markPrice": "84356.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004922",
      "fundingTime": 1790236800000,
      "markPrice": "84468.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001443",
      "fundingTime": 1790265600000,
      "markPrice": "84374.2"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00000196",
      "fundingTime": 1790294400000,
      "markPrice": "84369.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003512",
      "fundingTime": 1790323200000,
      "markPrice": "83994.7"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00000680",
      "fundingTime": 1790352000000,
      "markPrice": "83766.7"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00000779",
      "fundingTime": 1790380800000,
      "markPrice": "84055.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004940",
      "fundingTime": 1790409600000,
      "markPrice": "84078.4"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00000552",
      "fundingTime": 1790438400000,
      "markPrice": "84112.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004645",
      "fundingTime": 1790467200000,
      "markPrice": "84403"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001408",
      "fundingTime": 1790496000000,
      "markPrice": "84755.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001032",
      "fundingTime": 1790524800000,
      "markPrice": "84426.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00002034",
      "fundingTime": 1790553600000,
      "markPrice": "84433"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00002527",
      "fundingTime": 1790582400000,
      "markPrice": "82920.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006482",
      "fundingTime": 1790611200000,
      "markPrice": "83346.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003842",
      "fundingTime": 1790640000000,
      "markPrice": "83460.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006810",
      "fundingTime": 1790668800000,
      "markPrice": "83946.7"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001391",
      "fundingTime": 1790697600000,
      "markPrice": "83031"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007737",
      "fundingTime": 1790726400000,
      "markPrice": "83624.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00000189",
      "fundingTime": 1790755200000,
      "markPrice": "83258.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00006604",
      "fundingTime": 1790784000000,
      "markPrice": "84104.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00008007",
      "fundingTime": 1790812800000,
      "markPrice": "83580"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004669",
      "fundingTime": 1790841600000,
      "markPrice": "83383.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007000",
      "fundingTime": 1790870400000,
      "markPrice": "84126.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00002706",
      "fundingTime": 1790899200000,
      "markPrice": "84833.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790928000000,
      "markPrice": "86064.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001214",
      "fundingTime": 1790956800000,
      "markPrice": "85297.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004568",
      "fundingTime": 1790985600000,
      "markPrice": "84482.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00000411",
      "fundingTime": 1791014400000,
      "markPrice": "84521.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004449",
      "fundingTime": 1791043200000,
      "markPrice": "84834.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00001346",
      "fundingTime": 1791072000000,
      "markPrice": "84710.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003445",
      "fundingTime": 1791100800000,
      "markPrice": "85069.7"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003828",
      "fundingTime": 1791129600000,
      "markPrice": "85212.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00007483",
      "fundingTime": 1791158400000,
      "markPrice": "86490"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00004186",
      "fundingTime": 1791187200000,
      "markPrice": "86221.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00001541",
      "fundingTime": 1791216000000,
      "markPrice": "85226.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00002485",
      "fundingTime": 1791244800000,
      "markPrice": "85717.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00001527",
      "fundingTime": 1791273600000,
      "markPrice": "85512.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00002465",
      "fundingTime": 1791302400000,
      "markPrice": "85675.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00000759",
      "fundingTime": 1791331200000,
      "markPrice": "85517"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00003693",
      "fundingTime": 1791360000000,
      "markPrice": "84095.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001152",
      "fundingTime": 1791388800000,
      "markPrice": "83411.3"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00001030",
      "fundingTime": 1791417600000,
      "markPrice": "83282.1"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00001142",
      "fundingTime": 1791446400000,
      "markPrice": "82949.6"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00003502",
      "fundingTime": 1791475200000,
      "markPrice": "81006.8"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001792",
      "fundingTime": 1791504000000,
      "markPrice": "81710.9"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00005152",
      "fundingTime": 1791532800000,
      "markPrice": "82619.2"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00001238",
      "fundingTime": 1791561600000,
      "markPrice": "82845.5"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00005342",
      "fundingTime": 1791590400000,
      "markPrice": "82585.2"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00000417",
      "fundingTime": 1791619200000,
      "markPrice": "82761.4"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.00000457",
      "fundingTime": 1791648000000,
      "markPrice": "83013.2"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00002659",
      "fundingTime": 1791676800000,
      "markPrice": "82941"
    },
    {
      "symbol": "BTCUSDT",
      "fundingRate": "-0.00000993",
      "fundingTime": 1791705600000,
      "markPrice": "82980.5"
    }
  ]
}
```

</details>


<details>
<summary>funding_raw/DOGEUSDT.json</summary>

SHA256 UTF-8/LF: `6c59707013f6f244054df9367b9d3004b8fc416c33c689f015d374e6ecc36ebc`

```json
{
  "weex_current": [
    {
      "symbol": "DOGEUSDT",
      "markPrice": "0.0853",
      "indexPrice": "0.08533925",
      "forecastFundingRate": "-0.00000679",
      "lastFundingRate": "0.00004415",
      "interestRate": "0.0003",
      "nextFundingTime": 1791734400000,
      "time": 1791721541228,
      "collectCycle": 480
    }
  ],
  "weex_book": [
    {
      "symbol": "DOGEUSDT",
      "bidPrice": "0.08524",
      "bidQty": "295300",
      "askPrice": "0.08525",
      "askQty": "230900",
      "time": 1791721541366
    }
  ],
  "bybit_current": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "DOGEUSDT",
          "lastPrice": "0.08525",
          "indexPrice": "0.08530",
          "markPrice": "0.08525",
          "prevPrice24h": "0.08571",
          "price24hPcnt": "-0.005366",
          "highPrice24h": "0.08661",
          "lowPrice24h": "0.08483",
          "prevPrice1h": "0.08514",
          "openInterest": "1399205361",
          "openInterestValue": "119282257.03",
          "singleOpenInterest": "699602681",
          "singleOpenInterestValue": "59641128.56",
          "turnover24h": "34696169.9104",
          "volume24h": "404995044.0000",
          "fundingRate": "0.00000565",
          "nextFundingTime": "1791734400000",
          "predictedDeliveryPrice": "",
          "basisRate": "",
          "deliveryFeeRate": "",
          "deliveryTime": "0",
          "ask1Size": "426101",
          "bid1Price": "0.08525",
          "ask1Price": "0.08526",
          "bid1Size": "62091",
          "basis": "",
          "preOpenPrice": "",
          "preQty": "",
          "curPreListingPhase": "",
          "fundingIntervalHour": "8",
          "basisRateYear": "",
          "fundingCap": "0.0058"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721541764
  },
  "bybit_instrument": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "DOGEUSDT",
          "contractType": "LinearPerpetual",
          "status": "Trading",
          "baseCoin": "DOGE",
          "quoteCoin": "USDT",
          "launchTime": "1622630640000",
          "deliveryTime": "0",
          "deliveryFeeRate": "",
          "priceScale": "5",
          "leverageFilter": {
            "minLeverage": "1",
            "maxLeverage": "75.00",
            "leverageStep": "0.01"
          },
          "priceFilter": {
            "minPrice": "0.00001",
            "maxPrice": "199.99998",
            "tickSize": "0.00001"
          },
          "lotSizeFilter": {
            "maxOrderQty": "43678900",
            "minOrderQty": "1",
            "qtyStep": "1",
            "postOnlyMaxOrderQty": "43678900",
            "maxMktOrderQty": "5991100",
            "minNotionalValue": "5"
          },
          "unifiedMarginTrade": true,
          "fundingInterval": 480,
          "settleCoin": "USDT",
          "copyTrading": "both",
          "upperFundingRate": "0.0058",
          "lowerFundingRate": "-0.0058",
          "isPreListing": false,
          "preListingInfo": null,
          "riskParameters": {
            "priceLimitRatioX": "0.05",
            "priceLimitRatioY": "0.1"
          },
          "displayName": "DOGEUSDT",
          "symbolType": "",
          "forbidUplWithdrawal": false,
          "symbolId": 33,
          "fullName": "Dogecoin",
          "marketRegion": "",
          "underlyingTicker": "",
          "tags": []
        }
      ],
      "nextPageCursor": ""
    },
    "retExtInfo": {},
    "time": 1791721541979
  },
  "bybit_history": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00000966",
          "fundingRateTimestamp": "1791705600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00001861",
          "fundingRateTimestamp": "1791676800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004051",
          "fundingRateTimestamp": "1791648000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00001585",
          "fundingRateTimestamp": "1791619200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00004143",
          "fundingRateTimestamp": "1791590400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00000401",
          "fundingRateTimestamp": "1791561600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00008343",
          "fundingRateTimestamp": "1791532800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00007645",
          "fundingRateTimestamp": "1791504000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00000992",
          "fundingRateTimestamp": "1791475200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.000072",
          "fundingRateTimestamp": "1791446400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002807",
          "fundingRateTimestamp": "1791417600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002919",
          "fundingRateTimestamp": "1791388800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00001251",
          "fundingRateTimestamp": "1791360000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791331200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791302400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00000698",
          "fundingRateTimestamp": "1791273600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791244800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791216000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791187200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791158400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004012",
          "fundingRateTimestamp": "1791129600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002745",
          "fundingRateTimestamp": "1791100800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00007476",
          "fundingRateTimestamp": "1791072000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00000125",
          "fundingRateTimestamp": "1791043200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00001159",
          "fundingRateTimestamp": "1791014400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00009414",
          "fundingRateTimestamp": "1790985600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790956800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790928000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790899200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002906",
          "fundingRateTimestamp": "1790870400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00006372",
          "fundingRateTimestamp": "1790841600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00003759",
          "fundingRateTimestamp": "1790812800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00006032",
          "fundingRateTimestamp": "1790784000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00001269",
          "fundingRateTimestamp": "1790755200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00008848",
          "fundingRateTimestamp": "1790726400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790697600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790668800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00001665",
          "fundingRateTimestamp": "1790640000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00004234",
          "fundingRateTimestamp": "1790611200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004125",
          "fundingRateTimestamp": "1790582400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004718",
          "fundingRateTimestamp": "1790553600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004181",
          "fundingRateTimestamp": "1790524800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790496000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00005592",
          "fundingRateTimestamp": "1790467200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00007203",
          "fundingRateTimestamp": "1790438400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00003844",
          "fundingRateTimestamp": "1790409600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790380800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790352000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00001654",
          "fundingRateTimestamp": "1790323200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790294400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0000261",
          "fundingRateTimestamp": "1790265600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00003159",
          "fundingRateTimestamp": "1790236800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00001134",
          "fundingRateTimestamp": "1790208000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00005393",
          "fundingRateTimestamp": "1790179200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790150400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790121600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790092800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790064000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790035200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790006400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789977600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789948800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002526",
          "fundingRateTimestamp": "1789920000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00007101",
          "fundingRateTimestamp": "1789891200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789862400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789833600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789804800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789776000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789747200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789718400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00005552",
          "fundingRateTimestamp": "1789689600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00001021",
          "fundingRateTimestamp": "1789660800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0000014",
          "fundingRateTimestamp": "1789632000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004114",
          "fundingRateTimestamp": "1789603200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00005031",
          "fundingRateTimestamp": "1789574400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00000153",
          "fundingRateTimestamp": "1789545600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00001109",
          "fundingRateTimestamp": "1789516800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00006135",
          "fundingRateTimestamp": "1789488000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00000036",
          "fundingRateTimestamp": "1789459200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002747",
          "fundingRateTimestamp": "1789430400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00000971",
          "fundingRateTimestamp": "1789401600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0000159",
          "fundingRateTimestamp": "1789372800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002785",
          "fundingRateTimestamp": "1789344000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.0000237",
          "fundingRateTimestamp": "1789315200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00003507",
          "fundingRateTimestamp": "1789286400000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.0000215",
          "fundingRateTimestamp": "1789257600000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00006151",
          "fundingRateTimestamp": "1789228800000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "-0.00004065",
          "fundingRateTimestamp": "1789200000000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00004074",
          "fundingRateTimestamp": "1789171200000"
        },
        {
          "symbol": "DOGEUSDT",
          "fundingRate": "0.00002704",
          "fundingRateTimestamp": "1789142400000"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721542192
  },
  "weex_history": [
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00005771",
      "fundingTime": 1789142400000,
      "markPrice": "0.08493"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00003166",
      "fundingTime": 1789171200000,
      "markPrice": "0.08426"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00006408",
      "fundingTime": 1789200000000,
      "markPrice": "0.0847"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789228800000,
      "markPrice": "0.08506"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00003722",
      "fundingTime": 1789257600000,
      "markPrice": "0.08478"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002152",
      "fundingTime": 1789286400000,
      "markPrice": "0.08412"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00000348",
      "fundingTime": 1789315200000,
      "markPrice": "0.08344"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00000777",
      "fundingTime": 1789344000000,
      "markPrice": "0.08235"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00009527",
      "fundingTime": 1789372800000,
      "markPrice": "0.08431"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00003050",
      "fundingTime": 1789401600000,
      "markPrice": "0.084"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789430400000,
      "markPrice": "0.0836"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004466",
      "fundingTime": 1789459200000,
      "markPrice": "0.08249"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00001252",
      "fundingTime": 1789488000000,
      "markPrice": "0.08162"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004666",
      "fundingTime": 1789516800000,
      "markPrice": "0.08003"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00005480",
      "fundingTime": 1789545600000,
      "markPrice": "0.07962"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002631",
      "fundingTime": 1789574400000,
      "markPrice": "0.07899"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00005598",
      "fundingTime": 1789603200000,
      "markPrice": "0.08087"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00000374",
      "fundingTime": 1789632000000,
      "markPrice": "0.08113"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004330",
      "fundingTime": 1789660800000,
      "markPrice": "0.08194"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789689600000,
      "markPrice": "0.08167"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789718400000,
      "markPrice": "0.08443"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789747200000,
      "markPrice": "0.08747"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789776000000,
      "markPrice": "0.08743"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789804800000,
      "markPrice": "0.08666"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789833600000,
      "markPrice": "0.0889"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789862400000,
      "markPrice": "0.08769"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789891200000,
      "markPrice": "0.08484"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004903",
      "fundingTime": 1789920000000,
      "markPrice": "0.08578"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00009461",
      "fundingTime": 1789948800000,
      "markPrice": "0.08725"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789977600000,
      "markPrice": "0.08974"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790006400000,
      "markPrice": "0.09729"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790035200000,
      "markPrice": "0.09982"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790064000000,
      "markPrice": "0.09881"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790092800000,
      "markPrice": "0.09996"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790121600000,
      "markPrice": "0.10037"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790150400000,
      "markPrice": "0.10084"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790179200000,
      "markPrice": "0.09271"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00001792",
      "fundingTime": 1790208000000,
      "markPrice": "0.09267"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002405",
      "fundingTime": 1790236800000,
      "markPrice": "0.09455"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004327",
      "fundingTime": 1790265600000,
      "markPrice": "0.09561"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00009720",
      "fundingTime": 1790294400000,
      "markPrice": "0.09574"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790323200000,
      "markPrice": "0.09546"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790352000000,
      "markPrice": "0.09739"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790380800000,
      "markPrice": "0.09893"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790409600000,
      "markPrice": "0.09791"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004487",
      "fundingTime": 1790438400000,
      "markPrice": "0.09862"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002863",
      "fundingTime": 1790467200000,
      "markPrice": "0.09668"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004723",
      "fundingTime": 1790496000000,
      "markPrice": "0.09809"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00008217",
      "fundingTime": 1790524800000,
      "markPrice": "0.09688"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00005844",
      "fundingTime": 1790553600000,
      "markPrice": "0.09687"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00001068",
      "fundingTime": 1790582400000,
      "markPrice": "0.0925"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002986",
      "fundingTime": 1790611200000,
      "markPrice": "0.09334"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002915",
      "fundingTime": 1790640000000,
      "markPrice": "0.09391"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790668800000,
      "markPrice": "0.09504"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790697600000,
      "markPrice": "0.09369"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00008717",
      "fundingTime": 1790726400000,
      "markPrice": "0.09385"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00008288",
      "fundingTime": 1790755200000,
      "markPrice": "0.09374"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790784000000,
      "markPrice": "0.09533"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004783",
      "fundingTime": 1790812800000,
      "markPrice": "0.09451"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790841600000,
      "markPrice": "0.09424"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00007211",
      "fundingTime": 1790870400000,
      "markPrice": "0.09427"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790899200000,
      "markPrice": "0.09432"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790928000000,
      "markPrice": "0.09645"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790956800000,
      "markPrice": "0.09507"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00004601",
      "fundingTime": 1790985600000,
      "markPrice": "0.09289"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791014400000,
      "markPrice": "0.09262"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00002995",
      "fundingTime": 1791043200000,
      "markPrice": "0.09308"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791072000000,
      "markPrice": "0.09277"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00003354",
      "fundingTime": 1791100800000,
      "markPrice": "0.09344"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791129600000,
      "markPrice": "0.09414"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791158400000,
      "markPrice": "0.09589"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791187200000,
      "markPrice": "0.09655"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791216000000,
      "markPrice": "0.09451"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791244800000,
      "markPrice": "0.09538"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00000499",
      "fundingTime": 1791273600000,
      "markPrice": "0.09463"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791302400000,
      "markPrice": "0.09533"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00005037",
      "fundingTime": 1791331200000,
      "markPrice": "0.09364"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00009351",
      "fundingTime": 1791360000000,
      "markPrice": "0.09086"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00002786",
      "fundingTime": 1791388800000,
      "markPrice": "0.08879"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00001597",
      "fundingTime": 1791417600000,
      "markPrice": "0.08898"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00000747",
      "fundingTime": 1791446400000,
      "markPrice": "0.08763"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00003663",
      "fundingTime": 1791475200000,
      "markPrice": "0.08263"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00001490",
      "fundingTime": 1791504000000,
      "markPrice": "0.08399"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00001877",
      "fundingTime": 1791532800000,
      "markPrice": "0.08535"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00003134",
      "fundingTime": 1791561600000,
      "markPrice": "0.08459"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00005120",
      "fundingTime": 1791590400000,
      "markPrice": "0.08533"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00007343",
      "fundingTime": 1791619200000,
      "markPrice": "0.0861"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00000811",
      "fundingTime": 1791648000000,
      "markPrice": "0.08618"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "-0.00001981",
      "fundingTime": 1791676800000,
      "markPrice": "0.08572"
    },
    {
      "symbol": "DOGEUSDT",
      "fundingRate": "0.00004415",
      "fundingTime": 1791705600000,
      "markPrice": "0.08516"
    }
  ]
}
```

</details>


<details>
<summary>funding_raw/ETHUSDT.json</summary>

SHA256 UTF-8/LF: `c647abafe095c4180fda1c596dd7a126f5c45f2b1228e0f540168d45ddf9462f`

```json
{
  "weex_current": [
    {
      "symbol": "ETHUSDT",
      "markPrice": "2504.89",
      "indexPrice": "2506.16925",
      "forecastFundingRate": "-0.00002113",
      "lastFundingRate": "-0.00011662",
      "interestRate": "0.001",
      "nextFundingTime": 1791734400000,
      "time": 1791721537405,
      "collectCycle": 480
    }
  ],
  "weex_book": [
    {
      "symbol": "ETHUSDT",
      "bidPrice": "2504.46",
      "bidQty": "48.138",
      "askPrice": "2504.47",
      "askQty": "46.044",
      "time": 1791721537573
    }
  ],
  "bybit_current": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "ETHUSDT",
          "lastPrice": "2504.47",
          "indexPrice": "2505.76",
          "markPrice": "2504.47",
          "prevPrice24h": "2495.12",
          "price24hPcnt": "0.003747",
          "highPrice24h": "2518.00",
          "lowPrice24h": "2494.29",
          "prevPrice1h": "2501.18",
          "openInterest": "792491.45",
          "openInterestValue": "1984771061.78",
          "singleOpenInterest": "396245.73",
          "singleOpenInterestValue": "992385543.41",
          "turnover24h": "781539389.8581",
          "volume24h": "311965.6900",
          "fundingRate": "0.0000208",
          "nextFundingTime": "1791734400000",
          "predictedDeliveryPrice": "",
          "basisRate": "",
          "deliveryFeeRate": "",
          "deliveryTime": "0",
          "ask1Size": "87.21",
          "bid1Price": "2504.46",
          "ask1Price": "2504.47",
          "bid1Size": "0.68",
          "basis": "",
          "preOpenPrice": "",
          "preQty": "",
          "curPreListingPhase": "",
          "fundingIntervalHour": "8",
          "basisRateYear": "",
          "fundingCap": "0.00333"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721537941
  },
  "bybit_instrument": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "ETHUSDT",
          "contractType": "LinearPerpetual",
          "status": "Trading",
          "baseCoin": "ETH",
          "quoteCoin": "USDT",
          "launchTime": "1615766400000",
          "deliveryTime": "0",
          "deliveryFeeRate": "",
          "priceScale": "2",
          "leverageFilter": {
            "minLeverage": "1",
            "maxLeverage": "150.00",
            "leverageStep": "0.01"
          },
          "priceFilter": {
            "minPrice": "0.01",
            "maxPrice": "199999.98",
            "tickSize": "0.01"
          },
          "lotSizeFilter": {
            "maxOrderQty": "10000.00",
            "minOrderQty": "0.01",
            "qtyStep": "0.01",
            "postOnlyMaxOrderQty": "10000.00",
            "maxMktOrderQty": "2000.00",
            "minNotionalValue": "5"
          },
          "unifiedMarginTrade": true,
          "fundingInterval": 480,
          "settleCoin": "USDT",
          "copyTrading": "both",
          "upperFundingRate": "0.00333",
          "lowerFundingRate": "-0.00333",
          "isPreListing": false,
          "preListingInfo": null,
          "riskParameters": {
            "priceLimitRatioX": "0.02",
            "priceLimitRatioY": "0.04"
          },
          "displayName": "ETHUSDT",
          "symbolType": "",
          "forbidUplWithdrawal": false,
          "symbolId": 6,
          "fullName": "Ethereum",
          "marketRegion": "",
          "underlyingTicker": "",
          "tags": []
        }
      ],
      "nextPageCursor": ""
    },
    "retExtInfo": {},
    "time": 1791721538318
  },
  "bybit_history": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.0000537",
          "fundingRateTimestamp": "1791705600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00004925",
          "fundingRateTimestamp": "1791676800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002983",
          "fundingRateTimestamp": "1791648000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00000303",
          "fundingRateTimestamp": "1791619200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00000916",
          "fundingRateTimestamp": "1791590400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.0000207",
          "fundingRateTimestamp": "1791561600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.0000088",
          "fundingRateTimestamp": "1791532800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004163",
          "fundingRateTimestamp": "1791504000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002179",
          "fundingRateTimestamp": "1791475200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00003445",
          "fundingRateTimestamp": "1791446400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.0000287",
          "fundingRateTimestamp": "1791417600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00003482",
          "fundingRateTimestamp": "1791388800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00005819",
          "fundingRateTimestamp": "1791360000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791331200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004897",
          "fundingRateTimestamp": "1791302400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00000573",
          "fundingRateTimestamp": "1791273600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00005185",
          "fundingRateTimestamp": "1791244800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00001286",
          "fundingRateTimestamp": "1791216000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00005037",
          "fundingRateTimestamp": "1791187200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008169",
          "fundingRateTimestamp": "1791158400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004782",
          "fundingRateTimestamp": "1791129600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004809",
          "fundingRateTimestamp": "1791100800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008719",
          "fundingRateTimestamp": "1791072000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.0000007",
          "fundingRateTimestamp": "1791043200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002399",
          "fundingRateTimestamp": "1791014400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00003937",
          "fundingRateTimestamp": "1790985600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003303",
          "fundingRateTimestamp": "1790956800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790928000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004088",
          "fundingRateTimestamp": "1790899200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004946",
          "fundingRateTimestamp": "1790870400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790841600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003719",
          "fundingRateTimestamp": "1790812800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003212",
          "fundingRateTimestamp": "1790784000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004135",
          "fundingRateTimestamp": "1790755200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00005524",
          "fundingRateTimestamp": "1790726400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008702",
          "fundingRateTimestamp": "1790697600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00009032",
          "fundingRateTimestamp": "1790668800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00005247",
          "fundingRateTimestamp": "1790640000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000661",
          "fundingRateTimestamp": "1790611200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00004295",
          "fundingRateTimestamp": "1790582400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00001136",
          "fundingRateTimestamp": "1790553600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00001756",
          "fundingRateTimestamp": "1790524800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00009881",
          "fundingRateTimestamp": "1790496000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003438",
          "fundingRateTimestamp": "1790467200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003168",
          "fundingRateTimestamp": "1790438400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002583",
          "fundingRateTimestamp": "1790409600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00000164",
          "fundingRateTimestamp": "1790380800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00000343",
          "fundingRateTimestamp": "1790352000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002709",
          "fundingRateTimestamp": "1790323200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00000592",
          "fundingRateTimestamp": "1790294400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003632",
          "fundingRateTimestamp": "1790265600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000582",
          "fundingRateTimestamp": "1790236800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000445",
          "fundingRateTimestamp": "1790208000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00000224",
          "fundingRateTimestamp": "1790179200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002247",
          "fundingRateTimestamp": "1790150400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00007951",
          "fundingRateTimestamp": "1790121600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00005873",
          "fundingRateTimestamp": "1790092800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002473",
          "fundingRateTimestamp": "1790064000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008628",
          "fundingRateTimestamp": "1790035200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790006400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008796",
          "fundingRateTimestamp": "1789977600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008055",
          "fundingRateTimestamp": "1789948800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003891",
          "fundingRateTimestamp": "1789920000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00001739",
          "fundingRateTimestamp": "1789891200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008181",
          "fundingRateTimestamp": "1789862400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789833600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789804800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789776000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789747200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789718400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002413",
          "fundingRateTimestamp": "1789689600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002798",
          "fundingRateTimestamp": "1789660800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003757",
          "fundingRateTimestamp": "1789632000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000467",
          "fundingRateTimestamp": "1789603200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.000026",
          "fundingRateTimestamp": "1789574400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00005202",
          "fundingRateTimestamp": "1789545600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00004679",
          "fundingRateTimestamp": "1789516800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00006029",
          "fundingRateTimestamp": "1789488000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00006352",
          "fundingRateTimestamp": "1789459200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00002704",
          "fundingRateTimestamp": "1789430400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00003932",
          "fundingRateTimestamp": "1789401600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00008234",
          "fundingRateTimestamp": "1789372800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004039",
          "fundingRateTimestamp": "1789344000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000068",
          "fundingRateTimestamp": "1789315200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000615",
          "fundingRateTimestamp": "1789286400000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.00004029",
          "fundingRateTimestamp": "1789257600000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0000691",
          "fundingRateTimestamp": "1789228800000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00000394",
          "fundingRateTimestamp": "1789200000000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "-0.00002407",
          "fundingRateTimestamp": "1789171200000"
        },
        {
          "symbol": "ETHUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789142400000"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721538548
  },
  "weex_history": [
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005145",
      "fundingTime": 1789142400000,
      "markPrice": "2558.61"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-1.5E-7",
      "fundingTime": 1789171200000,
      "markPrice": "2515.46"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00000597",
      "fundingTime": 1789200000000,
      "markPrice": "2522.98"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005121",
      "fundingTime": 1789228800000,
      "markPrice": "2533.99"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004575",
      "fundingTime": 1789257600000,
      "markPrice": "2524.79"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005809",
      "fundingTime": 1789286400000,
      "markPrice": "2516.7"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00004585",
      "fundingTime": 1789315200000,
      "markPrice": "2489.55"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005268",
      "fundingTime": 1789344000000,
      "markPrice": "2475.66"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00007700",
      "fundingTime": 1789372800000,
      "markPrice": "2522.05"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003690",
      "fundingTime": 1789401600000,
      "markPrice": "2507.27"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00001285",
      "fundingTime": 1789430400000,
      "markPrice": "2514.54"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00008220",
      "fundingTime": 1789459200000,
      "markPrice": "2472.83"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00004784",
      "fundingTime": 1789488000000,
      "markPrice": "2423.27"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00000294",
      "fundingTime": 1789516800000,
      "markPrice": "2397.14"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00003887",
      "fundingTime": 1789545600000,
      "markPrice": "2395.66"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00002098",
      "fundingTime": 1789574400000,
      "markPrice": "2391.63"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003305",
      "fundingTime": 1789603200000,
      "markPrice": "2417.48"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003109",
      "fundingTime": 1789632000000,
      "markPrice": "2443.39"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005107",
      "fundingTime": 1789660800000,
      "markPrice": "2469.44"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003705",
      "fundingTime": 1789689600000,
      "markPrice": "2446.31"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00007768",
      "fundingTime": 1789718400000,
      "markPrice": "2488.98"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789747200000,
      "markPrice": "2583.29"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789776000000,
      "markPrice": "2611.13"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789804800000,
      "markPrice": "2626.22"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005468",
      "fundingTime": 1789833600000,
      "markPrice": "2639.99"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789862400000,
      "markPrice": "2631.58"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004128",
      "fundingTime": 1789891200000,
      "markPrice": "2575.51"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003421",
      "fundingTime": 1789920000000,
      "markPrice": "2611.82"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00008166",
      "fundingTime": 1789948800000,
      "markPrice": "2643.73"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00008660",
      "fundingTime": 1789977600000,
      "markPrice": "2660.77"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00009022",
      "fundingTime": 1790006400000,
      "markPrice": "2753.99"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005621",
      "fundingTime": 1790035200000,
      "markPrice": "2774.69"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00009329",
      "fundingTime": 1790064000000,
      "markPrice": "2725.47"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005831",
      "fundingTime": 1790092800000,
      "markPrice": "2742.87"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00009373",
      "fundingTime": 1790121600000,
      "markPrice": "2752.67"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004572",
      "fundingTime": 1790150400000,
      "markPrice": "2741.97"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004502",
      "fundingTime": 1790179200000,
      "markPrice": "2655.18"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005253",
      "fundingTime": 1790208000000,
      "markPrice": "2683.52"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005204",
      "fundingTime": 1790236800000,
      "markPrice": "2692.03"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00006485",
      "fundingTime": 1790265600000,
      "markPrice": "2682.26"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00002794",
      "fundingTime": 1790294400000,
      "markPrice": "2686.64"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003742",
      "fundingTime": 1790323200000,
      "markPrice": "2671.17"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004911",
      "fundingTime": 1790352000000,
      "markPrice": "2685.69"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00006567",
      "fundingTime": 1790380800000,
      "markPrice": "2690.55"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00006745",
      "fundingTime": 1790409600000,
      "markPrice": "2689.75"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005746",
      "fundingTime": 1790438400000,
      "markPrice": "2691.98"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005671",
      "fundingTime": 1790467200000,
      "markPrice": "2694.98"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790496000000,
      "markPrice": "2717.01"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005379",
      "fundingTime": 1790524800000,
      "markPrice": "2688.83"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003117",
      "fundingTime": 1790553600000,
      "markPrice": "2687.34"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00003010",
      "fundingTime": 1790582400000,
      "markPrice": "2642.76"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005932",
      "fundingTime": 1790611200000,
      "markPrice": "2677.39"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00007036",
      "fundingTime": 1790640000000,
      "markPrice": "2687.58"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790668800000,
      "markPrice": "2711.48"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004221",
      "fundingTime": 1790697600000,
      "markPrice": "2672.82"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00006641",
      "fundingTime": 1790726400000,
      "markPrice": "2676.93"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005479",
      "fundingTime": 1790755200000,
      "markPrice": "2673.52"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003581",
      "fundingTime": 1790784000000,
      "markPrice": "2682.29"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005749",
      "fundingTime": 1790812800000,
      "markPrice": "2684.69"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00007304",
      "fundingTime": 1790841600000,
      "markPrice": "2675.96"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003565",
      "fundingTime": 1790870400000,
      "markPrice": "2681.18"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00004805",
      "fundingTime": 1790899200000,
      "markPrice": "2705.04"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790928000000,
      "markPrice": "2736.91"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00001715",
      "fundingTime": 1790956800000,
      "markPrice": "2695.92"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00001518",
      "fundingTime": 1790985600000,
      "markPrice": "2667.28"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00000116",
      "fundingTime": 1791014400000,
      "markPrice": "2680.34"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00001830",
      "fundingTime": 1791043200000,
      "markPrice": "2680.44"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003800",
      "fundingTime": 1791072000000,
      "markPrice": "2686.01"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005399",
      "fundingTime": 1791100800000,
      "markPrice": "2705.29"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00003105",
      "fundingTime": 1791129600000,
      "markPrice": "2697.51"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00009785",
      "fundingTime": 1791158400000,
      "markPrice": "2725.86"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00006919",
      "fundingTime": 1791187200000,
      "markPrice": "2725.29"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00002986",
      "fundingTime": 1791216000000,
      "markPrice": "2695.95"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00001605",
      "fundingTime": 1791244800000,
      "markPrice": "2708.69"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00002130",
      "fundingTime": 1791273600000,
      "markPrice": "2706.46"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005701",
      "fundingTime": 1791302400000,
      "markPrice": "2700.6"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00009314",
      "fundingTime": 1791331200000,
      "markPrice": "2696.44"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00003188",
      "fundingTime": 1791360000000,
      "markPrice": "2614.76"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00003411",
      "fundingTime": 1791388800000,
      "markPrice": "2569.69"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00003321",
      "fundingTime": 1791417600000,
      "markPrice": "2572.89"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00000582",
      "fundingTime": 1791446400000,
      "markPrice": "2566.83"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00002806",
      "fundingTime": 1791475200000,
      "markPrice": "2434.14"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00001539",
      "fundingTime": 1791504000000,
      "markPrice": "2474"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00001127",
      "fundingTime": 1791532800000,
      "markPrice": "2503.28"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00001498",
      "fundingTime": 1791561600000,
      "markPrice": "2487.77"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00005620",
      "fundingTime": 1791590400000,
      "markPrice": "2486.48"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00000532",
      "fundingTime": 1791619200000,
      "markPrice": "2494.11"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "0.00002995",
      "fundingTime": 1791648000000,
      "markPrice": "2510.87"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00011729",
      "fundingTime": 1791676800000,
      "markPrice": "2504.89"
    },
    {
      "symbol": "ETHUSDT",
      "fundingRate": "-0.00011662",
      "fundingTime": 1791705600000,
      "markPrice": "2499.53"
    }
  ]
}
```

</details>


<details>
<summary>funding_raw/SOLUSDT.json</summary>

SHA256 UTF-8/LF: `78d0c6882970c5726a2866d0ebcf0ef0973e658eea162ee7124ffaf13e95154d`

```json
{
  "weex_current": [
    {
      "symbol": "SOLUSDT",
      "markPrice": "109.61",
      "indexPrice": "109.65584",
      "forecastFundingRate": "0.00004961",
      "lastFundingRate": "0.00005878",
      "interestRate": "0.0003",
      "nextFundingTime": 1791734400000,
      "time": 1791721540270,
      "collectCycle": 480
    }
  ],
  "weex_book": [
    {
      "symbol": "SOLUSDT",
      "bidPrice": "109.53",
      "bidQty": "964.0",
      "askPrice": "109.54",
      "askQty": "1020.4",
      "time": 1791721540520
    }
  ],
  "bybit_current": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "SOLUSDT",
          "lastPrice": "109.540",
          "indexPrice": "109.596",
          "markPrice": "109.550",
          "prevPrice24h": "109.560",
          "price24hPcnt": "-0.000182",
          "highPrice24h": "110.730",
          "lowPrice24h": "108.880",
          "prevPrice1h": "109.380",
          "openInterest": "6383583",
          "openInterestValue": "699321517.65",
          "singleOpenInterest": "3191791.5",
          "singleOpenInterestValue": "349660758.83",
          "turnover24h": "208852451.4950",
          "volume24h": "1900537.2000",
          "fundingRate": "-0.00000898",
          "nextFundingTime": "1791734400000",
          "predictedDeliveryPrice": "",
          "basisRate": "",
          "deliveryFeeRate": "",
          "deliveryTime": "0",
          "ask1Size": "856.3",
          "bid1Price": "109.540",
          "ask1Price": "109.550",
          "bid1Size": "1064.0",
          "basis": "",
          "preOpenPrice": "",
          "preQty": "",
          "curPreListingPhase": "",
          "fundingIntervalHour": "8",
          "basisRateYear": "",
          "fundingCap": "0.005"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721540808
  },
  "bybit_instrument": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "SOLUSDT",
          "contractType": "LinearPerpetual",
          "status": "Trading",
          "baseCoin": "SOL",
          "quoteCoin": "USDT",
          "launchTime": "1634256000000",
          "deliveryTime": "0",
          "deliveryFeeRate": "",
          "priceScale": "3",
          "leverageFilter": {
            "minLeverage": "1",
            "maxLeverage": "100.00",
            "leverageStep": "0.01"
          },
          "priceFilter": {
            "minPrice": "0.010",
            "maxPrice": "199999.980",
            "tickSize": "0.010"
          },
          "lotSizeFilter": {
            "maxOrderQty": "96000.0",
            "minOrderQty": "0.1",
            "qtyStep": "0.1",
            "postOnlyMaxOrderQty": "96000.0",
            "maxMktOrderQty": "12000.0",
            "minNotionalValue": "5"
          },
          "unifiedMarginTrade": true,
          "fundingInterval": 480,
          "settleCoin": "USDT",
          "copyTrading": "both",
          "upperFundingRate": "0.005",
          "lowerFundingRate": "-0.005",
          "isPreListing": false,
          "preListingInfo": null,
          "riskParameters": {
            "priceLimitRatioX": "0.05",
            "priceLimitRatioY": "0.1"
          },
          "displayName": "SOLUSDT",
          "symbolType": "",
          "forbidUplWithdrawal": false,
          "symbolId": 38,
          "fullName": "Solana",
          "marketRegion": "",
          "underlyingTicker": "",
          "tags": []
        }
      ],
      "nextPageCursor": ""
    },
    "retExtInfo": {},
    "time": 1791721541024
  },
  "bybit_history": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0000448",
          "fundingRateTimestamp": "1791705600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00004401",
          "fundingRateTimestamp": "1791676800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0000007",
          "fundingRateTimestamp": "1791648000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.0000183",
          "fundingRateTimestamp": "1791619200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00001824",
          "fundingRateTimestamp": "1791590400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00001062",
          "fundingRateTimestamp": "1791561600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00004624",
          "fundingRateTimestamp": "1791532800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00008259",
          "fundingRateTimestamp": "1791504000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00001895",
          "fundingRateTimestamp": "1791475200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00004143",
          "fundingRateTimestamp": "1791446400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003557",
          "fundingRateTimestamp": "1791417600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00001901",
          "fundingRateTimestamp": "1791388800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.000013",
          "fundingRateTimestamp": "1791360000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791331200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00009366",
          "fundingRateTimestamp": "1791302400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00002002",
          "fundingRateTimestamp": "1791273600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00000302",
          "fundingRateTimestamp": "1791244800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00005975",
          "fundingRateTimestamp": "1791216000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00000867",
          "fundingRateTimestamp": "1791187200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791158400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791129600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791100800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00002207",
          "fundingRateTimestamp": "1791072000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00004402",
          "fundingRateTimestamp": "1791043200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003068",
          "fundingRateTimestamp": "1791014400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00017707",
          "fundingRateTimestamp": "1790985600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00008301",
          "fundingRateTimestamp": "1790956800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790928000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00000707",
          "fundingRateTimestamp": "1790899200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00009094",
          "fundingRateTimestamp": "1790870400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00000831",
          "fundingRateTimestamp": "1790841600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.0000917",
          "fundingRateTimestamp": "1790812800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00004461",
          "fundingRateTimestamp": "1790784000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00008565",
          "fundingRateTimestamp": "1790755200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00000705",
          "fundingRateTimestamp": "1790726400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790697600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00007688",
          "fundingRateTimestamp": "1790668800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003886",
          "fundingRateTimestamp": "1790640000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00007114",
          "fundingRateTimestamp": "1790611200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00008247",
          "fundingRateTimestamp": "1790582400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00006338",
          "fundingRateTimestamp": "1790553600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790524800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790496000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790467200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790438400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790409600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790380800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790352000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.0000047",
          "fundingRateTimestamp": "1790323200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00010564",
          "fundingRateTimestamp": "1790294400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00005264",
          "fundingRateTimestamp": "1790265600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00006839",
          "fundingRateTimestamp": "1790236800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00000519",
          "fundingRateTimestamp": "1790208000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.0000287",
          "fundingRateTimestamp": "1790179200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003254",
          "fundingRateTimestamp": "1790150400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00001861",
          "fundingRateTimestamp": "1790121600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00007045",
          "fundingRateTimestamp": "1790092800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00009131",
          "fundingRateTimestamp": "1790064000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790035200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790006400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789977600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789948800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00002275",
          "fundingRateTimestamp": "1789920000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789891200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789862400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789833600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789804800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789776000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789747200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789718400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789689600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00001141",
          "fundingRateTimestamp": "1789660800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00001177",
          "fundingRateTimestamp": "1789632000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003058",
          "fundingRateTimestamp": "1789603200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00000036",
          "fundingRateTimestamp": "1789574400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00005691",
          "fundingRateTimestamp": "1789545600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00009081",
          "fundingRateTimestamp": "1789516800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00005732",
          "fundingRateTimestamp": "1789488000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00000827",
          "fundingRateTimestamp": "1789459200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00005691",
          "fundingRateTimestamp": "1789430400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003009",
          "fundingRateTimestamp": "1789401600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00002768",
          "fundingRateTimestamp": "1789372800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00003363",
          "fundingRateTimestamp": "1789344000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "-0.00001358",
          "fundingRateTimestamp": "1789315200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003708",
          "fundingRateTimestamp": "1789286400000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003845",
          "fundingRateTimestamp": "1789257600000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00003168",
          "fundingRateTimestamp": "1789228800000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00005115",
          "fundingRateTimestamp": "1789200000000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.0000606",
          "fundingRateTimestamp": "1789171200000"
        },
        {
          "symbol": "SOLUSDT",
          "fundingRate": "0.00004253",
          "fundingRateTimestamp": "1789142400000"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721541241
  },
  "weex_history": [
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00004174",
      "fundingTime": 1789142400000,
      "markPrice": "101.54"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00005103",
      "fundingTime": 1789171200000,
      "markPrice": "102.4"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00004414",
      "fundingTime": 1789200000000,
      "markPrice": "101.61"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001500",
      "fundingTime": 1789228800000,
      "markPrice": "102.01"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002207",
      "fundingTime": 1789257600000,
      "markPrice": "101.7"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00001400",
      "fundingTime": 1789286400000,
      "markPrice": "100.66"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00001112",
      "fundingTime": 1789315200000,
      "markPrice": "100.2"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00000938",
      "fundingTime": 1789344000000,
      "markPrice": "99.24"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00008143",
      "fundingTime": 1789372800000,
      "markPrice": "101.56"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789401600000,
      "markPrice": "101.92"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789430400000,
      "markPrice": "102.5"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00006354",
      "fundingTime": 1789459200000,
      "markPrice": "100.39"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00003989",
      "fundingTime": 1789488000000,
      "markPrice": "99.31"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00002992",
      "fundingTime": 1789516800000,
      "markPrice": "96.83"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00000113",
      "fundingTime": 1789545600000,
      "markPrice": "96.91"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003293",
      "fundingTime": 1789574400000,
      "markPrice": "97.05"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003552",
      "fundingTime": 1789603200000,
      "markPrice": "98.61"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00000905",
      "fundingTime": 1789632000000,
      "markPrice": "99.99"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00008756",
      "fundingTime": 1789660800000,
      "markPrice": "101.25"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789689600000,
      "markPrice": "101.6"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789718400000,
      "markPrice": "105.74"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789747200000,
      "markPrice": "111.13"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789776000000,
      "markPrice": "112.72"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789804800000,
      "markPrice": "111.59"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789833600000,
      "markPrice": "111.61"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789862400000,
      "markPrice": "111"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789891200000,
      "markPrice": "108.43"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789920000000,
      "markPrice": "108.73"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00009171",
      "fundingTime": 1789948800000,
      "markPrice": "111.09"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789977600000,
      "markPrice": "112.08"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790006400000,
      "markPrice": "117.88"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790035200000,
      "markPrice": "118.86"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790064000000,
      "markPrice": "116.26"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00000323",
      "fundingTime": 1790092800000,
      "markPrice": "117.3"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00007908",
      "fundingTime": 1790121600000,
      "markPrice": "118.49"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00004335",
      "fundingTime": 1790150400000,
      "markPrice": "117.82"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00006733",
      "fundingTime": 1790179200000,
      "markPrice": "113.81"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001138",
      "fundingTime": 1790208000000,
      "markPrice": "114.94"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001530",
      "fundingTime": 1790236800000,
      "markPrice": "115.46"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00004885",
      "fundingTime": 1790265600000,
      "markPrice": "116.25"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00004103",
      "fundingTime": 1790294400000,
      "markPrice": "116.99"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790323200000,
      "markPrice": "116.33"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790352000000,
      "markPrice": "120.05"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003047",
      "fundingTime": 1790380800000,
      "markPrice": "122.09"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00004157",
      "fundingTime": 1790409600000,
      "markPrice": "120.69"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00007338",
      "fundingTime": 1790438400000,
      "markPrice": "121.82"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001461",
      "fundingTime": 1790467200000,
      "markPrice": "121.34"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00006615",
      "fundingTime": 1790496000000,
      "markPrice": "124.04"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00002971",
      "fundingTime": 1790524800000,
      "markPrice": "121.68"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00001692",
      "fundingTime": 1790553600000,
      "markPrice": "121.93"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003312",
      "fundingTime": 1790582400000,
      "markPrice": "117.98"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00004114",
      "fundingTime": 1790611200000,
      "markPrice": "118.67"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001277",
      "fundingTime": 1790640000000,
      "markPrice": "118.82"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00004841",
      "fundingTime": 1790668800000,
      "markPrice": "119.48"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00002598",
      "fundingTime": 1790697600000,
      "markPrice": "118.15"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002543",
      "fundingTime": 1790726400000,
      "markPrice": "119.08"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00000891",
      "fundingTime": 1790755200000,
      "markPrice": "118.41"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00000179",
      "fundingTime": 1790784000000,
      "markPrice": "119.23"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00008014",
      "fundingTime": 1790812800000,
      "markPrice": "118.04"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002083",
      "fundingTime": 1790841600000,
      "markPrice": "117.41"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00002297",
      "fundingTime": 1790870400000,
      "markPrice": "117.3"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003880",
      "fundingTime": 1790899200000,
      "markPrice": "118.35"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790928000000,
      "markPrice": "121.69"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790956800000,
      "markPrice": "119.92"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00006089",
      "fundingTime": 1790985600000,
      "markPrice": "118.56"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003604",
      "fundingTime": 1791014400000,
      "markPrice": "119.28"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00000696",
      "fundingTime": 1791043200000,
      "markPrice": "119.64"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001890",
      "fundingTime": 1791072000000,
      "markPrice": "119.54"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791100800000,
      "markPrice": "121.09"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791129600000,
      "markPrice": "121.52"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791158400000,
      "markPrice": "121.54"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001333",
      "fundingTime": 1791187200000,
      "markPrice": "121.64"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00001707",
      "fundingTime": 1791216000000,
      "markPrice": "119.27"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001156",
      "fundingTime": 1791244800000,
      "markPrice": "120.72"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00003861",
      "fundingTime": 1791273600000,
      "markPrice": "120.17"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791302400000,
      "markPrice": "120.47"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791331200000,
      "markPrice": "120.65"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00013640",
      "fundingTime": 1791360000000,
      "markPrice": "118.56"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003115",
      "fundingTime": 1791388800000,
      "markPrice": "116.71"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00000224",
      "fundingTime": 1791417600000,
      "markPrice": "116.23"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002150",
      "fundingTime": 1791446400000,
      "markPrice": "114.89"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002597",
      "fundingTime": 1791475200000,
      "markPrice": "108.51"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "-0.00013939",
      "fundingTime": 1791504000000,
      "markPrice": "109.56"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002584",
      "fundingTime": 1791532800000,
      "markPrice": "110.63"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001827",
      "fundingTime": 1791561600000,
      "markPrice": "109.65"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00007997",
      "fundingTime": 1791590400000,
      "markPrice": "109.07"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00002552",
      "fundingTime": 1791619200000,
      "markPrice": "109.88"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00003325",
      "fundingTime": 1791648000000,
      "markPrice": "110.41"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00001487",
      "fundingTime": 1791676800000,
      "markPrice": "110.03"
    },
    {
      "symbol": "SOLUSDT",
      "fundingRate": "0.00005878",
      "fundingTime": 1791705600000,
      "markPrice": "109.33"
    }
  ]
}
```

</details>


<details>
<summary>funding_raw/XRPUSDT.json</summary>

SHA256 UTF-8/LF: `5a1814bd3595db88b92751caf480cff184858f42061aad0740a5847f2b7a3447`

```json
{
  "weex_current": [
    {
      "symbol": "XRPUSDT",
      "markPrice": "1.3942",
      "indexPrice": "1.3948975",
      "forecastFundingRate": "0.00006238",
      "lastFundingRate": "0.00002920",
      "interestRate": "0.0003",
      "nextFundingTime": 1791734400000,
      "time": 1791721537405,
      "collectCycle": 480
    }
  ],
  "weex_book": [
    {
      "symbol": "XRPUSDT",
      "bidPrice": "1.3935",
      "bidQty": "63760",
      "askPrice": "1.3936",
      "askQty": "67260",
      "time": 1791721537570
    }
  ],
  "bybit_current": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "XRPUSDT",
          "lastPrice": "1.3935",
          "indexPrice": "1.3944",
          "markPrice": "1.3935",
          "prevPrice24h": "1.4019",
          "price24hPcnt": "-0.005991",
          "highPrice24h": "1.4114",
          "lowPrice24h": "1.3860",
          "prevPrice1h": "1.3903",
          "openInterest": "203187393.7",
          "openInterestValue": "283141633.12",
          "singleOpenInterest": "101593696.9",
          "singleOpenInterestValue": "141570816.63",
          "turnover24h": "114151872.5652",
          "volume24h": "81636495.1000",
          "fundingRate": "0.00002805",
          "nextFundingTime": "1791734400000",
          "predictedDeliveryPrice": "",
          "basisRate": "",
          "deliveryFeeRate": "",
          "deliveryTime": "0",
          "ask1Size": "30025.8",
          "bid1Price": "1.3934",
          "ask1Price": "1.3935",
          "bid1Size": "8172.2",
          "basis": "",
          "preOpenPrice": "",
          "preQty": "",
          "curPreListingPhase": "",
          "fundingIntervalHour": "8",
          "basisRateYear": "",
          "fundingCap": "0.005"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721537942
  },
  "bybit_instrument": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "XRPUSDT",
          "contractType": "LinearPerpetual",
          "status": "Trading",
          "baseCoin": "XRP",
          "quoteCoin": "USDT",
          "launchTime": "1620898440000",
          "deliveryTime": "0",
          "deliveryFeeRate": "",
          "priceScale": "4",
          "leverageFilter": {
            "minLeverage": "1",
            "maxLeverage": "100.00",
            "leverageStep": "0.01"
          },
          "priceFilter": {
            "minPrice": "0.0001",
            "maxPrice": "1999.9998",
            "tickSize": "0.0001"
          },
          "lotSizeFilter": {
            "maxOrderQty": "7500000.0",
            "minOrderQty": "0.1",
            "qtyStep": "0.1",
            "postOnlyMaxOrderQty": "7500000.0",
            "maxMktOrderQty": "1500000.0",
            "minNotionalValue": "5"
          },
          "unifiedMarginTrade": true,
          "fundingInterval": 480,
          "settleCoin": "USDT",
          "copyTrading": "both",
          "upperFundingRate": "0.005",
          "lowerFundingRate": "-0.005",
          "isPreListing": false,
          "preListingInfo": null,
          "riskParameters": {
            "priceLimitRatioX": "0.05",
            "priceLimitRatioY": "0.1"
          },
          "displayName": "XRPUSDT",
          "symbolType": "",
          "forbidUplWithdrawal": false,
          "symbolId": 8,
          "fullName": "XRP",
          "marketRegion": "",
          "underlyingTicker": "",
          "tags": []
        }
      ],
      "nextPageCursor": ""
    },
    "retExtInfo": {},
    "time": 1791721538273
  },
  "bybit_history": {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
      "category": "linear",
      "list": [
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00003861",
          "fundingRateTimestamp": "1791705600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00000289",
          "fundingRateTimestamp": "1791676800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00001916",
          "fundingRateTimestamp": "1791648000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002486",
          "fundingRateTimestamp": "1791619200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00002919",
          "fundingRateTimestamp": "1791590400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00001599",
          "fundingRateTimestamp": "1791561600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00006677",
          "fundingRateTimestamp": "1791532800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00011236",
          "fundingRateTimestamp": "1791504000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00000935",
          "fundingRateTimestamp": "1791475200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00002645",
          "fundingRateTimestamp": "1791446400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00000398",
          "fundingRateTimestamp": "1791417600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002721",
          "fundingRateTimestamp": "1791388800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00002031",
          "fundingRateTimestamp": "1791360000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00001229",
          "fundingRateTimestamp": "1791331200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791302400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002546",
          "fundingRateTimestamp": "1791273600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791244800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00006171",
          "fundingRateTimestamp": "1791216000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791187200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791158400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791129600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1791100800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00005997",
          "fundingRateTimestamp": "1791072000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00008662",
          "fundingRateTimestamp": "1791043200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00002471",
          "fundingRateTimestamp": "1791014400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00008766",
          "fundingRateTimestamp": "1790985600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790956800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790928000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790899200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002099",
          "fundingRateTimestamp": "1790870400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00003353",
          "fundingRateTimestamp": "1790841600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00001392",
          "fundingRateTimestamp": "1790812800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790784000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00005589",
          "fundingRateTimestamp": "1790755200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00004193",
          "fundingRateTimestamp": "1790726400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790697600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790668800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00005446",
          "fundingRateTimestamp": "1790640000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002559",
          "fundingRateTimestamp": "1790611200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00006234",
          "fundingRateTimestamp": "1790582400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0000824",
          "fundingRateTimestamp": "1790553600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00002237",
          "fundingRateTimestamp": "1790524800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00001572",
          "fundingRateTimestamp": "1790496000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00006697",
          "fundingRateTimestamp": "1790467200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00006064",
          "fundingRateTimestamp": "1790438400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0000263",
          "fundingRateTimestamp": "1790409600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790380800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00003164",
          "fundingRateTimestamp": "1790352000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790323200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00000525",
          "fundingRateTimestamp": "1790294400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00000833",
          "fundingRateTimestamp": "1790265600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002762",
          "fundingRateTimestamp": "1790236800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00004647",
          "fundingRateTimestamp": "1790208000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790179200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790150400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790121600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790092800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790064000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790035200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1790006400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789977600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789948800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00003651",
          "fundingRateTimestamp": "1789920000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789891200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789862400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789833600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789804800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789776000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789747200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00007194",
          "fundingRateTimestamp": "1789718400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002618",
          "fundingRateTimestamp": "1789689600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00000209",
          "fundingRateTimestamp": "1789660800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00000918",
          "fundingRateTimestamp": "1789632000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00001098",
          "fundingRateTimestamp": "1789603200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00000402",
          "fundingRateTimestamp": "1789574400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00002572",
          "fundingRateTimestamp": "1789545600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00000895",
          "fundingRateTimestamp": "1789516800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00007581",
          "fundingRateTimestamp": "1789488000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0000868",
          "fundingRateTimestamp": "1789459200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789430400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0001",
          "fundingRateTimestamp": "1789401600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00004356",
          "fundingRateTimestamp": "1789372800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00000217",
          "fundingRateTimestamp": "1789344000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00012654",
          "fundingRateTimestamp": "1789315200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.0000329",
          "fundingRateTimestamp": "1789286400000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00001911",
          "fundingRateTimestamp": "1789257600000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00006125",
          "fundingRateTimestamp": "1789228800000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "-0.00004117",
          "fundingRateTimestamp": "1789200000000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00003964",
          "fundingRateTimestamp": "1789171200000"
        },
        {
          "symbol": "XRPUSDT",
          "fundingRate": "0.00003352",
          "fundingRateTimestamp": "1789142400000"
        }
      ]
    },
    "retExtInfo": {},
    "time": 1791721538500
  },
  "weex_history": [
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00006109",
      "fundingTime": 1789142400000,
      "markPrice": "1.3738"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00003259",
      "fundingTime": 1789171200000,
      "markPrice": "1.3557"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00003566",
      "fundingTime": 1789200000000,
      "markPrice": "1.3685"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00006877",
      "fundingTime": 1789228800000,
      "markPrice": "1.3718"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00000123",
      "fundingTime": 1789257600000,
      "markPrice": "1.3657"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00001661",
      "fundingTime": 1789286400000,
      "markPrice": "1.357"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00008374",
      "fundingTime": 1789315200000,
      "markPrice": "1.3427"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00005053",
      "fundingTime": 1789344000000,
      "markPrice": "1.3402"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789372800000,
      "markPrice": "1.3899"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00007549",
      "fundingTime": 1789401600000,
      "markPrice": "1.4026"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789430400000,
      "markPrice": "1.423"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00004364",
      "fundingTime": 1789459200000,
      "markPrice": "1.3934"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00001978",
      "fundingTime": 1789488000000,
      "markPrice": "1.3888"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00006237",
      "fundingTime": 1789516800000,
      "markPrice": "1.2825"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00000558",
      "fundingTime": 1789545600000,
      "markPrice": "1.2846"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00002679",
      "fundingTime": 1789574400000,
      "markPrice": "1.2656"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00004867",
      "fundingTime": 1789603200000,
      "markPrice": "1.2987"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00000895",
      "fundingTime": 1789632000000,
      "markPrice": "1.3014"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00000365",
      "fundingTime": 1789660800000,
      "markPrice": "1.3072"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00007370",
      "fundingTime": 1789689600000,
      "markPrice": "1.2954"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00009371",
      "fundingTime": 1789718400000,
      "markPrice": "1.3282"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789747200000,
      "markPrice": "1.3848"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789776000000,
      "markPrice": "1.3963"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789804800000,
      "markPrice": "1.4103"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789833600000,
      "markPrice": "1.4304"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789862400000,
      "markPrice": "1.4102"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789891200000,
      "markPrice": "1.3791"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00001324",
      "fundingTime": 1789920000000,
      "markPrice": "1.3902"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789948800000,
      "markPrice": "1.4098"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1789977600000,
      "markPrice": "1.4383"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790006400000,
      "markPrice": "1.495"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790035200000,
      "markPrice": "1.5361"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790064000000,
      "markPrice": "1.5181"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790092800000,
      "markPrice": "1.5715"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790121600000,
      "markPrice": "1.5718"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790150400000,
      "markPrice": "1.6157"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00008418",
      "fundingTime": 1790179200000,
      "markPrice": "1.5058"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00004906",
      "fundingTime": 1790208000000,
      "markPrice": "1.5001"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "9.1E-7",
      "fundingTime": 1790236800000,
      "markPrice": "1.5057"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00001725",
      "fundingTime": 1790265600000,
      "markPrice": "1.5141"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00002083",
      "fundingTime": 1790294400000,
      "markPrice": "1.5339"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790323200000,
      "markPrice": "1.5339"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00001078",
      "fundingTime": 1790352000000,
      "markPrice": "1.5756"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790380800000,
      "markPrice": "1.5677"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00009638",
      "fundingTime": 1790409600000,
      "markPrice": "1.5517"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00006843",
      "fundingTime": 1790438400000,
      "markPrice": "1.5519"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00000246",
      "fundingTime": 1790467200000,
      "markPrice": "1.5264"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00009732",
      "fundingTime": 1790496000000,
      "markPrice": "1.5379"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00001441",
      "fundingTime": 1790524800000,
      "markPrice": "1.5158"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00002518",
      "fundingTime": 1790553600000,
      "markPrice": "1.5159"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00008015",
      "fundingTime": 1790582400000,
      "markPrice": "1.4706"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00003054",
      "fundingTime": 1790611200000,
      "markPrice": "1.4945"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00005365",
      "fundingTime": 1790640000000,
      "markPrice": "1.4961"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00008716",
      "fundingTime": 1790668800000,
      "markPrice": "1.5073"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00007476",
      "fundingTime": 1790697600000,
      "markPrice": "1.5174"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00002152",
      "fundingTime": 1790726400000,
      "markPrice": "1.4899"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00000465",
      "fundingTime": 1790755200000,
      "markPrice": "1.4997"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00008533",
      "fundingTime": 1790784000000,
      "markPrice": "1.5046"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00000653",
      "fundingTime": 1790812800000,
      "markPrice": "1.4892"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00006364",
      "fundingTime": 1790841600000,
      "markPrice": "1.4859"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00002606",
      "fundingTime": 1790870400000,
      "markPrice": "1.4866"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790899200000,
      "markPrice": "1.4937"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790928000000,
      "markPrice": "1.5314"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1790956800000,
      "markPrice": "1.5063"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00009363",
      "fundingTime": 1790985600000,
      "markPrice": "1.4839"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00003780",
      "fundingTime": 1791014400000,
      "markPrice": "1.4814"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00001132",
      "fundingTime": 1791043200000,
      "markPrice": "1.4893"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00003391",
      "fundingTime": 1791072000000,
      "markPrice": "1.4855"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00004207",
      "fundingTime": 1791100800000,
      "markPrice": "1.4984"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791129600000,
      "markPrice": "1.5042"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791158400000,
      "markPrice": "1.5201"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791187200000,
      "markPrice": "1.5217"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791216000000,
      "markPrice": "1.4919"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00006319",
      "fundingTime": 1791244800000,
      "markPrice": "1.5071"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00002525",
      "fundingTime": 1791273600000,
      "markPrice": "1.4994"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00010000",
      "fundingTime": 1791302400000,
      "markPrice": "1.5021"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00001101",
      "fundingTime": 1791331200000,
      "markPrice": "1.496"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00005838",
      "fundingTime": 1791360000000,
      "markPrice": "1.4712"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00001043",
      "fundingTime": 1791388800000,
      "markPrice": "1.4338"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00006455",
      "fundingTime": 1791417600000,
      "markPrice": "1.4204"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00000814",
      "fundingTime": 1791446400000,
      "markPrice": "1.4068"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00001701",
      "fundingTime": 1791475200000,
      "markPrice": "1.3456"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00016753",
      "fundingTime": 1791504000000,
      "markPrice": "1.3795"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00006295",
      "fundingTime": 1791532800000,
      "markPrice": "1.4033"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00005731",
      "fundingTime": 1791561600000,
      "markPrice": "1.3817"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00001086",
      "fundingTime": 1791590400000,
      "markPrice": "1.3949"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00001883",
      "fundingTime": 1791619200000,
      "markPrice": "1.4059"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00003817",
      "fundingTime": 1791648000000,
      "markPrice": "1.4076"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "-0.00000465",
      "fundingTime": 1791676800000,
      "markPrice": "1.4015"
    },
    {
      "symbol": "XRPUSDT",
      "fundingRate": "0.00002920",
      "fundingTime": 1791705600000,
      "markPrice": "1.3922"
    }
  ]
}
```

</details>


<details>
<summary>Предыдущий source carry/REPORT.md</summary>

# Spot–perpetual carry: реальные парные цены и фандинг

Дата: 06.10.2026. Данные Binance spot + Binance USD-M; результат не переносится автоматически на OKX или WEEX.

## Правило, замороженное до расчёта

Один альтернативный портфель $2700 на BTC либо ETH. На каждом квартальном входе $1350 выделяется на спот, включая комиссию; perpetual продаётся в точно таком же количестве монет. Остаток держится денежным резервом. Входы в 01:00 UTC, вне стандартного расчёта фандинга. Обе ноги закрываются на следующей границе; последняя открытая позиция ликвидируется в конце данных. Прибыль остаётся в денежном резерве, но не увеличивает фиксированный бюджет следующей покупки. Полугодовой срок — заранее заданный соседний вариант.

Цены обеих ног реальные, синхронизированные 1h OHLC. Комиссия спота принята 0.10% за сторону, perpetual 0.05%; неблагоприятное проскальзывание 0.02% на каждое исполнение. Это четыре исполнения пакета, а не один круг 0.10%. Фандинг рассчитан по настоящим fundingTime, fundingRate и markPrice, с корректным знаком для шорта. Числа комиссий требуют проверки тарифа конкретного аккаунта.

## Результаты базового квартального правила

| Альтернативный портфель | Январь 2024 — 5 октября 2026 | Простая годовая доходность на $2700 | 95% месячный интервал годовой доходности | Май — 5 октября 2026 |
|---|---:|---:|---:|---:|
| BTC | +$248.86 | +3.337% | [1.743%; 5.499%] | +$17.59 |
| ETH | +$258.67 | +3.468% | [1.797%; 5.690%] | +$12.42 |
| XRP | Теоретически +$242.99 | Не трактовать как реализуемую доходность | Не устраняет нарушение маржи | −$3.03 |

Свежий май–октябрь при независимом старте:

| Актив | Годовой темп, base | 95% интервал | Стресс net $ | Минимальный локальный запас шорта / его нотионал, base |
|---|---:|---:|---:|---:|
| BTC | +1.566% | [−1.595%; 3.287%] | +$11.76 | 35.37% |
| ETH | +1.106% | [−2.000%; 2.989%] | +$6.39 | 13.04% |

Стресс: spot fee 0.12%, perp fee 0.06%, slippage 0.04% за каждую сторону.

Полный BTC cashflow: funding +$312.32, изменение базиса +$0.96, комиссии −$50.86, slippage −$13.56 = +$248.86. Полный ETH: funding +$321.44, изменение базиса +$1.35, комиссии −$50.62, slippage −$13.50 = +$258.67. Спот без хеджа и шорт без спота сохранены как атрибуционные контроли; сумма их P&L в каждом пакете точно равна P&L carry. Денежный контроль без процентного дохода равен нулю.

Это положительный результат на истории из явного источника платежа. Современный темп существенно меньше, а свежие интервалы пересекают ноль. Пакеты и начисления фандинга зависимы; число платежей не равно числу независимых торговых наблюдений. BTC и ETH здесь альтернативные использования одного капитала — суммы нельзя складывать без совместной модели.

## Маржа и equity

Портфельная equity включает спот, текущую стоимость шорта, денежный резерв, фандинг и все комиссии. Максимальные просадки по часовым закрытиям полного BTC и ETH портфелей: $10.54 и $13.11. Это часовая оценка, не точная стоимость мгновенной ликвидации всех ног.

Отдельно проверен локальный денежный резерв шорта при внутрисвечном максимуме фьючерса, с накопленной ранее прибылью. Минимум полного BTC — 18.36% текущего фьючерсного нотионала, ETH — 9.58%. Исторические mark-price пути и точные maintenance tiers не загружены; эти величины являются стресс-диагностикой, а не доказательством отсутствия ликвидации.

У XRP минимум локальной маржи отрицателен: примерно −54.69% / −$3467.58. Продолжать такой путь и предъявлять положительный конечный P&L как торгуемую стратегию нельзя. Поэтому XRP исключён независимо от красивого суммарного результата.

## Тенденция источника дохода

Годовые суммы ставок фандинга Binance, до расходов, на нотионал:

| Актив | 2024 | 2025 | 2026 до 5 октября: фактическая сумма / годовой темп |
|---|---:|---:|---:|
| BTC | 11.957% | 5.126% | 2.255% / 2.966% |
| ETH | 12.997% | 4.929% | 1.514% / 1.991% |
| XRP | 14.229% | 3.528% | −0.106% / −0.139% |

Положительные старые средние нельзя переносить как сегодняшнюю ожидаемую выплату. Для actual position доход необходимо взвешивать по количеству монет и mark price каждого события.

## Проверки и воспроизведение

Независимый QA подтвердил четыре исполнения, funding sign, отсутствие двойного счёта и сохранение денежных потоков. Во всех 30 baseline окнах сумма месячного P&L равна сумме пакетов; отдельные spot/short контроли также сверены. Bootstrap выбирает пары «месячный P&L, реальные дни экспозиции», включая неполные крайние месяцы; 5000 повторов, фиксированный seed. Интервал соответствует тому же годовому показателю, что точечная оценка. Это диагностический интервал, не стационарная гарантия.

Воспроизведение: `python research/expectancy_20261006/carry_lab.py`. Числа: `metrics.json`, `summary.csv`; полные пакеты, часовая equity и месячные денежные потоки находятся рядом. Сводные независимые проверки — `../intraday/qa_root_labs.json`.


</details>


<details>
<summary>Предыдущий source trend/REPORT.md</summary>

# Независимая численная проверка 4h-тренда, 06.10.2026

Замороженный до вычислений референс: закрытие выше/ниже предыдущих 30 полных 4h экстремумов при Wilder ADX14≥20; рыночный вход на следующем 4h открытии. Initial stop ATR14×3, Chandelier по экстремуму со входа, только затягивание после полного 4h закрытия. Одна позиция, без пирамидинга и подбора. Это явная реализация краткого описания брифа; исходный скрипт из брифа отсутствует, поэтому точное совпадение реализации не доказано.

На каждую сделку фиксированный входной нотионал $1000, комиссия 0,05% и неблагоприятное проскальзывание 0,02% за сторону (полный круг около 0,14%). Стресс: проскальзывание 0,04% за сторону (круг около 0,18%). Все суммы — P&L на этот торговый размер, НЕ доходность депозита, без реинвестирования, плеча и оптимизации риска. Funding реальный Binance; для новых USD-M данных есть точный markPrice начисления. Сигнал и исполнение USD-M всё ещё не подтверждают исполнение/комиссии WEEX или OKX.

## Старые минутные spot-данные с funding, 12.05.2024 — 07.05.2026 08:00 UTC

| Актив / окно | N | Gross $ | Net $ | PF | Средняя net %/сделку | Средняя net R | DD close $ | 95% CI средней net % | Плацебо p |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| ETHUSDT | 81 | +996.50 | +861.60 | 1.549 | +1.064 | +0.264 | 478.27 | -0.253 / +2.642 | 0.11 |
| XRPUSDT | 92 | +944.79 | +793.46 | 1.398 | +0.862 | +0.072 | 717.08 | -0.589 / +2.613 | 0.21 |
| BTCUSDT | 95 | +114.93 | -28.03 | 0.981 | -0.030 | +0.006 | 496.33 | -0.668 / +0.671 | 0.50 |

Последняя треть старого набора (07.09.2025 — 07.05.2026) отрицательна у всех трёх: ETH −$77,95, XRP −$46,72, BTC −$192,23. ETH и XRP положительны суммарно, но N<100, месячные CI пересекают ноль, сдвинутые сигналы не отвергаются. Позитив из брифа не воспроизведён как достаточное доказательство положительного ожидания.

## Direct Binance USD-M 1h, 11.01.2024 — 06.10.2026 00:00 UTC

| Актив / окно | N | Gross $ | Net $ | PF | Средняя net %/сделку | Средняя net R | DD close $ | 95% CI средней net % | Плацебо p |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| ETHUSDT | 106 | +1481.75 | +1288.68 | 1.704 | +1.216 | +0.260 | 353.76 | +0.177 / +2.445 | 0.06 |
| XRPUSDT | 122 | +751.87 | +549.15 | 1.208 | +0.450 | +0.021 | 659.89 | -0.754 / +1.894 | 0.32 |
| BTCUSDT | 129 | +60.14 | -141.59 | 0.928 | -0.110 | +0.019 | 547.47 | -0.665 / +0.501 | 0.58 |

## Последняя треть USD-M, 07.11.2025 — 06.10.2026

| Актив / окно | N | Gross $ | Net $ | PF | Средняя net %/сделку | Средняя net R | DD close $ | 95% CI средней net % | Плацебо p |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| ETHUSDT | 33 | +53.41 | +4.65 | 1.007 | +0.014 | -0.017 | 353.76 | -1.507 / +2.076 | 0.51 |
| XRPUSDT | 40 | -154.71 | -217.30 | 0.768 | -0.543 | -0.104 | 659.89 | -1.708 / +1.188 | 0.72 |
| BTCUSDT | 43 | -139.42 | -199.07 | 0.745 | -0.463 | -0.064 | 396.72 | -1.525 / +0.733 | 0.78 |

Последняя треть — самостоятельный запуск с прогретыми каузальными индикаторами и ликвидацией остатка на границе, поэтому результаты трёх запусков не обязаны складываться в одну непрерывную историю. ETH +$4,65 исчезает от повышения расходов: см. стресс ниже. Позитив полного ETH CI не снимает провал свежего окна и неоднозначность плацебо (p=0,06 до поправки на три актива).

## Дополнительные свежие прямые futures1m, 07.05.2026 — 06.10.2026

| Актив / окно | N | Gross $ | Net $ | PF | Средняя net %/сделку | Средняя net R | DD close $ | 95% CI средней net % | Плацебо p |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| ETHUSDT | 12 | +162.57 | +145.60 | 1.718 | +1.213 | +0.206 | 220.48 | -0.304 / +2.783 | 0.34 |
| XRPUSDT | 19 | -102.66 | -132.56 | 0.704 | -0.698 | -0.140 | 297.11 | -2.676 / +2.048 | 0.74 |
| BTCUSDT | 18 | +51.80 | +24.28 | 1.092 | +0.135 | +0.136 | 174.76 | -1.361 / +1.558 | 0.31 |

Здесь входы и ATR/ADX прогреты полным предыдущим USD-M 1h-префиксом, исполнение и marked equity идут по свежим минутам. ETH проходит знак и стресс на этом отрезке, но это только 12 сделок за 152 дня, CI пересекает ноль, контроль p=0,34. Две сделки в самой последней трети нельзя объявлять новой стабильной стратегией.

## Соседняя поверхность ETH

| Канал 4h | ADX≥ | ATR× | USD-M full net $ | USD-M latest-third net $ | Fresh-minute May–Oct net $ |
|---:|---:|---:|---:|---:|---:|
| 30 | 20 | 3.0 | +1288.68 | +4.65 | +145.60 |
| 24 | 20 | 3.0 | +1207.72 | -33.63 | +136.01 |
| 36 | 20 | 3.0 | +1408.63 | +163.19 | +238.83 |
| 30 | 15 | 3.0 | +865.57 | -103.06 | +210.08 |
| 30 | 25 | 3.0 | +811.46 | -39.20 | +167.19 |
| 30 | 20 | 2.5 | +649.82 | -381.11 | +31.74 |
| 30 | 20 | 3.5 | +1296.67 | +33.11 | +103.13 |

Поверхность USD-M latest-third пересекает ноль: 24-bar, ADX15/25 и ATR2,5 отрицательны. Поэтому выбирать удачные 36-bar или ATR3,5 после просмотра свежего окна запрещено. На дополнительном May–Oct ETH все 7 соседей положительны, но это короткий отрезок, ранее средняя часть уже была отрицательной.

## Стресс и перенос источника

| Актив | USD-M full base / stress $ | Latest-third base / stress $ | Fresh1m base / stress $ | Same May2024–May2026 spot1m / direct-futures1h $ |
|---|---:|---:|---:|---:|
| ETHUSDT | +1288.68 / +1246.41 | +4.65 / -8.38 | +145.60 / +140.84 | +861.60 / +1114.88 |
| XRPUSDT | +549.15 / +500.03 | -217.30 / -233.48 | -132.56 / -140.22 | +793.46 / +845.69 |
| BTCUSDT | -141.59 / -193.23 | -199.07 / -216.14 | +24.28 / +17.09 | -28.03 / -90.18 |

На совпадающих свежих USD-M часах/минутах N и торговый P&L совпадают (проверка ниже); время внутри touched-часа в часовой модели приблизительно. Просадку часовой close-кривой нельзя трактовать как точную минутную: дополнительно сохранён консервативный OHLC-envelope, допускающий благоприятный экстремум перед неблагоприятным. У XRP верхняя оценка заметно выше.

## Проверки и ограничения

- Аудит старых 1m: 0 gaps, duplicates, нарушений OHLC, integer epoch ms. Старые 1h последние частичные свечи исключены. Новые direct-futures входы проверены на непрерывные наблюдения; при неожиданных пропусках движок отказывается проводить тест, не синтезирует цены.

- Prefix-индикаторы совпали с полной историей; сделки до среза совпали (кроме обязательной финальной ликвидации); cash/equity и net-журнал сошлись. Stop проходит внутри исходных минут/часов с adverse gap-fill; повторного входа внутри той же 4h нет.

- 5000 monthly block bootstrap повторов полного окна и дополнительного fresh-window; thirds 2000. 99 одинаково устроенных дневных циклических сдвигов для каждой пары asset/source. Сдвиги сохраняют кучность и UTC-час, но не идеально сохраняют зависимость сигналов от режима. Trade-month CI и daily-marked-month CI сохранены отдельно.

- Time-shift плацебо и CI не корректируют исторический отбор ETH/XRP из множества прошлых исследований. Новые числа не являются гарантией будущего ожидания. Funding convention: событие на точном entry-open не оплачивается; удержанная позиция платит/получает последующие события до фактического выхода.

- Результат требует недельных удержаний, а не скальпинга: полный ETH median hold≈58ч, median initial stop≈5,72%; fresh median hold≈63ч. Последний отрезок слабый по числу сделок. Исполнение stop и величина slippage/fees требуют живой paper-проверки на целевой бирже.

## Решение

ETH 4h тренд — лучший проверенный кандидат этой ветки для заранее замороженного paper-журнала. Полное USD-M окно даёт положительный CI и заметный P&L после расходов, но текущий набор ворот в целом не пройден: последняя треть почти нулевая и отрицательна под стрессом, поверхность там пересекает ноль, p сдвинутых контролей 0,06/0,51. XRP и BTC базовый референс отвергаются как кандидаты для запуска. Выдавать три стратегии с доказанным положительным матожиданием по этим данным было бы неверно.

Воспроизведение: `python research/expectancy_20261006/trend/run_trend.py --source futures1h --symbols ETHUSDT XRPUSDT BTCUSDT --placebos 99`; аналогично `futures1m` и `spot1m`. Затем `python research/expectancy_20261006/trend/summarize.py`. Полные JSON, trade CSV, daily_equity CSV и placebo CSV находятся рядом с этим отчётом.

</details>
