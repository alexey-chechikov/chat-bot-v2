# Пять вариантов ботов на реальный торговый оборот

11.10.2026. Для репозитория `alexey-chechikov/chat-bot-v2`, ветки `alexey/mac-2026-05-29`.

**Первым я бы отрабатывал последовательный maker-вход и разгрузку, вторым — дальние котировки с прекращением набора после первого исполнения.** Они проще остальных по состояниям и восстановлению. Пять вариантов ниже — проверяемые спецификации для сравнительного paper-теста. Их доходность и надёжность реализации ещё не подтверждены. Ни ордеров, ни изменений живых конфигов, ни сообщений бирже из этой сессии не было.

Оборот формируется реальными исполнениями с независимыми рыночными контрагентами. Это не схема собственных встречных сделок или заранее согласованных аккаунтов. Цель — измерить стоимость полезного оборота и ограничивать остаток.

| Вариант | Механика | Сложность реализации | Очерёдность |
|---|---|---|---:|
| 1 | Один вход, затем только разгрузка | Низкая | 1 |
| 2 | Дальние котировки, первый fill прекращает набор | Средняя: гонки двух отмен | 2 |
| 3 | Котировки со смещением под остаток | Средняя: несколько partial fills | 3 |
| 4 | Микросетка с конечными уровнями и refill | Выше: несколько лотов и общий выход | 4 |
| 5 | Maker с внешним аварийным хеджем | Высокая: две биржи и две маржи | 5 |

Это порядок простоты, не рейтинг доходности. Скорость оборота зависит от настоящих fills и очереди, а не от числа размещённых заявок. Параметры ниже — стартовые значения для замороженного теста, не найденные оптимальные настройки.

## Общая оболочка

Один процесс владеет заявками и учётом; предпочтителен отдельный бот-субаккаунт. На общем счёте ручные сделки меняют общую биржевую позицию, и prefix не изолирует этот риск. Текущий счёт документ не переключает.

Для примера C=$3000:

- Каждая входная котировка — не больше 1%C, то есть **$30**. Qty округляется вниз; если минимум контракта больше бюджета, вход пропускается.
- Общий gross inventory вместе со всем ещё исполнимым набором — не больше 10%C, то есть **$300**; net inventory — не больше 5%C, то есть **$150**.
- Модельный риск эпизода — до 0.1%C (**$3**), общий бюджет прекращения paper-дня — 0.2%C (**$6**). Gap, отказ или неизвестный исход выхода могут превысить плановый бюджет: это не гарантия максимального убытка.
- Сначала варианты тестируются по очереди на одинаковом капитале и бюджете. При совместной работе им нужен один ledger: лимиты не выдаются каждому независимо.

Размер нового входа:

`q=floor_step(min(R_remaining/loss_per_unit, gross_room/E))`

`loss_per_unit` включает цену до настоящего аварийного trigger, entry fee, вероятный taker exit fee, неблагоприятное исполнение и funding reserve. Для лестницы суммируется риск всех ещё возможных fills. Будущий хедж или тейк не считаются уже полученной защитой.

Бюджет эпизода не восстанавливается после каждого тейка. Реализованные потери и оплаченные расходы учитываются один раз; будущий резерв исключает уже оплаченный fee. Прибыль и обещанный rebate не увеличивают исходный R.

Состояния: `IDLE → ENTRY_PENDING → INVENTORY → EXIT_PENDING → RECONCILE → IDLE`. Intent сохраняется до POST, а ACK и adoption — атомарно до очистки intent. Неизвестный ответ означает сверку, а не повторную отправку. Partial fill немедленно создаёт остаток. CANCELING и UNKNOWN не освобождают резерв. После принятия сироты used пересчитывается до следующего POST.

Выходы — reduceOnly по правильной стороне. Новый SHORT не заменяет закрытие LONG. LONG+SHORT в hedge-mode не означают FLAT по нулевой delta. Старые algo orders и late fills ведутся до подтверждённого terminal состояния. Отключение стратегии запрещает набор, но не сопровождение остатка.

Перед агрессивным выходом собственные встречные заявки должны быть подтверждённо отменены либо должен действовать проверенный exchange STP. Отказ защиты ведёт в EXIT_ONLY с контролируемым уменьшением фактического остатка. Устаревшая книга, неизвестный риск, повреждённый state, NaN или расхождение позиции блокируют новые входы.

Все операции проходят через фактический API budget с резервом на отмену и выход. TTL5сек нельзя считать исполненным, если лимит команд не позволяет снять котировку вовремя.

## 1. Последовательный maker: один вход, затем разгрузка

**Назначение:** самый простой эталон стоимости оборота и восстановления одного эпизода.

**Вход:** одна BTCUSDT post-only заявка до $30. LONG-тест — BUY на один tick ниже best bid; SHORT — SELL на один tick выше best ask, как отдельный контроль. Книга не старше2сек, spread≤0.03%, quote≤1% видимой глубины в ближайших10bps на своей стороне, sigma предыдущих30 закрытых минутных mid-returns≤0.10%. Это стартовые фильтры ликвидности/волатильности, не прогноз цены. Полная целевая дистанция entry→exit — **0.08%**.

**Отмена:** возраст заявки5сек, объявленный сдвиг mid или непригодные данные. После любого fill остаток входа снимается, новый набор прекращается. Partial entry не доводится до полного ради объёма.

**Выход:** reduceOnly maker target0.08% от actual average fill; биржевой аварийный stop0.25% против входа; максимум15мин с первого fill, затем контролируемый taker exit. Защита не снимается раньше подтверждённого закрытия. Во время остатка или UNKNOWN новых входов нет.

**Размер:** один фиксированный q, весь возможный вход и аварийный выход заранее помещаются в общий R. До полной сверки FLAT следующего эпизода нет.

**Экономика:** цель8bps превышает чисто комиссионный порог maker/maker3.2005bps и maker/taker6.4031bps. Но это геометрия, а не частота достижимых тейков. Timeout превращает часть циклов в maker/taker; недополученная разгрузка остаётся ценовым риском.

## 2. Дальние котировки: первый fill прекращает набор

**Назначение:** меньше перестановок у best price; проверить исполнение на колебаниях цены.

**Вход:** в FLAT две post-only заявки по $30 вокруг зафиксированного fair mid. Half-width `h=max(0.08%,2*sigma_1m)`, где sigma — стандартное отклонение предыдущих30 закрытых минутных mid-returns. Полный bid/ask gap равен2h. До mid от каждой котировки — h, не2h.

**Отмена:** возраст10сек либо mid ушёл на h/3. После первого fill обе открывающие стороны снимаются. Если обе успели исполниться, учитываются обе gross-позиции и ведутся их выходы; они не объявляются пустым состоянием.

**Выход:** reduceOnly к исходному fair mid только если он остаётся на прибыльной стороне actual entry и покрывает расходы. Иначе действует заранее объявленный выход. Stop0.5% против entry, максимум30мин. Границы не перемещаются за уходящей ценой.

**Размер:** резервировать риск обоих первоначальных fills; максимум$60 gross для пары, а общий риск эпизода всё равно до$3. При нехватке бюджета q уменьшается или постановка пропускается.

**Экономика:** отступ до mid8bps может перекрыть maker costs. Однако далёкая заявка часто исполняется при информированном движении; это не доказанный безопасный возврат цены. Меньше активных перестановок может означать и меньше оборота.

## 3. Inventory-skew: добавляющая котировка отодвигается

**Назначение:** больше естественных partial fills при управлении накопленным остатком.

**Вход:** для текущего hedge-mode сначала один малый LONG-entry. После fill разрешаются BUY на добавление в тот же LONG и SELL reduceOnly LONG на разгрузку. SHORT-вариант зеркален в отдельном эпизоде. Истинный netting-MM — другой режим, который нельзя подразумевать без отдельной проверки API.

Reservation price `r=mid−k*(owned_signed_qty/Qmax)*mid`, цены `r*(1−h)` и `r*(1+h)`. Начальные paper-значения h=0.04%, k=0.04% (в формуле0.0004). При росте LONG bid удаляется и его размер снижается; ask приближается для разгрузки. Post-only границы и наличие позиции проверяются перед каждой командой.

**Отмена:** возраст котировки5сек. При80% inventory cap снимаются увеличивающие риск заявки, остаётся разгрузка. При100%, stale book или UNKNOWN — EXIT/RECONCILE. Замена не ставится поверх неизвестного предшественника.

**Выход:** возраст эпизода максимум15мин с первого fill. Общий emergencyS фиксируется от первого входа на0.25% неблагоприятного хода. Добавления не отодвигают его ради усреднения. Все новые q считаются до этого S; цена уже за S запрещает набор.

**Размер:** quote≤$30, общий net≤$150/gross≤$300, включая ещё исполнимые заявки. R≤$3 на весь эпизод, не на каждую добавку. Денежный риск может ограничить набор раньше notional cap.

**Экономика:** skew контролирует inventory, но сам не создаёт edge. Нужно измерить cash capture, taker-exit share и стоимость$1M. Номинальная дистанция2h не гарантируется каждому исполнению. Эта схема сложнее1/2.

## 4. Конечная микросетка: два уровня, один refill

**Назначение:** использовать знакомую grid-инфраструктуру без бесконечного мешка.

**Вход:** один directional episode. LONG — два одинаковых q ниже исходного mid на0.05%/0.10%; SHORT — зеркально. Исходный mid и общая stop-boundary0.35% против него фиксируются до старта. Эпизод начинается только с FLAT.

**Отмена:** boundary, возраст30мин, исчерпанный R или UNKNOWN запрещают новые входы. Максимум один повтор данного уровня после подтверждённого закрытия его лота, без увеличения q. Прибыль не расширяет первоначальный бюджет.

**Выход:** отдельные reduceOnly TP0.10% каждого fill; общий stop/timeout закрывает весь остаток. Старые лоты не переходят в новый эпизод с новым временем и границами.

**Размер:** до двух исходных заявок по$30; fixedq из суммы всех возможных stopped losses с costs. Каждый refill заново проверяет оставшийся R. Будущий тейк не освобождает место заранее.

**Экономика:** target10bps перекрывает fees геометрически. Один общий аварийный выход способен съесть много тейков. Отличие от прежней постоянной BTC-сетки — finite refill, фиксированный риск и обязательный выход; доходность от этого ещё не доказана.

## 5. Maker с внешним аварийным хеджем

**Назначение:** уменьшить часть ценового риска уже исполненного WEEX-остатка при проблеме разгрузки. Самый сложный вариант для небольшого капитала.

**Вход:** обычные WEEX quotes как в1/3. Внешний hedge активируется только по заранее объявленному условию residual risk/exit failure и под подтверждённый WEEX fill. Деньги и margin обеих площадок выделены заранее; виртуально общая equity их не заменяет.

**Отмена:** сначала запретить новые WEEX-входы и сверить их остатки. Hedge qty не больше фактической owned delta. Lost ACK восстанавливается по cid; второй полный hedge вслепую не отправляется. Нейтральность возникает после подтверждённых fills, не после POST.

**Выход:** WEEX уменьшается; hedge закрывается вслед за подтверждённым уменьшением WEEX-остатка. У двух ног отдельные ownership ledgers. Максимум30мин состояния hedge запускает аварийную процедуру, но не даёт забыть неисполненную ногу.

**Размер:** общий денежный/gross риск, basis, funding и margin каждой площадки отдельно. Низкая delta не обнуляет gross или риск ликвидации отдельных кошельков.

**Экономика:** добавляются ещё два исполнения, fees/spread/funding. Внешний оборот не является оборотом WEEX. Это аварийная страховка, а не гарантированно прибыльная нейтральная прокрутка. Сначала отработать1/2, затем3/4;5 выбирать после проверки двух биржевых ledger.

## Цена оборота

Последние исходные ставки: maker0.016%, taker0.048%. Опубликованный VIP5 справочник даёт такие же reference-ставки; actual API rate остаётся авторитетным для конкретного ключа. [WEEX VIP fees](https://www.weex.com/help/articles/ujokece4c7ygwbobu43ujbii).

`V=Σabs(fill_qty)*fill_price`: все реальные входы и выходы. Попытки, отменённые остатки и unfilled quotes не считаются. Eligible VIP volume имеет отдельные биржевые условия.

| Исполнения на$1M общегоV | Gross fees до refund |
|---|---:|
| Все maker | **$160** |
| Равный поUSD оборот maker/taker | **$320** |
| Все taker | **$480** |

LONG round break-even только для fees: m/m `(m+m)/(1−m)` = **3.200512bps≈0.032005%**, m/t `(m+t)/(1−t)` = **6.403073bps≈0.064031%**. Цена против позиции и расходы на выход добавляются. Adverse cost1bps на каждый исполненный USD оборота — ещё$100/M, 2bps —$200/M. Markout не вычитается второй раз из cash+marked PnL, уже содержащего движение цены.

Условный пример: $100 на каждую исполненную ногу ×50 завершённых кругов/ч ×8ч = **$80k оборота/день**. Fees: m/m$12.80, равный mix$25.60, taker$38.40. Это требуемые800fills, не прогноз fill-rate и не стартовый paper-размер$30.

Если фактическая стоимость$100/M, бюджет$6 соответствует лишь$60k оборота до его исчерпания; при$160/M —$37.5k, при$320/M —$18.75k. Расчёт предполагает фиксированный положительный cost и не зачитывает предполагаемый спред заранее.

Полный refund даёт нулевую итоговую fee-часть только после поступления. До этого учитываются gross списания и margin; funding, price PnL и forced exits остаются. После окончания бонуса режим не продолжает работать под прежним тарифным предположением.

## Что проверять

Одинаковые quote/trade данные, timestamps, latency, капитал и risk budget. Conservative queue: касание OHLC не означает гарантированный maker fill. Нельзя сравнивать идеальный paper-maker с реальным taker без описания различий исполнения.

Для каждого варианта: подтверждённыйV; cash+mark-to-liquidation equity с fees/funding/полученным rebate; cost/$1M; gross/net inventory; максимальный возраст остатка; taker-exit share; fill/quote ratio; signed markout1/5/30/60сек. Результаты до rebate и после реально полученного rebate разделяются.

Fault tests: crash после POST/ACK до adoption; partial entry/exit; cancel-fill race; переполнение history pages; orphan adoption; removed symbol; повреждённая схема/NaN; stale book; stop reject; неизвестная отмена старого algo; отложенная fee; внешний partial hedge. После restart нет потерянного лота, дубликата или повторного расходования room; защитный выход продолжается.

Для диагностики следующего этапа — не меньше1000fills нескольких сессий, блоковый CI полного net и измеренная цена оборота.1000fills не1000 независимых наблюдений. При задаче VIP допустимый заранее ограниченный cost может иметь смысл, если реальная выгода VIP выше; это другая метрика, не прибыльная торговая стратегия.

## Условия WEEX, важные для надёжности

WEEX публично перечисляет быстрые открытия/закрытия и HFT среди признаков ненормальных транзакций. Короткие варианты следует применять в формально разрешённом режиме ликвидности; наличие API само по себе такого статуса не устанавливает. Здесь обсуждаются paper-механики, а не подтверждённый допуск для live. [WEEX trading policy](https://www.weex.com/help/articles/26942698423449).

У VIP8 есть отдельное требование non-API volume: бот сам по себе не выполняет всё условие этого уровня. Это ограничение конкретно VIP8, не утверждение, что API-оборот нигде не засчитывается. [VIP8 criteria notice](https://www.weex.com/help/articles/vevz23hbz64yvy0iyy99xnce).

**Рекомендация:** общий execution/risk core, сначала1, затем2 на совпадающей market data. После сравнения стоимости оборота и fault tests —3/4. Внешний hedge — последний по приоритету. Тесты арифметики приложены; новых fill/backtest результатов пяти вариантов пока нет.


## Приложение: проверка арифметики

Блоки ниже — built-in Decimal, без аккаунтов, торговых команд и сетевых запросов.
Проверяют определение оборота, комиссии, round-trip break-even и денежный пример.
Они не являются бэктестом доходности или испытанием реализации пяти ботов.


<details>
<summary>volume_math_probe.py</summary>

SHA256: `0e2d32a96dae5c12568fd49cfbb1908d4d9d66e3ba6b770970c7b7a9b83ff5a6`

```python
"""Exact arithmetic only; no exchange calls, keys, positions, or source edits."""
from decimal import Decimal, getcontext
from pathlib import Path
import json

getcontext().prec = 40
D = Decimal
m = D("0.00016")
t = D("0.00048")
million = D("1000000")
turnover = D("100") * D("50") * D("8") * 2
out = {
    "definition": "V=sum(abs(fill_qty)*fill_price) across every actual execution; includes entry and exit, not attempted/cancelled/unfilled orders",
    "rates_assumed_from_user_state": {"maker_fraction": str(m), "taker_fraction": str(t),
                                      "maker_percent": str(100*m), "taker_percent": str(100*t)},
    "fees_per_million_total_turnover_USD": {
        "all_maker": str(million*m),
        "equal_maker_taker_turnover": str(million*(m+t)/2),
        "all_taker": str(million*t),
    },
    "daily_example": {
        "per_leg_notional_USD": "100", "real_completed_rounds_per_hour": 50, "active_hours": 8,
        "rounds_per_day": 400, "fills_per_day": 800,
        "total_turnover_USD": str(turnover), "all_maker_gross_fees_USD": str(turnover*m),
        "equal_mix_gross_fees_USD": str(turnover*(m+t)/2),
        "all_taker_gross_fees_USD": str(turnover*t),
        "not_a_fill_forecast": True,
        "note": "Exact only if every entry and exit executed leg has100USD notional; with fixed qty and changed exit price use actual fill values",
    },
    "long_round_trip_break_even": {
        "definition": "buyN, sellN*(1+g); net=N*g - N*f_entry - N*(1+g)*f_exit; g=(f_entry+f_exit)/(1-f_exit)",
        "maker_maker_fraction": str(2*m/(1-m)), "maker_maker_bps": str(10000*2*m/(1-m)),
        "maker_taker_fraction": str((m+t)/(1-t)), "maker_taker_bps": str(10000*(m+t)/(1-t)),
    },
    "short_round_trip_break_even": {
        "definition": "sellN, buyN*(1-g); net=N*g - N*f_entry - N*(1-g)*f_exit; g=(f_entry+f_exit)/(1+f_exit)",
        "maker_maker_bps": str(10000*2*m/(1+m)),
        "maker_taker_bps": str(10000*(m+t)/(1+t)),
    },
    "adverse_cost_per_million_turnover_USD": {"1bps": str(million*D("0.0001")),
                                            "2bps": str(million*D("0.0002"))},
    "rebate": {
        "if_100pct_rebate_actually_received": "cash fee net0; gross fee charges still occur and rebate receivable is not available margin",
        "zero_fee_does_not_erase": ["spread/adverse_selection", "slippage/emergency_exit", "funding", "inventory_price_PnL", "unfilled_leg_risk"],
    },
    "measurement_caution": "Adverse1bps per executed-turnover means100/M. A markout statistic is diagnostic; do not subtract it again from cash+marked-inventory netPnL that already contains the price effect.",
    "budget_example_not_guaranteed_loss_limit": {
        "single_shared_research_budget": "sum of allocated model loss budgets <=0.5% confirmed account equity; each candidate <=0.2%; not5 times0.2% independently",
        "maker_quote_notional": "per quote<=1% equity, gross sum of all still-fillable entries/inventory<=10% equity for the whole experiment",
        "net_inventory": "<=5% equity per active test, additionally shared worst-fill risk reservation; gross cap still needed in hedge mode",
        "risk_quantity": "floor_step(min(R_remaining/(price_to_emergency_trigger+gross_fees_per_unit+adverse_buffer+funding_buffer),reserved_gross_room/reference_price))",
        "margin": "count committed margin for both hedge legs and pending/UNKNOWN fills; keep confirmed free reserve; leverage only changes margin, not price-loss budget",
        "not_absolute_guarantee": "gap, spread widening, rejected/unknown exits, liquidation and fee-rebate delay can exceed model budget",
    },
}
assert D(out["fees_per_million_total_turnover_USD"]["all_maker"]) == 160
assert D(out["fees_per_million_total_turnover_USD"]["equal_maker_taker_turnover"]) == 320
assert D(out["fees_per_million_total_turnover_USD"]["all_taker"]) == 480
assert D(out["daily_example"]["total_turnover_USD"]) == 80000
assert D(out["daily_example"]["all_maker_gross_fees_USD"]) == D("12.8")
path = Path(__file__).with_name("volume_math_probe.json")
path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=True, indent=2))
```

</details>


<details>
<summary>volume_math_probe.json</summary>

SHA256: `01f84ea342c1cf3f9f6023b9eb7c6ed5aa7f56538fa77e54ffb68c67a3bad0ad`

```json
{
  "definition": "V=sum(abs(fill_qty)*fill_price) across every actual execution; includes entry and exit, not attempted/cancelled/unfilled orders",
  "rates_assumed_from_user_state": {
    "maker_fraction": "0.00016",
    "taker_fraction": "0.00048",
    "maker_percent": "0.01600",
    "taker_percent": "0.04800"
  },
  "fees_per_million_total_turnover_USD": {
    "all_maker": "160.00000",
    "equal_maker_taker_turnover": "320.00000",
    "all_taker": "480.00000"
  },
  "daily_example": {
    "per_leg_notional_USD": "100",
    "real_completed_rounds_per_hour": 50,
    "active_hours": 8,
    "rounds_per_day": 400,
    "fills_per_day": 800,
    "total_turnover_USD": "80000",
    "all_maker_gross_fees_USD": "12.80000",
    "equal_mix_gross_fees_USD": "25.60000",
    "all_taker_gross_fees_USD": "38.40000",
    "not_a_fill_forecast": true,
    "note": "Exact only if every entry and exit executed leg has100USD notional; with fixed qty and changed exit price use actual fill values"
  },
  "long_round_trip_break_even": {
    "definition": "buyN, sellN*(1+g); net=N*g - N*f_entry - N*(1+g)*f_exit; g=(f_entry+f_exit)/(1-f_exit)",
    "maker_maker_fraction": "0.0003200512081933109297487598015682509201472",
    "maker_maker_bps": "3.200512081933109297487598015682509201472",
    "maker_taker_fraction": "0.0006403073475268128701776852889386905714743",
    "maker_taker_bps": "6.403073475268128701776852889386905714743"
  },
  "short_round_trip_break_even": {
    "definition": "sellN, buyN*(1-g); net=N*g - N*f_entry - N*(1-g)*f_exit; g=(f_entry+f_exit)/(1+f_exit)",
    "maker_maker_bps": "3.199488081906894896816509358502639577668",
    "maker_taker_bps": "6.396929473852550775627698704621781544858"
  },
  "adverse_cost_per_million_turnover_USD": {
    "1bps": "100.0000",
    "2bps": "200.0000"
  },
  "rebate": {
    "if_100pct_rebate_actually_received": "cash fee net0; gross fee charges still occur and rebate receivable is not available margin",
    "zero_fee_does_not_erase": [
      "spread/adverse_selection",
      "slippage/emergency_exit",
      "funding",
      "inventory_price_PnL",
      "unfilled_leg_risk"
    ]
  },
  "measurement_caution": "Adverse1bps per executed-turnover means100/M. A markout statistic is diagnostic; do not subtract it again from cash+marked-inventory netPnL that already contains the price effect.",
  "budget_example_not_guaranteed_loss_limit": {
    "single_shared_research_budget": "sum of allocated model loss budgets <=0.5% confirmed account equity; each candidate <=0.2%; not5 times0.2% independently",
    "maker_quote_notional": "per quote<=1% equity, gross sum of all still-fillable entries/inventory<=10% equity for the whole experiment",
    "net_inventory": "<=5% equity per active test, additionally shared worst-fill risk reservation; gross cap still needed in hedge mode",
    "risk_quantity": "floor_step(min(R_remaining/(price_to_emergency_trigger+gross_fees_per_unit+adverse_buffer+funding_buffer),reserved_gross_room/reference_price))",
    "margin": "count committed margin for both hedge legs and pending/UNKNOWN fills; keep confirmed free reserve; leverage only changes margin, not price-loss budget",
    "not_absolute_guarantee": "gap, spread widening, rejected/unknown exits, liquidation and fee-rebate delay can exceed model budget"
  }
}
```

</details>
