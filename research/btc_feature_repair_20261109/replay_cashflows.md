# Исследовательский funding cashflow replay

`replay_cashflows.py` не является production trading service. Он ничего не отправляет, не создаёт ордеров и не меняет исходные данные. Он считает funding для уже закрытых engine events и явно показывает неполноту данных и временные соглашения.

```python
from replay_cashflows import event_net, prepare_funding

prepared = prepare_funding(rates, attrs={
    'expected_interval_s': 28800,
    'supported_from_s': 1568102400,
})
# a['t'] — CLOSE timestamps in UTC epoch seconds; rates is decimal, not percent.
result = event_net(exit_event, a, prepared, mode='corrected')
```

PreparedFunding immutable; нормализация и сортировка O(N log N) выполняются один раз. В каждом вызове выбираются только выплаты внутри сделки через bisect. `rates` может быть pandas Series с секундами в index, публичный CSV DataFrame (`ms,rate` или `fundingTime,fundingRate`), либо funding_records dict (`times`, `rates_pct`). У dict поддерживаются top-level `expected_interval_s`, `schedule_anchor_s`, `supported_from_s`, `venue`; одноимённые `attrs` имеют приоритет, явный `prepare_funding(...,attrs=...)` — последний приоритет.

## Деньги и размер

- `net_no_funding` копирует `e['res']`, где engine уже учёл исходные комиссии; повторных комиссий нет.
- Main позиции: первоначальная нога `w*0.5`, исполненный добор `w*0.5`; CS — `w`; 432 — 1.0 базы. Переоценка капитала и leverage не добавляются.
- Для каждой ноги сохраняется её количество: `funding_cost_pct = side*leg_weight*100/entry_price * Σ(spot_proxy_price_at_pay * decimal_rate)`. Положительное значение — расход, отрицательное — поступление, поэтому положительный funding приносит short доход.
- Ценовой proxy — **точное** `a.c` в `a.t == funding_time`; это spot H1 close, а не подтверждённый perp mark. Если ненулевой выплате нет цены в тот же час, она неизвестна. Переноса на следующий доступный бар или интерполяции нет. Нулевая наблюдённая ставка даёт точно 0 без необходимости цены.
- Все funding timestamps приводятся к **началу минуты** (ms jitter); одна выплата не дублируется. Дубликаты с одинаковой ставкой объединяются; конфликтующие или нечисловые ставки становятся missing. Входные файлы не меняются.

## Порядок событий

`entry_t` — точное закрытие входного часа. `add_t` — закрытие часа, внутри которого действующий stop был исполнен до close. `e.t` — закрытие выходного часа. Между входом и завершением существование каждой ноги определяется отдельно.

| Граница | corrected | old_event_clock | basis_bug |
|---|---|---|---|
| Funding в точный момент первого входа | Исключается: позиция открывается после выплаты | То же | То же |
| Funding на OPEN часа добора | Сначала funding, затем standing order: добор ещё не существует | Добор ещё не существует | Ошибочно считается существовавшим с первого входа |
| Funding строго внутри часа добора | Неизвестно, stop уже исполнился или нет: bounds/status | Добор начинает считаться только после записанного close | Ошибочно считается существовавшим с первого входа |
| Funding на CLOSE часа добора | Добор уже исполнен до close, выплата включает его | Исключается для add: старый event clock | Включается как часть ошибочного интервала с entry |
| Funding на OPEN target-exit часа | Сначала funding, затем standing target | Включается | Как corrected |
| Funding строго внутри target-exit часа | Без точного target time неизвестно, позиция ещё существует или уже закрыта | Включается вплоть до recorded close | Как corrected |
| Funding на CLOSE target-exit часа | Исключается: target исполнен раньше close | Включается по старому recorded close | Как corrected |
| Funding в момент обычного close-exit | Включается: funding прежде close-decision | То же | То же |

`basis_bug` — **изолированный контрфактический A3**, меняет только начало funding добора; CS, 432 и main без добора совпадают с corrected. `old_event_clock` отдельно сохраняет оба старых clock-допущения. Он не воспроизводит старый перенос funding price на следующий доступный H1 при дыре — такие выплаты честно помечаются неизвестными.

Обычная 8h UTC сетка не содержит выплат строго внутри часового бара. Но API проверяет и такой случай. Если same-clock price supplied, bounds включают варианты «добор/позиция ещё отсутствует» и «уже существует». Если нет и цены, границы неизвестны и остаются NaN. Порядок внутри минут/секунд этим модулем не выдумывается.

## Полнота и неподдержанные периоды

По умолчанию поддержка начинается с **первой наблюдаемой выплаты BTC USDT-M** 10.09.2019 08:00 UTC (`1568102400`), а не с произвольно объявленного момента запуска инструмента. Сделки до этой границы и Bitstamp (`a['venue']='Bitstamp'` либо attrs venue) не считаются фактическими подтверждёнными perp-трейдами.

- `funding_history_complete`: все необходимые выплаты ожидаемой сетки доступны и период/venue поддержан.
- `funding_complete`: дополнительно известны нужные proxy prices и порядок присутствия ног.
- `funding_cost_pct`: сумма **определённых наблюдённых** расходов; неизвестные или неоднозначные суммы в неё не включаются.
- `net_with_observed_funding` и синоним `benchmark_net_with_observed_funding`: `net_no_funding - funding_cost_pct`, то есть наблюдаемый benchmark. Если history incomplete, это **не полный net сделки**. До inception/Bitstamp нулевой benchmark funding означает условное отсутствие учтённых выплат, а не доказанные нулевые расходы реальной торговли.
- `net_with_funding_strict`: NaN при любой неполноте или неоднозначности. Его нельзя заполнять нулём или прибавлять к полной net-сумме без отдельного учёта покрытия.
- `funding_cost_lower_pct/upper_pct`, `net_with_funding_lower_pct/upper_pct`: границы только при полной ставочной/ценовой поддержке, когда неопределён именно порядок исполнения. При missing history/price/unsupported периоде они NaN.
- `status`, `missing_funding_times`, `missing_proxy_price_times`, `ambiguous_payments` и `payments` объясняют ограничения по каждой сделке.

Во всех денежных выводах сохраняется оговорка **spot proxy**, даже при `complete_spot_proxy`: правильные timestamps и ноги не превращают spot в реальный mark-price cashflow.

## Проверки

`python -X utf8 -m pytest -c pytest.ini --confcutdir=. --basetemp=<новая папка> -q test_replay_cashflows.py`

Acceptance cases: funding на входе, добор-close, add+exit в одном баре, target open/close, чистый basis_bug, short receipt/432 unit size, missing vs observed zero, inception/Bitstamp, timestamp jitter/duplicates/conflicts, intrabar bounds, same-clock price missing, immutable prepared equivalence, root-level interval metadata. Отдельный тестовый модуль не подключается к production suite автоматически.
