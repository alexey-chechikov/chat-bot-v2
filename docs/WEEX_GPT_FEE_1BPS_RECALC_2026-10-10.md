# WEEX: что меняет итоговая taker-комиссия 1 bps

Дата: 10 октября 2026 года. Сценарий: эффективная комиссия futures taker после партнёрского возврата **1 bps = 0.01%**, высокий VIP предоставляется авансом и может продлеваться без обычного порога оборота. Это условия присланного предложения, не независимо проверенный договор или выплата. Личность партнёра, контакты и реклама биржи в расчёте не используются. Счёт, рабочий бот и его параметры не изменялись.

## Что меняет вывод

Низкая taker-комиссия существенно уменьшает порог прибыльности интрадей и может удешевить выходы из сетки. Прежние сценарии $480/млн taker больше не подходят, если предложение действительно применяется к нужным сделкам. Однако maker и применение возврата к API в тексте не определены. Объявление WEEX отдельно устанавливает применимые API-ставки и исключает API из zero-fee promotions; оно само по себе не подтверждает и не опровергает индивидуальный партнёрский возврат. [API fee policy](https://www.weex.com/help/articles/ckz9kdxdvvjmjm2025rh0z49).

Если предоставленный VIP действительно продлевается без стандартного оборота, покупка оборота ради его удержания теряет основную экономическую цель. Тогда критерий — прибыль настоящих сделок после всех расходов, а VIP служит условием низкой цены исполнения.

## Проверенная арифметика

Оборот — сумма исполненных номиналов, обе ноги считаются по одному разу. Вход на $1000 и выход примерно на $1000 дают около $2000 оборота и **$0.20** итоговой комиссии.

| Оборот всех исполнений | Итоговая комиссия при 1 bps |
|---|---:|
| $10 000 | $1 |
| $100 000 | $10 |
| $1 млн | $100 |
| $10 млн | $1000 |
| $100 млн | $10 000 |

Точный порог LONG-покупки/продажи только по двум taker-комиссиям: `2t/(1−t)` = **0.020002%** цены покупки при t=.0001. Для SHORT — около **0.019998%**. Это не полный порог прибыльности: spread, проскальзывание, funding и неудачные исполнения добавляются.

Если stop-дистанция **0.25%**, комиссии за круг составляют примерно **0.08R**, вместо 0.4R при старых 0.05% за сторону. Для идеализированных фиксированных stop/target 1R/3R комиссионная безубыточность LONG снижается примерно с **35.005% до 27.0002% выигрышей**. Это арифметическая иллюстрация, не измеренный win rate и не доказательство преимущества входа.

## Возврат и доступные деньги — разные регистры

В предложении указана итоговая ставка с дополнительным возвратом от партнёра. Поэтому нельзя заранее подменять фактические биржевые комиссии числом .0001 в денежном учёте.

Примеры gross-ставок из [публичной futures-таблицы](https://www.weex.com/help/articles/50717160193561), не подтверждённые ставки аккаунта:

| Gross taker | Списано на $1 млн | Нужный возврат | Расход после его выплаты |
|---|---:|---:|---:|
| VIP5: 0.048% | $480 | $380 | $100 |
| VIP8: 0.040% | $400 | $300 | $100 |

До выплаты свободный капитал уменьшен на gross-сумму; обещанный возврат не является доступной маржой. Нужны отдельно фактически списанные trading fees, ожидаемый договорный возврат и действительно поступившая выплата. Их нельзя дважды вычитать/добавлять в PnL. Риск-бюджет учитывает реальное доступное equity.

Maker не указан. Только условная иллюстрация: VIP8 maker 0.01% и одинаковый с taker возврат 75% дали бы maker 0.0025%, то есть $25/млн. Такой тариф и одинаковая доля возврата не установлены; использовать его как факт нельзя. Даже этот сценарий требует примерно 0.005% двухсторонней дистанции только на fees. Он остаётся выше BTC/ETH лучшего спреда короткого публичного среза предыдущего отчёта.

## Прежняя BTC-сетка: чувствительность, а не новый taker-бэктест

В таблице меняется только стоимость прежних исполнений: сигналы, цены входа/выхода, inventory и конечная оценка не меняются. Старый grid был maker-моделью; предложение о taker не устанавливает новую цену его реальных maker-fills. Переключение типа исполнения потребовало бы отдельной модели.

| Ранее проверенное окно BTC 0.2/0.21 | Старый результат при 0.016% на сторону | Все те же fills условно по 0.01% | Те же fills при нулевых fees |
|---|---:|---:|---:|
| 7 мая — 5 октября 2026 | −$563.71 | −$500.04 | −$393.92 |
| Ранее проверенный примерно 10-месячный прогон | −$553.34 | −$468.42 | −$326.90 |

Таким образом, в этих моделях отрицательный результат не объясняется только комиссией. Источник остаточного минуса — полный результат закрытий вместе с открытой позицией. Funding и реальные WEEX очередь/исполнение в этих grid-результатах не проверены. Новая цена taker сама по себе не доказывает изменение знака нынешней сетки.

Источники сохранённых агрегатов: `ab_inventory.json` предыдущего исследования и `method2_results.json` перепроверки. Арифметический скрипт и вывод включены в приложение ниже.

## Повторная оценка ручного интрадей

Пересчитаны **36 ранее замороженных ячеек** импульсного исследования: BTC/ETH/XRP, следование 15-минутному импульсу на 5м сигнале, следование 60-минутному импульсу на 15м сигнале и противоположный контроль. Это прежний конечный набор, новые параметры не подбирались.

Цена входа/выхода и сигналы сохранены. Новая комиссия .0001 начислена на фактический номинал каждой ноги; проскальзывание оставлено **0.02% за сторону**, стресс — **0.04% за сторону**; исторический futures funding не менялся. Старые окна: март 2024 — май 2026, три хронологические части; дополнительное окно Binance USD-M: **7 мая — 5 октября 2026**. Эти периоды уже изучались, поэтому это fee-sensitivity, а не новая независимая контрольная история. WEEX исполнение не проверено.

В дополнительном окне **3 из 36** получили небольшой положительный результат. **Ни одна из 36** не имеет положительную нижнюю границу свежего 95% месячного bootstrap-интервала и не проходит все экономические проверки по периодам. Дальше три положительные строки показаны описательно, не выбраны для запуска.

| Прежняя версия на 15м: follow, z2.5, удержание ≤120 мин | Сделок май–октябрь | Новый net при фиксированном входном notional $1000 | PF | Net при стресс-проскальзывании |
|---|---:|---:|---:|---:|
| BTC | 158 | +$15.64 | 1.035 | −$50.00 |
| ETH | 174 | +$9.66 | 1.016 | −$59.51 |
| XRP | 154 | +$7.18 | 1.012 | −$48.35 |

Числа в долларах — сумма сделок на фиксированный входной notional, не процент доходности депозита и не модель автоматического реинвестирования. Непрерывная просадка/equity-траектория при новой комиссии в этой чувствительности не пересчитывалась; старую DD нельзя объявить новой. Свежий период имеет только шесть месячных блоков, включая неполный май.

Для этих трёх отдельно сохранены переоценённые интервалы и проверка прежних плацебо. Статистика плацебо описательная: выбор трёх строк после просмотра 36 результатов не даёт нового подтверждения. Не следует запускать их только потому, что итог пересёк ноль.

| Актив | 95% месячный CI дополнительного окна, % на сделку | 64 прежних плацебо: p без поправки за поиск |
|---|---:|---:|
| BTC | [−0.10025%; +0.07687%] | 0.0462 |
| ETH | [−0.09076%; +0.10799%] | 0.0154 |
| XRP | [−0.13637%; +0.13254%] | 0.0154 |

Все 192 контрольных прогона воспроизвели прежние accepted shifts, число сделок и результаты при возврате старой комиссии. Небольшое описательное p не отменяет отрицательные старые периоды, широкий интервал, стресс и отсутствие устойчивости соседей. Эти три настройки были описаны в прежнем отчёте ещё до нового предложения; остальные три intraday-follow соседа для каждого актива остаются отрицательны в дополнительном окне.

## Что полезно делать в логике бота с такими условиями

- Хранить реальные fees и партнёрские выплаты отдельно; оценивать прибыль после полученного возврата, а доступный капитал — по фактическим деньгам.
- Проверять ранее замороженные taker-стратегии с новой ценой исполнения. По найденным трём строкам пока нет подтверждённого преимущества для запуска.
- Исследовать ограниченный taker/IOC-выход из уже достигнутого тейка, когда чистый результат после обеих комиссий и возврата достаточен. Более дешёвый taker может изменить этот выбор; maker-ставка и реальные выплаты должны быть самостоятельными параметрами. Само ожидание прибыли от такого изменения ещё не измерено.
- Внешний хедж не становится бесплатным: при условном внешнем taker 0.05% и равном объёме исполнения общие net-fees — **$600 на $1 млн WEEX-оборота**, до basis/funding/slippage.
- Сохранять ограничения общей позиции и обработку неопределённых исходов. Снижение комиссии не исправляет найденные ранее ошибки pending, восстановлений TP и fee-досверки.

**Решение:** принять 1 bps как новый условный сценарий для исследования такерных стратегий. Отказ от них только по прежней комиссии теперь недостаточен. Повторный численный прогон показал улучшение, но доказанного положительного ожидания среди перепроверенных 36 вариантов пока нет. Целенаправленное создание оборота без торгового преимущества остаётся расходом; при продляемом льготном VIP его польза ещё меньше.

## Приложения и границы воспроизводимости

Далее включены арифметический скрипт, переоценка ручных журналов, точные результаты и контрольные прогоны. Набор источников содержит 82 SHA256 файлов. Исходные минутки, funding и журналы сделок хранятся в предыдущем локальном исследовании и не встроены в этот Markdown; при запуске нужны соответствующие файлы с той же структурой. Поэтому приложенный код раскрывает метод пересчёта, но не является автономным пакетом сырых исторических данных.

Для pandas 3 контрольный адаптер явно сохраняет наносекундную шкалу времени старого движка (`as_unit('ns')`); совпадение индексов входов/выходов проверено. Запускать `reprice_manual.py`, затем `reprice_controls.py`: второй добавляет проверку плацебо в основной JSON. Торговые API и ключи этим кодом не используются.

<details>
<summary>reprice_offer.py</summary>

```python
"""Fee sensitivity on previously saved aggregates, holding all fills constant."""
from decimal import Decimal, getcontext
from pathlib import Path
import json

getcontext().prec = 30
D = Decimal
HERE = Path(__file__).resolve().parent
RATE = D('.0001')

def decimal(value):
    return D(str(value))

def money(value):
    return str(value.quantize(D('.01')))

fees = [{
    'sum_of_execution_turnover': str(v),
    'effective_fee_after_rebate': money(v*RATE),
} for v in map(D, ['10000', '100000', '1000000', '10000000', '100000000'])]

grid5 = json.loads((HERE.parent/'weex_trading_logic_20261010/ab_inventory.json').read_text(encoding='utf-8'))['baseline']
grid10 = json.loads((HERE.parent/'weex_review2_20261010/method2_results.json').read_text(encoding='utf-8'))['new_numbers'][0]
reprice = []
for label, gross, bag, old_fees, old_net, turnover in [
    ('2026-05-07 through 2026-10-05', grid5['realized_gross'], grid5['bag'], grid5['fees'], grid5['equity'], grid5['turnover']),
    ('Previously reviewed approx 10-month BTC run', grid10['закрыто'], grid10['мешок'], grid10['комиссии'], grid10['итог'], grid10['комиссии']/0.00016),
]:
    gross, bag, old_fees, old_net, turnover = map(decimal, [gross, bag, old_fees, old_net, turnover])
    reprice.append({'period': label, 'fixed_execution_turnover': str(turnover),
                    'original_fee_rate': '.00016', 'original_net': money(old_net),
                    'fees_at_offer_rate': money(turnover*RATE),
                    'net_at_offer_rate_same_fills': money(gross+bag-turnover*RATE),
                    'net_if_all_execution_fees_zero': money(gross+bag)})

stop = D('.0025')
r = D(3)
def ideal_win_rate(fee):
    # LONG, target=3*stop, price fees proportional to each leg's actual price.
    return (stop*(1-fee)+2*fee)/((r+1)*stop*(1-fee))

rebates = []
for level, taker_gross, maker_gross in [
    ('VIP5 published scenario', D('.00048'), D('.00016')),
    ('VIP8 published scenario', D('.0004'), D('.0001')),
]:
    refund_share = 1-RATE/taker_gross
    maker_conditional = maker_gross*(1-refund_share)
    rebates.append({'gross_rate_scenario': level, 'gross_taker': str(taker_gross),
        'required_refund_share_for_1bps_taker': str(refund_share),
        'gross_taker_fee_per_million': money(D(1000000)*taker_gross),
        'refund_per_million': money(D(1000000)*(taker_gross-RATE)),
        'hypothetical_maker_if_same_refund_share_applies': str(maker_conditional),
        'hypothetical_maker_fee_per_million': money(D(1000000)*maker_conditional)})

result = {'scope': 'The partner offer is not independently verified. Arithmetic only, no new trading-edge proof.',
    'effective_taker_rate': str(RATE), 'turnover_counts_both_legs_once': True,
    'volume_costs': fees,
    'two_taker_long_break_even_price_gain_percent': str(2*RATE/(1-RATE)*100),
    'stop_0_25_percent_target_3R': {
        'round_trip_fee_R_approx': str(2*RATE/stop),
        'ideal_win_rate_new_1bps_percent': str(ideal_win_rate(RATE)*100),
        'ideal_win_rate_old_5bps_percent': str(ideal_win_rate(D('.0005'))*100),
        'excludes_slippage_spread_funding_and_execution_misses': True},
    'grid_fee_sensitivity': reprice, 'conditional_rebate_examples': rebates,
    'maker_offer_and_api_eligibility_are_unknown': True}
(HERE/'offer_economics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2))
```

</details>

<details>
<summary>offer_economics.json</summary>

```json
{
  "scope": "The partner offer is not independently verified. Arithmetic only, no new trading-edge proof.",
  "effective_taker_rate": "0.0001",
  "turnover_counts_both_legs_once": true,
  "volume_costs": [
    {
      "sum_of_execution_turnover": "10000",
      "effective_fee_after_rebate": "1.00"
    },
    {
      "sum_of_execution_turnover": "100000",
      "effective_fee_after_rebate": "10.00"
    },
    {
      "sum_of_execution_turnover": "1000000",
      "effective_fee_after_rebate": "100.00"
    },
    {
      "sum_of_execution_turnover": "10000000",
      "effective_fee_after_rebate": "1000.00"
    },
    {
      "sum_of_execution_turnover": "100000000",
      "effective_fee_after_rebate": "10000.00"
    }
  ],
  "two_taker_long_break_even_price_gain_percent": "0.0200020002000200020002000200020",
  "stop_0_25_percent_target_3R": {
    "round_trip_fee_R_approx": "0.08",
    "ideal_win_rate_new_1bps_percent": "27.0002000200020002000200020002",
    "ideal_win_rate_old_5bps_percent": "35.0050025012506253126563281641",
    "excludes_slippage_spread_funding_and_execution_misses": true
  },
  "grid_fee_sensitivity": [
    {
      "period": "2026-05-07 through 2026-10-05",
      "fixed_execution_turnover": "1061200.5538671608",
      "original_fee_rate": ".00016",
      "original_net": "-563.71",
      "fees_at_offer_rate": "106.12",
      "net_at_offer_rate_same_fills": "-500.04",
      "net_if_all_execution_fees_zero": "-393.92"
    },
    {
      "period": "Previously reviewed approx 10-month BTC run",
      "fixed_execution_turnover": "1415252.0460853628",
      "original_fee_rate": ".00016",
      "original_net": "-553.34",
      "fees_at_offer_rate": "141.53",
      "net_at_offer_rate_same_fills": "-468.42",
      "net_if_all_execution_fees_zero": "-326.90"
    }
  ],
  "conditional_rebate_examples": [
    {
      "gross_rate_scenario": "VIP5 published scenario",
      "gross_taker": "0.00048",
      "required_refund_share_for_1bps_taker": "0.791666666666666666666666666667",
      "gross_taker_fee_per_million": "480.00",
      "refund_per_million": "380.00",
      "hypothetical_maker_if_same_refund_share_applies": "0.0000333333333333333333333333333333",
      "hypothetical_maker_fee_per_million": "33.33"
    },
    {
      "gross_rate_scenario": "VIP8 published scenario",
      "gross_taker": "0.0004",
      "required_refund_share_for_1bps_taker": "0.75",
      "gross_taker_fee_per_million": "400.00",
      "refund_per_million": "300.00",
      "hypothetical_maker_if_same_refund_share_applies": "0.000025",
      "hypothetical_maker_fee_per_million": "25.00"
    }
  ],
  "maker_offer_and_api_eligibility_are_unknown": true
}
```

</details>

<details>
<summary>manual/reprice_manual.py</summary>

```python
"""Fee-only sensitivity of previously frozen journals; never edits the sources.

Only the effective commission changes from .0005 to .0001 per executed
notional. All entry/exit prices, slippage, stops and funding remain fixed.
The three descriptive reference cells are the previously highlighted 15m
impulse-follow z2.5 / 120-minute rules on BTC, ETH and XRP, not new winners.
"""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'research/expectancy_20261006/intraday'
PUBLIC = SOURCE.parent / 'public_data'
OLD_FEE = .0005
NEW_FEE = .0001
SLIP = .0002
STRESS_SLIP = .0004
SEED = 20261006
FIXED_NOTIONAL = 1000.


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(t, net, stress_net):
    x = np.asarray(net)
    z = np.asarray(stress_net)
    months = pd.DataFrame({'month': t.month, 'net': x}).groupby('month').agg(total=('net', 'sum'), n=('net', 'size'))
    vals = months.to_numpy()
    rng = np.random.default_rng(SEED)
    sel = rng.integers(0, len(vals), (4000, len(vals)))
    sums = vals[sel].sum(axis=1)
    ci = np.quantile(sums[:, 0] / sums[:, 1] * 100, [.025, .975])
    return {'n': len(t), 'net_usd': float(x.sum() * FIXED_NOTIONAL),
            'mean_net_pct': float(x.mean() * 100),
            'PF': float(x[x > 0].sum() / -x[x < 0].sum()) if (x < 0).any() else None,
            'monthly_CI95_mean_net_pct': ci.tolist(),
            'positive_CI': bool(ci[0] > 0),
            'stress_net_usd': float(z.sum() * FIXED_NOTIONAL),
            'stress_mean_net_pct': float(z.mean() * 100),
            'funding_usd_unchanged': float(t.funding_return.sum() * FIXED_NOTIONAL) if 'funding_return' in t else 0.,
            'median_hold_minutes': float(t.duration.median())}


def funding_stress(t, symbol):
    f = pd.read_csv(PUBLIC / f'binance_futures_{symbol}_funding.csv').sort_values('fundingTime')
    marks = pd.to_numeric(f.markPrice).to_numpy()
    assert np.all(np.isfinite(marks) & (marks > 0)), 'Missing marks require exact original proxy source.'
    fx = f.fundingTime.to_numpy()
    prefix = np.r_[0., np.cumsum(f.fundingRate.to_numpy() * marks)]
    ts0 = pd.Timestamp('2026-05-07', tz='UTC').value // 1000000
    a = np.searchsorted(fx, ts0 + t.entry_ix.to_numpy() * 60000, side='right')
    b = np.searchsorted(fx, ts0 + t.stress_exit_ix.to_numpy() * 60000, side='right')
    stress_entry = t.entry_mid.to_numpy() * (1 + t.side.to_numpy() * STRESS_SLIP)
    return -t.side.to_numpy() / stress_entry * (prefix[b] - prefix[a])


def reprice(t, symbol, fresh):
    ratio = t.exit_mid.to_numpy() * (1 - t.side.to_numpy() * SLIP) / t.entry_exec.to_numpy()
    original = t.side.to_numpy() * (ratio - 1) - OLD_FEE * (1 + ratio)
    funding = t.funding_return.to_numpy() if fresh else np.zeros(len(t))
    assert np.max(abs(original + funding - t.net.to_numpy())) < 1e-13
    new = t.net.to_numpy() + (OLD_FEE - NEW_FEE) * (1 + ratio)
    direct = t.side.to_numpy() * (ratio - 1) - NEW_FEE * (1 + ratio) + funding
    assert np.max(abs(direct - new)) < 1e-13
    # Invert the original stress PnL formula after stripping its own funding.
    stress_funding = funding_stress(t, symbol) if fresh else np.zeros(len(t))
    sr = (t.stress_net.to_numpy() - stress_funding + t.side.to_numpy() + OLD_FEE) / (t.side.to_numpy() - OLD_FEE)
    assert np.all(sr > 0)
    stress_new = t.stress_net.to_numpy() + (OLD_FEE - NEW_FEE) * (1 + sr)
    return new, stress_new, ratio


def run():
    rows = []
    sources = []
    for path in sorted(SOURCE.glob('trades_*.csv')):
        name = path.stem.removeprefix('trades_')
        symbol = name.split('_')[0]
        fresh_path = SOURCE / f'fresh_trades_{name}.csv'
        old = pd.read_csv(path)
        fresh = pd.read_csv(fresh_path)
        old_net, old_stress, _ = reprice(old, symbol, False)
        fresh_net, fresh_stress, ratio = reprice(fresh, symbol, True)
        original_old = stats(old, old.net.to_numpy(), old.stress_net.to_numpy())
        original_fresh = stats(fresh, fresh.net.to_numpy(), fresh.stress_net.to_numpy())
        thirds = {}
        for segment in ['train', 'validation', 'test']:
            ix = old.segment.eq(segment).to_numpy()
            thirds[segment] = stats(old[ix], old_net[ix], old_stress[ix])
        row = {'name': name, 'old_full': stats(old, old_net, old_stress),
               'old_thirds': thirds, 'fresh': stats(fresh, fresh_net, fresh_stress),
               'original_old': original_old, 'original_fresh': original_fresh,
               'actual_fresh_turnover_usd': float(FIXED_NOTIONAL * (1 + ratio).sum()),
               'fees_new_usd': float(NEW_FEE * FIXED_NOTIONAL * (1 + ratio).sum())}
        row['passes_economic_period_gate'] = bool(row['old_full']['net_usd'] > 0 and row['fresh']['net_usd'] > 0 and row['fresh']['positive_CI'] and all(v['net_usd'] > 0 for v in thirds.values()) and row['fresh']['stress_net_usd'] > 0)
        rows.append(row)
        sources.extend([{'path': str(path), 'sha256': sha(path)}, {'path': str(fresh_path), 'sha256': sha(fresh_path)}])
    assert len(rows) == 36
    references = [r for r in rows if '_intraday_impulse_follow_z2.5_h120' in r['name']]
    additional_sources = [SOURCE / 'spec.json', SOURCE / 'run_intraday.py', SOURCE / 'validate_fresh.py', SOURCE / 'fresh_audit.json']
    for symbol in ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']:
        additional_sources.extend([PUBLIC / f'binance_futures_{symbol}_funding.csv', PUBLIC / f'binance_futures_{symbol}_1m.csv'])
    sources.extend({'path': str(path), 'sha256': sha(path)} for path in additional_sources)
    results = {'scope': 'Fee sensitivity only; reused historical windows are not new OOS or WEEX execution evidence.',
               'old_fee_per_leg': OLD_FEE, 'new_effective_fee_per_leg': NEW_FEE,
               'slippage_per_leg_unchanged': SLIP, 'stress_slippage_per_leg_unchanged': STRESS_SLIP,
               'fixed_entry_notional_usd': FIXED_NOTIONAL, 'bootstrap_reps': 4000, 'bootstrap_seed': SEED,
               'altered_signals_or_exits': False, 'reoptimized_parameters': False,
               'drawdown_repriced': False,
               'old_windows': '2024-03-13 through 2026-05-07; spot proxy, chronological thirds',
               'fresh_window': '2026-05-07 through 2026-10-05; Binance USD-M with actual funding',
               'gate_counts': {'old_full_positive': sum(r['old_full']['net_usd'] > 0 for r in rows),
                               'old_test_positive': sum(r['old_thirds']['test']['net_usd'] > 0 for r in rows),
                               'fresh_positive': sum(r['fresh']['net_usd'] > 0 for r in rows),
                               'fresh_positive_CI': sum(r['fresh']['positive_CI'] for r in rows),
                               'economic_period_gate_passes': sum(r['passes_economic_period_gate'] for r in rows)},
               'descriptive_reference_cells': references, 'all_frozen_cells': rows, 'sources': sources}
    (OUT / 'manual_fee_sensitivity.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({'gate_counts': results['gate_counts'], 'references': references}, indent=2), flush=True)
    return results


if __name__ == '__main__':
    run()
```

</details>

<details>
<summary>manual/reprice_controls.py</summary>

```python
"""Replay the original 64 placebo draws for three previously shown references.

No searches or changes to strategy/exit/slippage/funding. Effective fee alone
changes. Original control outputs are checked after undoing this fee change.
"""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'research/expectancy_20261006/intraday'
sys.path.insert(0, str(SOURCE))
import run_intraday as lab
from validate_fresh import add_funding


def main():
    p = OUT / 'manual_fee_sensitivity.json'
    result = json.loads(p.read_text(encoding='utf-8'))
    original_controls = pd.read_csv(SOURCE / 'fresh_placebos.csv')
    lab.SPEC['fee_side'] = .0001
    f = next(f for f in lab.SPEC['families'] if f['family'] == 'intraday_impulse_follow')
    control_rows = []
    for r in result['descriptive_reference_cells']:
        name = r['name']
        symbol = name.split('_')[0]
        d = pd.read_csv(SOURCE.parent / 'public_data' / f'binance_futures_{symbol}_1m.csv')
        # Original pandas 2.3 uses nanosecond datetime integers; pandas 3 defaults
        # to microseconds. Preserve the original event builder's units explicitly.
        d['dt'] = pd.to_datetime(d.ts, unit='ms', utc=True).dt.as_unit('ns')
        funding = pd.read_csv(SOURCE.parent / 'public_data' / f'binance_futures_{symbol}_funding.csv').sort_values('fundingTime').reset_index(drop=True)
        events = lab.build_events(d, f, 2.5)
        segments = [(0, len(d))]
        t, _ = lab.simulate(d, events, f, 120, segments, lean=False)
        t, _, _ = add_funding(d, t, None, funding)
        old_journal = pd.read_csv(SOURCE / f'fresh_trades_{name}.csv')
        assert np.array_equal(t.entry_ix, old_journal.entry_ix)
        assert np.array_equal(t.exit_ix, old_journal.exit_ix)
        assert abs(t.net.sum() * 1000 - r['fresh']['net_usd']) < 1e-8
        assert abs(t.stress_net.sum() * 1000 - r['fresh']['stress_net_usd']) < 1e-8
        rng = np.random.default_rng(lab.SPEC['seed'])
        draw = accepted = 0
        null = []
        gross_max_error = net_max_error = 0.
        while accepted < 64 and draw < 192:
            draw += 1
            pe, shift = lab.shifted_events(events, segments, rng)
            pt, _ = lab.simulate(d, pe, f, 120, segments, lean=True)
            if abs(len(pt) / len(t) - 1) > .02:
                continue
            pt, _, _ = add_funding(d, pt, None, funding)
            accepted += 1
            orig = original_controls[(original_controls.name == name) & (original_controls.draw == accepted)].iloc[0]
            assert len(pt) == int(orig.n)
            assert str(shift) == orig.shift_weeks
            ratio = pt.exit_mid * (1 - pt.side * lab.SPEC['slip_base_side']) / pt.entry_exec
            undone = pt.net - (.0005 - .0001) * (1 + ratio)
            gross_err = abs(pt.gross.mean() * 100 - orig.gross_avg_pct)
            net_err = abs(undone.mean() * 100 - orig.net_avg_pct)
            gross_max_error = max(gross_max_error, float(gross_err))
            net_max_error = max(net_max_error, float(net_err))
            assert gross_err < 1e-11 and net_err < 1e-11
            avg = float(pt.net.mean() * 100)
            null.append(avg)
            control_rows.append({'name': name, 'draw': accepted, 'shift_weeks': shift,
                                 'n': len(pt), 'new_mean_net_pct': avg,
                                 'old_mean_net_pct_verified': float(undone.mean() * 100)})
        assert accepted == 64
        pv = {'replicates': accepted, 'one_sided_p_expectancy_unadjusted': (1 + sum(x >= r['fresh']['mean_net_pct'] for x in null)) / (1 + accepted),
              'median_mean_net_pct': float(np.median(null)),
              'same_original_draws_verified': True,
              'max_old_net_reproduction_error_pp': net_max_error,
              'max_old_gross_reproduction_error_pp': gross_max_error}
        r['repriced_fresh_placebo'] = pv
        for all_r in result['all_frozen_cells']:
            if all_r['name'] == name:
                all_r['repriced_fresh_placebo'] = pv
        print(json.dumps({'name': name, 'placebo': pv}), flush=True)
    result['controls_repriced_scope'] = 'Original 64 accepted fresh draws on the three previously described z2.5/120 reference cells; no new search.'
    result['verification'] = {'base_and_stress_reference_cash_match_original_engine_at_new_fee': True,
                              'original_control_draws_and_old_fee_results_reproduced': True}
    p.write_text(json.dumps(result, indent=2), encoding='utf-8')
    (OUT / 'manual_placebo_sensitivity.json').write_text(json.dumps(control_rows, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
```

</details>

<details>
<summary>manual/manual_fee_sensitivity.json</summary>

```json
{
  "scope": "Fee sensitivity only; reused historical windows are not new OOS or WEEX execution evidence.",
  "old_fee_per_leg": 0.0005,
  "new_effective_fee_per_leg": 0.0001,
  "slippage_per_leg_unchanged": 0.0002,
  "stress_slippage_per_leg_unchanged": 0.0004,
  "fixed_entry_notional_usd": 1000.0,
  "bootstrap_reps": 4000,
  "bootstrap_seed": 20261006,
  "altered_signals_or_exits": false,
  "reoptimized_parameters": false,
  "drawdown_repriced": false,
  "old_windows": "2024-03-13 through 2026-05-07; spot proxy, chronological thirds",
  "fresh_window": "2026-05-07 through 2026-10-05; Binance USD-M with actual funding",
  "gate_counts": {
    "old_full_positive": 2,
    "old_test_positive": 4,
    "fresh_positive": 3,
    "fresh_positive_CI": 0,
    "economic_period_gate_passes": 0
  },
  "descriptive_reference_cells": [
    {
      "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
      "old_full": {
        "n": 829,
        "net_usd": -225.2556042957135,
        "mean_net_pct": -0.027171966742546863,
        "PF": 0.9248033495667529,
        "monthly_CI95_mean_net_pct": [
          -0.09024468563295937,
          0.03654316742405312
        ],
        "positive_CI": false,
        "stress_net_usd": -550.6880925796413,
        "stress_mean_net_pct": -0.06642799669235722,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "old_thirds": {
        "train": {
          "n": 305,
          "net_usd": -140.72296545352197,
          "mean_net_pct": -0.04613867719787606,
          "PF": 0.8806794821038407,
          "monthly_CI95_mean_net_pct": [
            -0.18148236699315348,
            0.1013104069615925
          ],
          "positive_CI": false,
          "stress_net_usd": -253.7117578966049,
          "stress_mean_net_pct": -0.08318418291691963,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "validation": {
          "n": 258,
          "net_usd": -8.0058409631572,
          "mean_net_pct": -0.0031030391330066666,
          "PF": 0.991254625890475,
          "monthly_CI95_mean_net_pct": [
            -0.06473903161121804,
            0.05763944892978642
          ],
          "positive_CI": false,
          "stress_net_usd": -131.83802739570527,
          "stress_mean_net_pct": -0.05110001061849041,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "test": {
          "n": 266,
          "net_usd": -76.52679787903432,
          "mean_net_pct": -0.02876947288685501,
          "PF": 0.9150407498283458,
          "monthly_CI95_mean_net_pct": [
            -0.126454495099587,
            0.057235688282623945
          ],
          "positive_CI": false,
          "stress_net_usd": -165.1383072873313,
          "stress_mean_net_pct": -0.06208207040877115,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        }
      },
      "fresh": {
        "n": 158,
        "net_usd": 15.64373461364408,
        "mean_net_pct": 0.009901097856736759,
        "PF": 1.0348366065361847,
        "monthly_CI95_mean_net_pct": [
          -0.10024805897283484,
          0.07686632358281338
        ],
        "positive_CI": false,
        "stress_net_usd": -50.00320073781803,
        "stress_mean_net_pct": -0.031647595403682297,
        "funding_usd_unchanged": -0.17068623043223466,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 829,
        "net_usd": -888.2896688618426,
        "mean_net_pct": -0.10715195040552987,
        "PF": 0.7376235438235845,
        "monthly_CI95_mean_net_pct": [
          -0.17023390429518212,
          -0.043408926599885815
        ],
        "positive_CI": false,
        "stress_net_usd": -1213.731487993857,
        "stress_mean_net_pct": -0.1464091059099948,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "original_fresh": {
        "n": 158,
        "net_usd": -110.7815961374255,
        "mean_net_pct": -0.07011493426419335,
        "PF": 0.7868424204334128,
        "monthly_CI95_mean_net_pct": [
          -0.18026172278510466,
          -0.003120481249900618
        ],
        "positive_CI": false,
        "stress_net_usd": -176.4317911527685,
        "stress_mean_net_pct": -0.11166569060301805,
        "funding_usd_unchanged": -0.17068623043223466,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 316063.326877674,
      "fees_new_usd": 31.606332687767395,
      "passes_economic_period_gate": false,
      "repriced_fresh_placebo": {
        "replicates": 64,
        "one_sided_p_expectancy_unadjusted": 0.046153846153846156,
        "median_mean_net_pct": -0.07894116426502606,
        "same_original_draws_verified": true,
        "max_old_net_reproduction_error_pp": 8.326672684688674e-17,
        "max_old_gross_reproduction_error_pp": 8.673617379884035e-17
      }
    },
    {
      "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
      "old_full": {
        "n": 892,
        "net_usd": 104.98703978592266,
        "mean_net_pct": 0.011769847509632586,
        "PF": 1.027272320430587,
        "monthly_CI95_mean_net_pct": [
          -0.04530296556512879,
          0.06799838026633027
        ],
        "positive_CI": false,
        "stress_net_usd": -222.08348910389202,
        "stress_mean_net_pct": -0.024897252141691934,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 86.5
      },
      "old_thirds": {
        "train": {
          "n": 308,
          "net_usd": -30.26024780069556,
          "mean_net_pct": -0.00982475577944661,
          "PF": 0.9771250399964024,
          "monthly_CI95_mean_net_pct": [
            -0.07710816614316948,
            0.054041749239703486
          ],
          "positive_CI": false,
          "stress_net_usd": -130.62079162147398,
          "stress_mean_net_pct": -0.04240934792905,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 98.5
        },
        "validation": {
          "n": 302,
          "net_usd": -35.71789561210753,
          "mean_net_pct": -0.011827117752353487,
          "PF": 0.974875986657529,
          "monthly_CI95_mean_net_pct": [
            -0.13093235849418006,
            0.1024680053223603
          ],
          "positive_CI": false,
          "stress_net_usd": -146.80391532694534,
          "stress_mean_net_pct": -0.04861056798905475,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 69.5
        },
        "test": {
          "n": 282,
          "net_usd": 170.96518319872584,
          "mean_net_pct": 0.060625951488909875,
          "PF": 1.1547106722112574,
          "monthly_CI95_mean_net_pct": [
            -0.05028590159091082,
            0.1715898787369717
          ],
          "positive_CI": false,
          "stress_net_usd": 55.34121784452739,
          "stress_mean_net_pct": 0.01962454533493879,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 110.0
        }
      },
      "fresh": {
        "n": 174,
        "net_usd": 9.658720192146655,
        "mean_net_pct": 0.005550988616176238,
        "PF": 1.0163191748055418,
        "monthly_CI95_mean_net_pct": [
          -0.09076410632013733,
          0.10798769389333707
        ],
        "positive_CI": false,
        "stress_net_usd": -59.51168644460386,
        "stress_mean_net_pct": -0.03420211864632406,
        "funding_usd_unchanged": -0.3855445737811441,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 892,
        "net_usd": -608.6345353122842,
        "mean_net_pct": -0.06823257122335026,
        "PF": 0.8578100471128932,
        "monthly_CI95_mean_net_pct": [
          -0.12533185784523834,
          -0.011977562766894559
        ],
        "positive_CI": false,
        "stress_net_usd": -935.7283818905262,
        "stress_mean_net_pct": -0.10490228496530561,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 86.5
      },
      "original_fresh": {
        "n": 174,
        "net_usd": -129.50033749981367,
        "mean_net_pct": -0.07442548132173199,
        "PF": 0.8063328422492666,
        "monthly_CI95_mean_net_pct": [
          -0.1707722731803811,
          0.028049024289328307
        ],
        "positive_CI": false,
        "stress_net_usd": -198.66481803856647,
        "stress_mean_net_pct": -0.11417518278078534,
        "funding_usd_unchanged": -0.3855445737811441,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 347897.6442299007,
      "fees_new_usd": 34.78976442299007,
      "passes_economic_period_gate": false,
      "repriced_fresh_placebo": {
        "replicates": 64,
        "one_sided_p_expectancy_unadjusted": 0.015384615384615385,
        "median_mean_net_pct": -0.10927632259852858,
        "same_original_draws_verified": true,
        "max_old_net_reproduction_error_pp": 1.1102230246251565e-16,
        "max_old_gross_reproduction_error_pp": 9.71445146547012e-17
      }
    },
    {
      "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
      "old_full": {
        "n": 781,
        "net_usd": -878.9144049515654,
        "mean_net_pct": -0.11253705569162167,
        "PF": 0.7766107025319952,
        "monthly_CI95_mean_net_pct": [
          -0.16941009647330812,
          -0.057063142206467535
        ],
        "positive_CI": false,
        "stress_net_usd": -1166.5910236461277,
        "stress_mean_net_pct": -0.14937144989066933,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 55.0
      },
      "old_thirds": {
        "train": {
          "n": 255,
          "net_usd": -371.39505365892603,
          "mean_net_pct": -0.14564511908193178,
          "PF": 0.7015257494567018,
          "monthly_CI95_mean_net_pct": [
            -0.2584579579771812,
            -0.046795104715390515
          ],
          "positive_CI": false,
          "stress_net_usd": -444.4155545746617,
          "stress_mean_net_pct": -0.17428060963712225,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 86.0
        },
        "validation": {
          "n": 274,
          "net_usd": -413.0286184782914,
          "mean_net_pct": -0.1507403717074056,
          "PF": 0.7357579368787156,
          "monthly_CI95_mean_net_pct": [
            -0.24011593545439844,
            -0.06961081911525685
          ],
          "positive_CI": false,
          "stress_net_usd": -507.8235876312551,
          "stress_mean_net_pct": -0.18533707577783035,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "test": {
          "n": 252,
          "net_usd": -94.49073281434778,
          "mean_net_pct": -0.037496322545376104,
          "PF": 0.9161625497164819,
          "monthly_CI95_mean_net_pct": [
            -0.11981657341997241,
            0.03857359039832935
          ],
          "positive_CI": false,
          "stress_net_usd": -214.35188144021072,
          "stress_mean_net_pct": -0.08506027041278202,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 89.5
        }
      },
      "fresh": {
        "n": 154,
        "net_usd": 7.1811259377766685,
        "mean_net_pct": 0.004663068790764071,
        "PF": 1.0117361951772492,
        "monthly_CI95_mean_net_pct": [
          -0.1363666503038029,
          0.13254159367047058
        ],
        "positive_CI": false,
        "stress_net_usd": -48.35264185265413,
        "stress_mean_net_pct": -0.03139781938484035,
        "funding_usd_unchanged": -0.11690903564977556,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 781,
        "net_usd": -1503.7093038292512,
        "mean_net_pct": -0.19253640253895662,
        "PF": 0.6537693539017022,
        "monthly_CI95_mean_net_pct": [
          -0.24940557397163549,
          -0.13708774047813102
        ],
        "positive_CI": false,
        "stress_net_usd": -1791.3600377798132,
        "stress_mean_net_pct": -0.22936748243019373,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 55.0
      },
      "original_fresh": {
        "n": 154,
        "net_usd": -116.08384215528712,
        "mean_net_pct": -0.07537911828265396,
        "PF": 0.8292571030871028,
        "monthly_CI95_mean_net_pct": [
          -0.21635799471166461,
          0.052520892345902105
        ],
        "positive_CI": false,
        "stress_net_usd": -171.61379177174757,
        "stress_mean_net_pct": -0.11143752712451142,
        "funding_usd_unchanged": -0.11690903564977556,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 308162.42023265944,
      "fees_new_usd": 30.816242023265943,
      "passes_economic_period_gate": false,
      "repriced_fresh_placebo": {
        "replicates": 64,
        "one_sided_p_expectancy_unadjusted": 0.015384615384615385,
        "median_mean_net_pct": -0.04136107509295253,
        "same_original_draws_verified": true,
        "max_old_net_reproduction_error_pp": 1.249000902703301e-16,
        "max_old_gross_reproduction_error_pp": 9.8879238130678e-17
      }
    }
  ],
  "all_frozen_cells": [
    {
      "name": "BTCUSDT_intraday_impulse_fade_control_z2.5_h120",
      "old_full": {
        "n": 829,
        "net_usd": -693.76781943095,
        "mean_net_pct": -0.08368731235596502,
        "PF": 0.781804887780697,
        "monthly_CI95_mean_net_pct": [
          -0.1399279788334351,
          -0.02377817673379137
        ],
        "positive_CI": false,
        "stress_net_usd": -1003.0844029521157,
        "stress_mean_net_pct": -0.12099932484343978,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "old_thirds": {
        "train": {
          "n": 305,
          "net_usd": -168.1122846628111,
          "mean_net_pct": -0.05511878185665938,
          "PF": 0.8529939480767605,
          "monthly_CI95_mean_net_pct": [
            -0.1807659770717864,
            0.06395427612526407
          ],
          "positive_CI": false,
          "stress_net_usd": -268.5373855030762,
          "stress_mean_net_pct": -0.0880450444272381,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "validation": {
          "n": 258,
          "net_usd": -302.0380632542808,
          "mean_net_pct": -0.1170690167652251,
          "PF": 0.7160822403448893,
          "monthly_CI95_mean_net_pct": [
            -0.18543171766369757,
            -0.05813951489845687
          ],
          "positive_CI": false,
          "stress_net_usd": -395.08725305624665,
          "stress_mean_net_pct": -0.15313459420784753,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "test": {
          "n": 266,
          "net_usd": -223.61747151385805,
          "mean_net_pct": -0.08406671861423234,
          "PF": 0.769983271370413,
          "monthly_CI95_mean_net_pct": [
            -0.16621673139734375,
            0.005438148108993294
          ],
          "positive_CI": false,
          "stress_net_usd": -339.4597643927928,
          "stress_mean_net_pct": -0.1276164527792454,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        }
      },
      "fresh": {
        "n": 158,
        "net_usd": -199.79278371763067,
        "mean_net_pct": -0.1264511289352093,
        "PF": 0.6383583698646507,
        "monthly_CI95_mean_net_pct": [
          -0.2160326808431662,
          0.015941290336709008
        ],
        "positive_CI": false,
        "stress_net_usd": -253.0059719799227,
        "stress_mean_net_pct": -0.1601303620126093,
        "funding_usd_unchanged": 0.011594909994571936,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 829,
        "net_usd": -1356.7876935225393,
        "mean_net_pct": -0.1636655842608612,
        "PF": 0.617873594878155,
        "monthly_CI95_mean_net_pct": [
          -0.21989505362677583,
          -0.1037572031173143
        ],
        "positive_CI": false,
        "stress_net_usd": -1666.114712334078,
        "stress_mean_net_pct": -0.20097885552883932,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "original_fresh": {
        "n": 158,
        "net_usd": -326.2083105275221,
        "mean_net_pct": -0.20646095603007725,
        "PF": 0.48181399718256224,
        "monthly_CI95_mean_net_pct": [
          -0.29604479927422517,
          -0.06405921337170606
        ],
        "positive_CI": false,
        "stress_net_usd": -379.4189445188249,
        "stress_mean_net_pct": -0.24013857248026896,
        "funding_usd_unchanged": 0.011594909994571936,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 316038.81702472834,
      "fees_new_usd": 31.603881702472837,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_intraday_impulse_fade_control_z2.5_h60",
      "old_full": {
        "n": 829,
        "net_usd": -763.9222409914987,
        "mean_net_pct": -0.09214984812925196,
        "PF": 0.7198635459099952,
        "monthly_CI95_mean_net_pct": [
          -0.14648246528034173,
          -0.03416259737701789
        ],
        "positive_CI": false,
        "stress_net_usd": -1079.1953841419286,
        "stress_mean_net_pct": -0.13018038409432192,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 305,
          "net_usd": -248.4810737973094,
          "mean_net_pct": -0.081469204523708,
          "PF": 0.7464001081310221,
          "monthly_CI95_mean_net_pct": [
            -0.19051035105879308,
            0.020194082417642777
          ],
          "positive_CI": false,
          "stress_net_usd": -353.7505633273921,
          "stress_mean_net_pct": -0.11598379125488266,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 258,
          "net_usd": -281.59314016500525,
          "mean_net_pct": -0.10914462797093226,
          "PF": 0.6897360477868579,
          "monthly_CI95_mean_net_pct": [
            -0.18251519538729105,
            -0.034893239542171245
          ],
          "positive_CI": false,
          "stress_net_usd": -383.2383566362345,
          "stress_mean_net_pct": -0.14854199869621493,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 266,
          "net_usd": -233.8480270291841,
          "mean_net_pct": -0.08791279211623462,
          "PF": 0.7214626630357257,
          "monthly_CI95_mean_net_pct": [
            -0.16939056878433875,
            0.017139830668645644
          ],
          "positive_CI": false,
          "stress_net_usd": -342.20646417830204,
          "stress_mean_net_pct": -0.1286490466835722,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 158,
        "net_usd": -176.65305072715694,
        "mean_net_pct": -0.11180572830832716,
        "PF": 0.6015382650110312,
        "monthly_CI95_mean_net_pct": [
          -0.18254985964253023,
          -0.010992323214992104
        ],
        "positive_CI": false,
        "stress_net_usd": -234.85193836680872,
        "stress_mean_net_pct": -0.14864046732076502,
        "funding_usd_unchanged": -0.10665927811185894,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 829,
        "net_usd": -1427.0400900129198,
        "mean_net_pct": -0.17213993848165499,
        "PF": 0.5412643422832241,
        "monthly_CI95_mean_net_pct": [
          -0.22646422562566892,
          -0.11416669103313548
        ],
        "positive_CI": false,
        "stress_net_usd": -1742.3146979017495,
        "stress_mean_net_pct": -0.2101706511341073,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 158,
        "net_usd": -303.056323027258,
        "mean_net_pct": -0.1918077993843405,
        "PF": 0.4231522074084022,
        "monthly_CI95_mean_net_pct": [
          -0.2625312153150326,
          -0.09094873491704131
        ],
        "positive_CI": false,
        "stress_net_usd": -361.2527419214966,
        "stress_mean_net_pct": -0.22864097589968138,
        "funding_usd_unchanged": -0.10665927811185894,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 316008.18075025256,
      "fees_new_usd": 31.60081807502526,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_intraday_impulse_fade_control_z2_h120",
      "old_full": {
        "n": 1073,
        "net_usd": -746.2565731394188,
        "mean_net_pct": -0.06954860886667465,
        "PF": 0.8159869317366739,
        "monthly_CI95_mean_net_pct": [
          -0.11483497811487514,
          -0.0256097263851653
        ],
        "positive_CI": false,
        "stress_net_usd": -1162.3642250229382,
        "stress_mean_net_pct": -0.10832844594808372,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "old_thirds": {
        "train": {
          "n": 391,
          "net_usd": -220.44941277410578,
          "mean_net_pct": -0.05638092398314726,
          "PF": 0.8503210794555365,
          "monthly_CI95_mean_net_pct": [
            -0.14534118253366435,
            0.035076025343020185
          ],
          "positive_CI": false,
          "stress_net_usd": -371.88123941898175,
          "stress_mean_net_pct": -0.09511029141150429,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "validation": {
          "n": 338,
          "net_usd": -342.605599946867,
          "mean_net_pct": -0.10136260353457603,
          "PF": 0.7503498700071327,
          "monthly_CI95_mean_net_pct": [
            -0.16974968915771854,
            -0.04135301968966802
          ],
          "positive_CI": false,
          "stress_net_usd": -456.02383255860764,
          "stress_mean_net_pct": -0.1349182936563928,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "test": {
          "n": 344,
          "net_usd": -183.20156041844604,
          "mean_net_pct": -0.053256267563501755,
          "PF": 0.8486307672397342,
          "monthly_CI95_mean_net_pct": [
            -0.12322051684518706,
            0.002497728632957724
          ],
          "positive_CI": false,
          "stress_net_usd": -334.4591530453491,
          "stress_mean_net_pct": -0.09722649797829916,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        }
      },
      "fresh": {
        "n": 214,
        "net_usd": -209.46939437615336,
        "mean_net_pct": -0.09788289456829596,
        "PF": 0.6989560349566281,
        "monthly_CI95_mean_net_pct": [
          -0.21098407448437723,
          0.01123991469119504
        ],
        "positive_CI": false,
        "stress_net_usd": -304.6834157041296,
        "stress_mean_net_pct": -0.14237542789912594,
        "funding_usd_unchanged": 0.3552090229011924,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 1073,
        "net_usd": -1604.5010586153812,
        "mean_net_pct": -0.14953411543479786,
        "PF": 0.64628586791813,
        "monthly_CI95_mean_net_pct": [
          -0.19481703866166614,
          -0.1056163135190972
        ],
        "positive_CI": false,
        "stress_net_usd": -2020.6287721879862,
        "stress_mean_net_pct": -0.1883158221983212,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "original_fresh": {
        "n": 214,
        "net_usd": -380.6666789200333,
        "mean_net_pct": -0.17788162566356697,
        "PF": 0.5231557759120843,
        "monthly_CI95_mean_net_pct": [
          -0.2909777668225631,
          -0.06876420602321127
        ],
        "positive_CI": false,
        "stress_net_usd": -475.8864608123974,
        "stress_mean_net_pct": -0.22237685084691466,
        "funding_usd_unchanged": 0.3552090229011924,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 427993.2113596999,
      "fees_new_usd": 42.79932113596999,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_intraday_impulse_fade_control_z2_h60",
      "old_full": {
        "n": 1073,
        "net_usd": -771.1026150467429,
        "mean_net_pct": -0.07186417661199841,
        "PF": 0.7693350120438838,
        "monthly_CI95_mean_net_pct": [
          -0.1109432913989692,
          -0.032235211337267033
        ],
        "positive_CI": false,
        "stress_net_usd": -1200.5130096014063,
        "stress_mean_net_pct": -0.11188378467860265,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 391,
          "net_usd": -262.5260051382403,
          "mean_net_pct": -0.067142200802619,
          "PF": 0.7840712036930756,
          "monthly_CI95_mean_net_pct": [
            -0.13689976106015128,
            -0.0005901223201933372
          ],
          "positive_CI": false,
          "stress_net_usd": -424.8884166585188,
          "stress_mean_net_pct": -0.10866711423491529,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 338,
          "net_usd": -239.77531576035003,
          "mean_net_pct": -0.07093944253264793,
          "PF": 0.7838864804430077,
          "monthly_CI95_mean_net_pct": [
            -0.15277700338507608,
            0.006027504867579414
          ],
          "positive_CI": false,
          "stress_net_usd": -364.3670155348653,
          "stress_mean_net_pct": -0.10780089217007847,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 344,
          "net_usd": -268.8012941481526,
          "mean_net_pct": -0.07813991108957924,
          "PF": 0.7358654285200754,
          "monthly_CI95_mean_net_pct": [
            -0.12425815336354779,
            -0.029104329278822085
          ],
          "positive_CI": false,
          "stress_net_usd": -411.2575774080223,
          "stress_mean_net_pct": -0.11955162133954138,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 214,
        "net_usd": -127.6197265073404,
        "mean_net_pct": -0.059635386218383366,
        "PF": 0.7612553170510533,
        "monthly_CI95_mean_net_pct": [
          -0.1197908068409625,
          -0.0013369277104769179
        ],
        "positive_CI": false,
        "stress_net_usd": -223.30985275092547,
        "stress_mean_net_pct": -0.10435039848174087,
        "funding_usd_unchanged": -0.018195142293758387,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 1073,
        "net_usd": -1629.385361115859,
        "mean_net_pct": -0.15185324893903626,
        "PF": 0.5738123687007193,
        "monthly_CI95_mean_net_pct": [
          -0.19091239374842636,
          -0.11223830593882496
        ],
        "positive_CI": false,
        "stress_net_usd": -2058.808792028745,
        "stress_mean_net_pct": -0.19187407195048878,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 214,
        "net_usd": -298.83594090390187,
        "mean_net_pct": -0.13964296303920648,
        "PF": 0.5304148257205601,
        "monthly_CI95_mean_net_pct": [
          -0.19978940879159776,
          -0.08137878809120071
        ],
        "positive_CI": false,
        "stress_net_usd": -394.5315419733329,
        "stress_mean_net_pct": -0.18436053363239854,
        "funding_usd_unchanged": -0.018195142293758387,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 428040.5359914037,
      "fees_new_usd": 42.80405359914037,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
      "old_full": {
        "n": 829,
        "net_usd": -225.2556042957135,
        "mean_net_pct": -0.027171966742546863,
        "PF": 0.9248033495667529,
        "monthly_CI95_mean_net_pct": [
          -0.09024468563295937,
          0.03654316742405312
        ],
        "positive_CI": false,
        "stress_net_usd": -550.6880925796413,
        "stress_mean_net_pct": -0.06642799669235722,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "old_thirds": {
        "train": {
          "n": 305,
          "net_usd": -140.72296545352197,
          "mean_net_pct": -0.04613867719787606,
          "PF": 0.8806794821038407,
          "monthly_CI95_mean_net_pct": [
            -0.18148236699315348,
            0.1013104069615925
          ],
          "positive_CI": false,
          "stress_net_usd": -253.7117578966049,
          "stress_mean_net_pct": -0.08318418291691963,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "validation": {
          "n": 258,
          "net_usd": -8.0058409631572,
          "mean_net_pct": -0.0031030391330066666,
          "PF": 0.991254625890475,
          "monthly_CI95_mean_net_pct": [
            -0.06473903161121804,
            0.05763944892978642
          ],
          "positive_CI": false,
          "stress_net_usd": -131.83802739570527,
          "stress_mean_net_pct": -0.05110001061849041,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "test": {
          "n": 266,
          "net_usd": -76.52679787903432,
          "mean_net_pct": -0.02876947288685501,
          "PF": 0.9150407498283458,
          "monthly_CI95_mean_net_pct": [
            -0.126454495099587,
            0.057235688282623945
          ],
          "positive_CI": false,
          "stress_net_usd": -165.1383072873313,
          "stress_mean_net_pct": -0.06208207040877115,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        }
      },
      "fresh": {
        "n": 158,
        "net_usd": 15.64373461364408,
        "mean_net_pct": 0.009901097856736759,
        "PF": 1.0348366065361847,
        "monthly_CI95_mean_net_pct": [
          -0.10024805897283484,
          0.07686632358281338
        ],
        "positive_CI": false,
        "stress_net_usd": -50.00320073781803,
        "stress_mean_net_pct": -0.031647595403682297,
        "funding_usd_unchanged": -0.17068623043223466,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 829,
        "net_usd": -888.2896688618426,
        "mean_net_pct": -0.10715195040552987,
        "PF": 0.7376235438235845,
        "monthly_CI95_mean_net_pct": [
          -0.17023390429518212,
          -0.043408926599885815
        ],
        "positive_CI": false,
        "stress_net_usd": -1213.731487993857,
        "stress_mean_net_pct": -0.1464091059099948,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "original_fresh": {
        "n": 158,
        "net_usd": -110.7815961374255,
        "mean_net_pct": -0.07011493426419335,
        "PF": 0.7868424204334128,
        "monthly_CI95_mean_net_pct": [
          -0.18026172278510466,
          -0.003120481249900618
        ],
        "positive_CI": false,
        "stress_net_usd": -176.4317911527685,
        "stress_mean_net_pct": -0.11166569060301805,
        "funding_usd_unchanged": -0.17068623043223466,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 316063.326877674,
      "fees_new_usd": 31.606332687767395,
      "passes_economic_period_gate": false,
      "repriced_fresh_placebo": {
        "replicates": 64,
        "one_sided_p_expectancy_unadjusted": 0.046153846153846156,
        "median_mean_net_pct": -0.07894116426502606,
        "same_original_draws_verified": true,
        "max_old_net_reproduction_error_pp": 8.326672684688674e-17,
        "max_old_gross_reproduction_error_pp": 8.673617379884035e-17
      }
    },
    {
      "name": "BTCUSDT_intraday_impulse_follow_z2.5_h60",
      "old_full": {
        "n": 829,
        "net_usd": -200.83643522493733,
        "mean_net_pct": -0.02422634924305637,
        "PF": 0.9188252991258383,
        "monthly_CI95_mean_net_pct": [
          -0.08312182749190491,
          0.036374080543251086
        ],
        "positive_CI": false,
        "stress_net_usd": -495.9027970484144,
        "stress_mean_net_pct": -0.05981939650764951,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 305,
          "net_usd": -130.01351023130348,
          "mean_net_pct": -0.04262738040370606,
          "PF": 0.8688510982165025,
          "monthly_CI95_mean_net_pct": [
            -0.16507345852214517,
            0.10259008084458306
          ],
          "positive_CI": false,
          "stress_net_usd": -237.5825505366856,
          "stress_mean_net_pct": -0.07789591820874937,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 258,
          "net_usd": -31.114724575098833,
          "mean_net_pct": -0.012059970765542183,
          "PF": 0.9575294432319189,
          "monthly_CI95_mean_net_pct": [
            -0.07709969961022842,
            0.05075057510678356
          ],
          "positive_CI": false,
          "stress_net_usd": -125.21689928401695,
          "stress_mean_net_pct": -0.04853368189302982,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 266,
          "net_usd": -39.708200418535064,
          "mean_net_pct": -0.014927894894186115,
          "PF": 0.947067344463907,
          "monthly_CI95_mean_net_pct": [
            -0.10244628010897734,
            0.06177396363573174
          ],
          "positive_CI": false,
          "stress_net_usd": -133.10334722771194,
          "stress_mean_net_pct": -0.05003885234124509,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 158,
        "net_usd": -16.383144908914698,
        "mean_net_pct": -0.010369079056275127,
        "PF": 0.954189816931609,
        "monthly_CI95_mean_net_pct": [
          -0.09558729726716005,
          0.06358582868765714
        ],
        "positive_CI": false,
        "stress_net_usd": -77.18842525595848,
        "stress_mean_net_pct": -0.048853433706302844,
        "funding_usd_unchanged": 0.012902648963043236,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 829,
        "net_usd": -863.9863747798129,
        "mean_net_pct": -0.10422031058863847,
        "PF": 0.6995802142133514,
        "monthly_CI95_mean_net_pct": [
          -0.16311950252897295,
          -0.04361346780540709
        ],
        "positive_CI": false,
        "stress_net_usd": -1159.0569833794973,
        "stress_mean_net_pct": -0.1398138701302168,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 158,
        "net_usd": -142.79799422340207,
        "mean_net_pct": -0.09037847735658358,
        "PF": 0.6700793748110266,
        "monthly_CI95_mean_net_pct": [
          -0.17560204150191241,
          -0.016410092201869595
        ],
        "positive_CI": false,
        "stress_net_usd": -203.6069494638939,
        "stress_mean_net_pct": -0.12886515788854044,
        "funding_usd_unchanged": 0.012902648963043236,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 316037.12328621844,
      "fees_new_usd": 31.603712328621846,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_intraday_impulse_follow_z2_h120",
      "old_full": {
        "n": 1073,
        "net_usd": -307.92989299167783,
        "mean_net_pct": -0.028698032897640058,
        "PF": 0.9216135038205259,
        "monthly_CI95_mean_net_pct": [
          -0.0730989036299719,
          0.015332806075437142
        ],
        "positive_CI": false,
        "stress_net_usd": -699.1310649254834,
        "stress_mean_net_pct": -0.06515666961094906,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "old_thirds": {
        "train": {
          "n": 391,
          "net_usd": -151.35362893084928,
          "mean_net_pct": -0.03870936801300493,
          "PF": 0.8998856634426781,
          "monthly_CI95_mean_net_pct": [
            -0.09867784815867309,
            0.013715654557740512
          ],
          "positive_CI": false,
          "stress_net_usd": -294.3259201427288,
          "stress_mean_net_pct": -0.07527517139200225,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "validation": {
          "n": 338,
          "net_usd": 8.16889311458973,
          "mean_net_pct": 0.002416832282422997,
          "PF": 1.0069530398492532,
          "monthly_CI95_mean_net_pct": [
            -0.04955226478805827,
            0.05830246991131674
          ],
          "positive_CI": false,
          "stress_net_usd": -123.45624042832569,
          "stress_mean_net_pct": -0.036525514919622984,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "test": {
          "n": 344,
          "net_usd": -164.74515717541837,
          "mean_net_pct": -0.04789103406262162,
          "PF": 0.8673207254207488,
          "monthly_CI95_mean_net_pct": [
            -0.14769920943287249,
            0.05997909958765324
          ],
          "positive_CI": false,
          "stress_net_usd": -281.3489043544289,
          "stress_mean_net_pct": -0.08178747219605491,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        }
      },
      "fresh": {
        "n": 214,
        "net_usd": -66.65084627124592,
        "mean_net_pct": -0.03114525526693735,
        "PF": 0.8927947855510048,
        "monthly_CI95_mean_net_pct": [
          -0.11438196816667284,
          0.04300165505557641
        ],
        "positive_CI": false,
        "stress_net_usd": -147.3706911050603,
        "stress_mean_net_pct": -0.06886480892759828,
        "funding_usd_unchanged": -0.22780567420042339,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 1073,
        "net_usd": -1166.232041301547,
        "mean_net_pct": -0.10868891344842005,
        "PF": 0.7372828915541821,
        "monthly_CI95_mean_net_pct": [
          -0.1530904176806437,
          -0.06464611304436536
        ],
        "positive_CI": false,
        "stress_net_usd": -1557.4382067874478,
        "stress_mean_net_pct": -0.14514801554403056,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 120.0
      },
      "original_fresh": {
        "n": 214,
        "net_usd": -237.88062956992547,
        "mean_net_pct": -0.11115917269622687,
        "PF": 0.6711002703439233,
        "monthly_CI95_mean_net_pct": [
          -0.1944067184775595,
          -0.03700630993804051
        ],
        "positive_CI": false,
        "stress_net_usd": -318.604267394194,
        "stress_mean_net_pct": -0.14888049878233364,
        "funding_usd_unchanged": -0.22780567420042339,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 428074.4582466988,
      "fees_new_usd": 42.807445824669884,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_intraday_impulse_follow_z2_h60",
      "old_full": {
        "n": 1073,
        "net_usd": -470.80240597544184,
        "mean_net_pct": -0.04387720465754351,
        "PF": 0.8553282297033101,
        "monthly_CI95_mean_net_pct": [
          -0.08247924096550263,
          -0.007293773703004835
        ],
        "positive_CI": false,
        "stress_net_usd": -869.1214025335654,
        "stress_mean_net_pct": -0.08099919874497348,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 391,
          "net_usd": -253.25150487110415,
          "mean_net_pct": -0.06477020584938725,
          "PF": 0.8075874276039778,
          "monthly_CI95_mean_net_pct": [
            -0.1119423174716291,
            -0.011918861870040686
          ],
          "positive_CI": false,
          "stress_net_usd": -399.4313793440526,
          "stress_mean_net_pct": -0.10215636300359401,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 338,
          "net_usd": -74.71466033837105,
          "mean_net_pct": -0.022104929094192618,
          "PF": 0.9232519895421765,
          "monthly_CI95_mean_net_pct": [
            -0.0943237896361916,
            0.04121423542445487
          ],
          "positive_CI": false,
          "stress_net_usd": -200.85916111796698,
          "stress_mean_net_pct": -0.05942578731300798,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 344,
          "net_usd": -142.83624076596664,
          "mean_net_pct": -0.04152216301336239,
          "PF": 0.8519192647987016,
          "monthly_CI95_mean_net_pct": [
            -0.1177093151390775,
            0.024480268112805306
          ],
          "positive_CI": false,
          "stress_net_usd": -268.83086207154577,
          "stress_mean_net_pct": -0.07814850641614703,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 214,
        "net_usd": -102.60449642813913,
        "mean_net_pct": -0.04794602636828931,
        "PF": 0.8000456913115183,
        "monthly_CI95_mean_net_pct": [
          -0.10443023195555406,
          0.009950890889846568
        ],
        "positive_CI": false,
        "stress_net_usd": -193.93848446635857,
        "stress_mean_net_pct": -0.09062546003100869,
        "funding_usd_unchanged": 0.025503341164837857,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 1073,
        "net_usd": -1329.1859968329277,
        "mean_net_pct": -0.12387567538051515,
        "PF": 0.6487421870414308,
        "monthly_CI95_mean_net_pct": [
          -0.16248519575404546,
          -0.08727222212668417
        ],
        "positive_CI": false,
        "stress_net_usd": -1727.5123399023253,
        "stress_mean_net_pct": -0.16099835413814775,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 214,
        "net_usd": -273.82464697511386,
        "mean_net_pct": -0.12795544251173546,
        "PF": 0.5562486424181552,
        "monthly_CI95_mean_net_pct": [
          -0.18443529914048074,
          -0.07005885083475863
        ],
        "positive_CI": false,
        "stress_net_usd": -365.15746921200434,
        "stress_mean_net_pct": -0.17063433140747866,
        "funding_usd_unchanged": 0.025503341164837857,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 428050.3763674369,
      "fees_new_usd": 42.80503763674369,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_scalp_impulse_follow_z2.5_h15",
      "old_full": {
        "n": 2536,
        "net_usd": -1474.0189832077467,
        "mean_net_pct": -0.05812377694036857,
        "PF": 0.7006379305467988,
        "monthly_CI95_mean_net_pct": [
          -0.07542395265228664,
          -0.04054901125049257
        ],
        "positive_CI": false,
        "stress_net_usd": -2506.994702887189,
        "stress_mean_net_pct": -0.09885625800028347,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "old_thirds": {
        "train": {
          "n": 895,
          "net_usd": -525.5859243032622,
          "mean_net_pct": -0.0587246842796941,
          "PF": 0.7089988781289382,
          "monthly_CI95_mean_net_pct": [
            -0.0977824495306567,
            -0.021149766229031756
          ],
          "positive_CI": false,
          "stress_net_usd": -884.9378885314862,
          "stress_mean_net_pct": -0.0988757417353616,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "validation": {
          "n": 836,
          "net_usd": -409.69403224561034,
          "mean_net_pct": -0.04900646318727397,
          "PF": 0.7362575193238099,
          "monthly_CI95_mean_net_pct": [
            -0.06908700924051187,
            -0.030361882917912496
          ],
          "positive_CI": false,
          "stress_net_usd": -767.4321024979213,
          "stress_mean_net_pct": -0.09179809838491881,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 805,
          "net_usd": -538.7390266588743,
          "mean_net_pct": -0.0669241026905434,
          "PF": 0.6556147909370876,
          "monthly_CI95_mean_net_pct": [
            -0.09292320715437695,
            -0.044866919869798336
          ],
          "positive_CI": false,
          "stress_net_usd": -854.6247118577819,
          "stress_mean_net_pct": -0.10616456047922757,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        }
      },
      "fresh": {
        "n": 494,
        "net_usd": -403.3705293210528,
        "mean_net_pct": -0.08165395330385684,
        "PF": 0.5188343974091796,
        "monthly_CI95_mean_net_pct": [
          -0.10742345228284085,
          -0.05039452515204989
        ],
        "positive_CI": false,
        "stress_net_usd": -594.4333661865124,
        "stress_mean_net_pct": -0.12033064092844381,
        "funding_usd_unchanged": -0.007898831278041883,
        "median_hold_minutes": 15.0
      },
      "original_old": {
        "n": 2536,
        "net_usd": -3502.743797203278,
        "mean_net_pct": -0.1381208121925583,
        "PF": 0.4441244436485696,
        "monthly_CI95_mean_net_pct": [
          -0.15542215631481265,
          -0.1205448089338631
        ],
        "positive_CI": false,
        "stress_net_usd": -4535.724792784747,
        "stress_mean_net_pct": -0.17885350129277391,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "original_fresh": {
        "n": 494,
        "net_usd": -798.6309579254267,
        "mean_net_pct": -0.16166618581486372,
        "PF": 0.2840349984992175,
        "monthly_CI95_mean_net_pct": [
          -0.1874397191105397,
          -0.13041212708214522
        ],
        "positive_CI": false,
        "stress_net_usd": -989.6913857084278,
        "stress_mean_net_pct": -0.20034238577093677,
        "funding_usd_unchanged": -0.007898831278041883,
        "median_hold_minutes": 15.0
      },
      "actual_fresh_turnover_usd": 988151.071510935,
      "fees_new_usd": 98.8151071510935,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_scalp_impulse_follow_z2.5_h30",
      "old_full": {
        "n": 2536,
        "net_usd": -1447.4944933415316,
        "mean_net_pct": -0.05707785857024967,
        "PF": 0.7590325939273712,
        "monthly_CI95_mean_net_pct": [
          -0.07719604924367608,
          -0.03915250993398335
        ],
        "positive_CI": false,
        "stress_net_usd": -2484.34319855191,
        "stress_mean_net_pct": -0.09796305987980716,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "old_thirds": {
        "train": {
          "n": 895,
          "net_usd": -548.2745433947081,
          "mean_net_pct": -0.06125972551896179,
          "PF": 0.7525666651632319,
          "monthly_CI95_mean_net_pct": [
            -0.0984305142471537,
            -0.030477091909426084
          ],
          "positive_CI": false,
          "stress_net_usd": -922.0587351079588,
          "stress_mean_net_pct": -0.10302332235843115,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "validation": {
          "n": 836,
          "net_usd": -460.635587650949,
          "mean_net_pct": -0.05509995067595083,
          "PF": 0.7601100630112894,
          "monthly_CI95_mean_net_pct": [
            -0.08461573287896071,
            -0.029532986182228483
          ],
          "positive_CI": false,
          "stress_net_usd": -816.8996947375792,
          "stress_mean_net_pct": -0.09771527449014106,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "test": {
          "n": 805,
          "net_usd": -438.58436229587426,
          "mean_net_pct": -0.054482529477748357,
          "PF": 0.7655845735174015,
          "monthly_CI95_mean_net_pct": [
            -0.09287630762621606,
            -0.015305436429311214
          ],
          "positive_CI": false,
          "stress_net_usd": -745.3847687063719,
          "stress_mean_net_pct": -0.0925943812057605,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        }
      },
      "fresh": {
        "n": 494,
        "net_usd": -393.15951643281795,
        "mean_net_pct": -0.07958694664631942,
        "PF": 0.6167356046318411,
        "monthly_CI95_mean_net_pct": [
          -0.1103124422960532,
          -0.04877987776514517
        ],
        "positive_CI": false,
        "stress_net_usd": -576.5941041636459,
        "stress_mean_net_pct": -0.11671945428413885,
        "funding_usd_unchanged": 0.16668410401091405,
        "median_hold_minutes": 30.0
      },
      "original_old": {
        "n": 2536,
        "net_usd": -3476.1956813908964,
        "mean_net_pct": -0.1370739621999565,
        "PF": 0.5252210786793478,
        "monthly_CI95_mean_net_pct": [
          -0.15719333347709208,
          -0.1191473876574676
        ],
        "positive_CI": false,
        "stress_net_usd": -4513.040594834829,
        "stress_mean_net_pct": -0.17795901399190964,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "original_fresh": {
        "n": 494,
        "net_usd": -788.41861393855,
        "mean_net_pct": -0.15959890970415994,
        "PF": 0.3889038256165363,
        "monthly_CI95_mean_net_pct": [
          -0.1903339544569575,
          -0.1287841661934031
        ],
        "positive_CI": false,
        "stress_net_usd": -971.8487657037749,
        "stress_mean_net_pct": -0.19673051937323377,
        "funding_usd_unchanged": 0.16668410401091405,
        "median_hold_minutes": 30.0
      },
      "actual_fresh_turnover_usd": 988147.7437643307,
      "fees_new_usd": 98.81477437643308,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_scalp_impulse_follow_z2_h15",
      "old_full": {
        "n": 3445,
        "net_usd": -2116.033654864628,
        "mean_net_pct": -0.06142332815281938,
        "PF": 0.6751975500694105,
        "monthly_CI95_mean_net_pct": [
          -0.07583220904937324,
          -0.046888034929093575
        ],
        "positive_CI": false,
        "stress_net_usd": -3520.9190966234446,
        "stress_mean_net_pct": -0.10220374736207387,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "old_thirds": {
        "train": {
          "n": 1262,
          "net_usd": -756.1967878398842,
          "mean_net_pct": -0.059920506167978144,
          "PF": 0.6930314106424639,
          "monthly_CI95_mean_net_pct": [
            -0.08925401387985214,
            -0.03046714539539748
          ],
          "positive_CI": false,
          "stress_net_usd": -1255.7304492302324,
          "stress_mean_net_pct": -0.09950320516879813,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "validation": {
          "n": 1101,
          "net_usd": -652.1324122681162,
          "mean_net_pct": -0.05923091846213589,
          "PF": 0.6787830231342523,
          "monthly_CI95_mean_net_pct": [
            -0.07924753297680392,
            -0.036858951020057935
          ],
          "positive_CI": false,
          "stress_net_usd": -1110.1264374261834,
          "stress_mean_net_pct": -0.10082892256368604,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 1082,
          "net_usd": -707.7044547566271,
          "mean_net_pct": -0.065407066058838,
          "PF": 0.6498603347740114,
          "monthly_CI95_mean_net_pct": [
            -0.08942490132763198,
            -0.04285484028577874
          ],
          "positive_CI": false,
          "stress_net_usd": -1155.0622099670286,
          "stress_mean_net_pct": -0.10675251478438344,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        }
      },
      "fresh": {
        "n": 660,
        "net_usd": -416.53276514692914,
        "mean_net_pct": -0.06311102502226199,
        "PF": 0.5937459287789412,
        "monthly_CI95_mean_net_pct": [
          -0.08444123285239635,
          -0.04350120570782294
        ],
        "positive_CI": false,
        "stress_net_usd": -681.1317828533486,
        "stress_mean_net_pct": -0.10320178528081038,
        "funding_usd_unchanged": 0.00850254322593336,
        "median_hold_minutes": 15.0
      },
      "original_old": {
        "n": 3445,
        "net_usd": -4872.0805036384,
        "mean_net_pct": -0.14142468805916983,
        "PF": 0.41783334758634727,
        "monthly_CI95_mean_net_pct": [
          -0.155836187921716,
          -0.126893959124553
        ],
        "positive_CI": false,
        "stress_net_usd": -6276.985614265839,
        "stress_mean_net_pct": -0.18220567820800693,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "original_fresh": {
        "n": 660,
        "net_usd": -944.5765609038363,
        "mean_net_pct": -0.1431176607430055,
        "PF": 0.32175139479052306,
        "monthly_CI95_mean_net_pct": [
          -0.16444399416632785,
          -0.1235114969898966
        ],
        "positive_CI": false,
        "stress_net_usd": -1209.1692839833033,
        "stress_mean_net_pct": -0.18320746727019746,
        "funding_usd_unchanged": 0.00850254322593336,
        "median_hold_minutes": 15.0
      },
      "actual_fresh_turnover_usd": 1320109.4893922678,
      "fees_new_usd": 132.01094893922678,
      "passes_economic_period_gate": false
    },
    {
      "name": "BTCUSDT_scalp_impulse_follow_z2_h30",
      "old_full": {
        "n": 3445,
        "net_usd": -1949.6080880858292,
        "mean_net_pct": -0.056592397331954404,
        "PF": 0.7532049651247774,
        "monthly_CI95_mean_net_pct": [
          -0.06987189394756209,
          -0.043078191022751594
        ],
        "positive_CI": false,
        "stress_net_usd": -3387.393993669126,
        "stress_mean_net_pct": -0.09832783726180336,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "old_thirds": {
        "train": {
          "n": 1262,
          "net_usd": -749.8120310257721,
          "mean_net_pct": -0.05941458249015626,
          "PF": 0.7524696313130934,
          "monthly_CI95_mean_net_pct": [
            -0.07716515045228149,
            -0.04074502960308617
          ],
          "positive_CI": false,
          "stress_net_usd": -1269.8275723344602,
          "stress_mean_net_pct": -0.10062025137357056,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "validation": {
          "n": 1101,
          "net_usd": -610.9927150322385,
          "mean_net_pct": -0.055494342873046186,
          "PF": 0.7510647013855446,
          "monthly_CI95_mean_net_pct": [
            -0.0806661404773916,
            -0.030284491369433984
          ],
          "positive_CI": false,
          "stress_net_usd": -1073.6588992569052,
          "stress_mean_net_pct": -0.09751670292978248,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "test": {
          "n": 1082,
          "net_usd": -588.8033420278188,
          "mean_net_pct": -0.05441805379185016,
          "PF": 0.7563010854354497,
          "monthly_CI95_mean_net_pct": [
            -0.08081402329307394,
            -0.025580964365927883
          ],
          "positive_CI": false,
          "stress_net_usd": -1043.9075220777604,
          "stress_mean_net_pct": -0.09647943826966364,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        }
      },
      "fresh": {
        "n": 660,
        "net_usd": -413.43057086435266,
        "mean_net_pct": -0.06264099558550798,
        "PF": 0.6792949907557165,
        "monthly_CI95_mean_net_pct": [
          -0.09746751137822372,
          -0.029098976347093578
        ],
        "positive_CI": false,
        "stress_net_usd": -676.6657152146536,
        "stress_mean_net_pct": -0.1025251083658566,
        "funding_usd_unchanged": 0.17275140469648878,
        "median_hold_minutes": 30.0
      },
      "original_old": {
        "n": 3445,
        "net_usd": -4705.5885764165005,
        "mean_net_pct": -0.13659183095548624,
        "PF": 0.5136933021769134,
        "monthly_CI95_mean_net_pct": [
          -0.14987401090705527,
          -0.12307576848724847
        ],
        "positive_CI": false,
        "stress_net_usd": -6143.393842706275,
        "stress_mean_net_pct": -0.1783278328797177,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "original_fresh": {
        "n": 660,
        "net_usd": -941.4535112308051,
        "mean_net_pct": -0.14264447139860684,
        "PF": 0.42463884017197284,
        "monthly_CI95_mean_net_pct": [
          -0.1774717080567092,
          -0.1090985074246479
        ],
        "positive_CI": false,
        "stress_net_usd": -1204.68149453813,
        "stress_mean_net_pct": -0.18252749917244393,
        "funding_usd_unchanged": 0.17275140469648878,
        "median_hold_minutes": 30.0
      },
      "actual_fresh_turnover_usd": 1320057.3509161312,
      "fees_new_usd": 132.0057350916131,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_fade_control_z2.5_h120",
      "old_full": {
        "n": 892,
        "net_usd": -1011.2744959709444,
        "mean_net_pct": -0.11337158026580092,
        "PF": 0.755232016352109,
        "monthly_CI95_mean_net_pct": [
          -0.1646841938330654,
          -0.06364713191940213
        ],
        "positive_CI": false,
        "stress_net_usd": -1363.2602950447645,
        "stress_mean_net_pct": -0.15283187164178974,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 90.5
      },
      "old_thirds": {
        "train": {
          "n": 308,
          "net_usd": -282.24991050435716,
          "mean_net_pct": -0.09163958133258349,
          "PF": 0.7889668170586678,
          "monthly_CI95_mean_net_pct": [
            -0.1583537402136882,
            -0.029691044649993004
          ],
          "positive_CI": false,
          "stress_net_usd": -377.60044764265285,
          "stress_mean_net_pct": -0.12259754793592625,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 119.0
        },
        "validation": {
          "n": 302,
          "net_usd": -204.40215029691302,
          "mean_net_pct": -0.06768283122414338,
          "PF": 0.8572655546122825,
          "monthly_CI95_mean_net_pct": [
            -0.1690552174357009,
            0.022898863027622497
          ],
          "positive_CI": false,
          "stress_net_usd": -353.78152504094885,
          "stress_mean_net_pct": -0.11714620034468505,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 76.0
        },
        "test": {
          "n": 282,
          "net_usd": -524.6224351696743,
          "mean_net_pct": -0.1860363245282533,
          "PF": 0.6148292630768383,
          "monthly_CI95_mean_net_pct": [
            -0.26001588357237587,
            -0.09584881374421285
          ],
          "positive_CI": false,
          "stress_net_usd": -631.8783223611628,
          "stress_mean_net_pct": -0.22407032707842653,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 85.0
        }
      },
      "fresh": {
        "n": 174,
        "net_usd": -194.35772652273215,
        "mean_net_pct": -0.1116998428291564,
        "PF": 0.731549447188368,
        "monthly_CI95_mean_net_pct": [
          -0.1483383783423215,
          -0.07410594124485469
        ],
        "positive_CI": false,
        "stress_net_usd": -266.11772721524295,
        "stress_mean_net_pct": -0.15294122253749595,
        "funding_usd_unchanged": 0.10927276630277266,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 892,
        "net_usd": -1724.9279374442542,
        "mean_net_pct": -0.19337757146236034,
        "PF": 0.6212459797419565,
        "monthly_CI95_mean_net_pct": [
          -0.24468300004809745,
          -0.14365278585698954
        ],
        "positive_CI": false,
        "stress_net_usd": -2076.9104452147194,
        "stress_mean_net_pct": -0.23283749385815244,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 90.5
      },
      "original_fresh": {
        "n": 174,
        "net_usd": -333.50205668421034,
        "mean_net_pct": -0.1916678486690864,
        "PF": 0.5873122256050017,
        "monthly_CI95_mean_net_pct": [
          -0.22831791439387114,
          -0.15411913122875354
        ],
        "positive_CI": false,
        "stress_net_usd": -405.26718961754693,
        "stress_mean_net_pct": -0.23291217794111893,
        "funding_usd_unchanged": 0.10927276630277266,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 347860.8254036952,
      "fees_new_usd": 34.78608254036953,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_fade_control_z2.5_h60",
      "old_full": {
        "n": 892,
        "net_usd": -1194.4201429319226,
        "mean_net_pct": -0.13390360346770433,
        "PF": 0.6716080883678591,
        "monthly_CI95_mean_net_pct": [
          -0.17577106197816403,
          -0.09038844446740636
        ],
        "positive_CI": false,
        "stress_net_usd": -1526.2750185650261,
        "stress_mean_net_pct": -0.17110706486155003,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 308,
          "net_usd": -172.4360716101362,
          "mean_net_pct": -0.05598573753575851,
          "PF": 0.8468454298442329,
          "monthly_CI95_mean_net_pct": [
            -0.12298567746476728,
            0.015079133440572424
          ],
          "positive_CI": false,
          "stress_net_usd": -275.7975441292245,
          "stress_mean_net_pct": -0.08954465718481314,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 302,
          "net_usd": -465.6309415012067,
          "mean_net_pct": -0.15418243096066445,
          "PF": 0.6385231587399266,
          "monthly_CI95_mean_net_pct": [
            -0.2144533859383281,
            -0.09001334391934106
          ],
          "positive_CI": false,
          "stress_net_usd": -601.9909135093027,
          "stress_mean_net_pct": -0.1993347395726168,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 282,
          "net_usd": -556.3531298205797,
          "mean_net_pct": -0.197288343908007,
          "PF": 0.5451466335207323,
          "monthly_CI95_mean_net_pct": [
            -0.2643401670019587,
            -0.12732711816097636
          ],
          "positive_CI": false,
          "stress_net_usd": -648.4865609264991,
          "stress_mean_net_pct": -0.2299597733781912,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 174,
        "net_usd": -123.62594369188213,
        "mean_net_pct": -0.07104939292636904,
        "PF": 0.769484134076957,
        "monthly_CI95_mean_net_pct": [
          -0.12975093047570066,
          -0.029446908525589843
        ],
        "positive_CI": false,
        "stress_net_usd": -207.8237152513855,
        "stress_mean_net_pct": -0.11943891681114108,
        "funding_usd_unchanged": -0.06799214097653855,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 892,
        "net_usd": -1908.0542651100495,
        "mean_net_pct": -0.2139074288239966,
        "PF": 0.5285918681550269,
        "monthly_CI95_mean_net_pct": [
          -0.25577419983700617,
          -0.17038968655195538
        ],
        "positive_CI": false,
        "stress_net_usd": -2239.8963140552305,
        "stress_mean_net_pct": -0.25110945224834424,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 174,
        "net_usd": -262.76739905532753,
        "mean_net_pct": -0.15101574658352157,
        "PF": 0.5720630244513981,
        "monthly_CI95_mean_net_pct": [
          -0.2097044648174771,
          -0.10942108408615572
        ],
        "positive_CI": false,
        "stress_net_usd": -346.97102533348203,
        "stress_mean_net_pct": -0.19940863524912758,
        "funding_usd_unchanged": -0.06799214097653855,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 347853.6384086134,
      "fees_new_usd": 34.78536384086134,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_fade_control_z2_h120",
      "old_full": {
        "n": 1154,
        "net_usd": -1106.0878083567914,
        "mean_net_pct": -0.09584816363577048,
        "PF": 0.7870555018466167,
        "monthly_CI95_mean_net_pct": [
          -0.13039397731129704,
          -0.062346092515584976
        ],
        "positive_CI": false,
        "stress_net_usd": -1562.4023410120978,
        "stress_mean_net_pct": -0.13539015086759948,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 100.5
      },
      "old_thirds": {
        "train": {
          "n": 388,
          "net_usd": -254.4510083779909,
          "mean_net_pct": -0.06558015679845126,
          "PF": 0.8416724246095277,
          "monthly_CI95_mean_net_pct": [
            -0.12380789377586897,
            -0.01744151951277987
          ],
          "positive_CI": false,
          "stress_net_usd": -424.21592776464547,
          "stress_mean_net_pct": -0.10933400200119729,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 120.0
        },
        "validation": {
          "n": 391,
          "net_usd": -353.55415540991675,
          "mean_net_pct": -0.09042305764959509,
          "PF": 0.8107351396868717,
          "monthly_CI95_mean_net_pct": [
            -0.16132043948092262,
            -0.0167088634452722
          ],
          "positive_CI": false,
          "stress_net_usd": -499.3409499199296,
          "stress_mean_net_pct": -0.12770868284397177,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 81.0
        },
        "test": {
          "n": 375,
          "net_usd": -498.0826445688838,
          "mean_net_pct": -0.13282203855170235,
          "PF": 0.710265034103063,
          "monthly_CI95_mean_net_pct": [
            -0.17976963204465526,
            -0.08650597583840926
          ],
          "positive_CI": false,
          "stress_net_usd": -638.8454633275227,
          "stress_mean_net_pct": -0.1703587902206727,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 93.0
        }
      },
      "fresh": {
        "n": 247,
        "net_usd": -116.98528937645297,
        "mean_net_pct": -0.04736246533459634,
        "PF": 0.8719674264716709,
        "monthly_CI95_mean_net_pct": [
          -0.09007251045244002,
          -0.012116432603361529
        ],
        "positive_CI": false,
        "stress_net_usd": -216.98234414734443,
        "stress_mean_net_pct": -0.08784710289366171,
        "funding_usd_unchanged": 0.2053469203177226,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 1154,
        "net_usd": -2029.2618314715144,
        "mean_net_pct": -0.17584591260585045,
        "PF": 0.6458396112846363,
        "monthly_CI95_mean_net_pct": [
          -0.210385068708987,
          -0.1423379996558192
        ],
        "positive_CI": false,
        "stress_net_usd": -2485.5552973980766,
        "stress_mean_net_pct": -0.21538607429792694,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 100.5
      },
      "original_fresh": {
        "n": 247,
        "net_usd": -314.56020817517987,
        "mean_net_pct": -0.12735231100209712,
        "PF": 0.6923516550202603,
        "monthly_CI95_mean_net_pct": [
          -0.17004799208465557,
          -0.09210315108139447
        ],
        "positive_CI": false,
        "stress_net_usd": -414.5623323838056,
        "stress_mean_net_pct": -0.16783900096510346,
        "funding_usd_unchanged": 0.2053469203177226,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 493937.2969968172,
      "fees_new_usd": 49.39372969968173,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_fade_control_z2_h60",
      "old_full": {
        "n": 1154,
        "net_usd": -1198.7144820019362,
        "mean_net_pct": -0.10387473847503781,
        "PF": 0.7290266317395666,
        "monthly_CI95_mean_net_pct": [
          -0.12869923882636058,
          -0.07519313546413359
        ],
        "positive_CI": false,
        "stress_net_usd": -1644.4660509918858,
        "stress_mean_net_pct": -0.14250139090051003,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 388,
          "net_usd": -198.9484415585811,
          "mean_net_pct": -0.051275371535716784,
          "PF": 0.8533454200922029,
          "monthly_CI95_mean_net_pct": [
            -0.10643352763599512,
            0.0007181511542284104
          ],
          "positive_CI": false,
          "stress_net_usd": -353.0494663561251,
          "stress_mean_net_pct": -0.09099213050415596,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 391,
          "net_usd": -490.30913067287,
          "mean_net_pct": -0.12539875464779285,
          "PF": 0.689246226758994,
          "monthly_CI95_mean_net_pct": [
            -0.14219082017765702,
            -0.10782158270488355
          ],
          "positive_CI": false,
          "stress_net_usd": -641.9024409328111,
          "stress_mean_net_pct": -0.16416942223345551,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 375,
          "net_usd": -509.4569097704851,
          "mean_net_pct": -0.13585517593879604,
          "PF": 0.6579336350356956,
          "monthly_CI95_mean_net_pct": [
            -0.17401549250594744,
            -0.09331077944730148
          ],
          "positive_CI": false,
          "stress_net_usd": -649.5141437029495,
          "stress_mean_net_pct": -0.17320377165411988,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 247,
        "net_usd": -97.46262293646552,
        "mean_net_pct": -0.039458551796139885,
        "PF": 0.8563526316192219,
        "monthly_CI95_mean_net_pct": [
          -0.06932355920140654,
          -0.01802165233338933
        ],
        "positive_CI": false,
        "stress_net_usd": -216.10821076818488,
        "stress_mean_net_pct": -0.08749320274015582,
        "funding_usd_unchanged": -0.042612115782277186,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 1154,
        "net_usd": -2121.8313936330046,
        "mean_net_pct": -0.183867538443068,
        "PF": 0.5710201723507131,
        "monthly_CI95_mean_net_pct": [
          -0.20869172672005518,
          -0.15518168609604868
        ],
        "positive_CI": false,
        "stress_net_usd": -2567.56056127114,
        "stress_mean_net_pct": -0.22249224967687523,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 247,
        "net_usd": -295.03826883953366,
        "mean_net_pct": -0.11944869183786787,
        "PF": 0.6249693159519092,
        "monthly_CI95_mean_net_pct": [
          -0.14929639819585405,
          -0.09802037982753671
        ],
        "positive_CI": false,
        "stress_net_usd": -413.691313275273,
        "stress_mean_net_pct": -0.1674863616499081,
        "funding_usd_unchanged": -0.042612115782277186,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 493939.11475767015,
      "fees_new_usd": 49.39391147576702,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
      "old_full": {
        "n": 892,
        "net_usd": 104.98703978592266,
        "mean_net_pct": 0.011769847509632586,
        "PF": 1.027272320430587,
        "monthly_CI95_mean_net_pct": [
          -0.04530296556512879,
          0.06799838026633027
        ],
        "positive_CI": false,
        "stress_net_usd": -222.08348910389202,
        "stress_mean_net_pct": -0.024897252141691934,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 86.5
      },
      "old_thirds": {
        "train": {
          "n": 308,
          "net_usd": -30.26024780069556,
          "mean_net_pct": -0.00982475577944661,
          "PF": 0.9771250399964024,
          "monthly_CI95_mean_net_pct": [
            -0.07710816614316948,
            0.054041749239703486
          ],
          "positive_CI": false,
          "stress_net_usd": -130.62079162147398,
          "stress_mean_net_pct": -0.04240934792905,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 98.5
        },
        "validation": {
          "n": 302,
          "net_usd": -35.71789561210753,
          "mean_net_pct": -0.011827117752353487,
          "PF": 0.974875986657529,
          "monthly_CI95_mean_net_pct": [
            -0.13093235849418006,
            0.1024680053223603
          ],
          "positive_CI": false,
          "stress_net_usd": -146.80391532694534,
          "stress_mean_net_pct": -0.04861056798905475,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 69.5
        },
        "test": {
          "n": 282,
          "net_usd": 170.96518319872584,
          "mean_net_pct": 0.060625951488909875,
          "PF": 1.1547106722112574,
          "monthly_CI95_mean_net_pct": [
            -0.05028590159091082,
            0.1715898787369717
          ],
          "positive_CI": false,
          "stress_net_usd": 55.34121784452739,
          "stress_mean_net_pct": 0.01962454533493879,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 110.0
        }
      },
      "fresh": {
        "n": 174,
        "net_usd": 9.658720192146655,
        "mean_net_pct": 0.005550988616176238,
        "PF": 1.0163191748055418,
        "monthly_CI95_mean_net_pct": [
          -0.09076410632013733,
          0.10798769389333707
        ],
        "positive_CI": false,
        "stress_net_usd": -59.51168644460386,
        "stress_mean_net_pct": -0.03420211864632406,
        "funding_usd_unchanged": -0.3855445737811441,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 892,
        "net_usd": -608.6345353122842,
        "mean_net_pct": -0.06823257122335026,
        "PF": 0.8578100471128932,
        "monthly_CI95_mean_net_pct": [
          -0.12533185784523834,
          -0.011977562766894559
        ],
        "positive_CI": false,
        "stress_net_usd": -935.7283818905262,
        "stress_mean_net_pct": -0.10490228496530561,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 86.5
      },
      "original_fresh": {
        "n": 174,
        "net_usd": -129.50033749981367,
        "mean_net_pct": -0.07442548132173199,
        "PF": 0.8063328422492666,
        "monthly_CI95_mean_net_pct": [
          -0.1707722731803811,
          0.028049024289328307
        ],
        "positive_CI": false,
        "stress_net_usd": -198.66481803856647,
        "stress_mean_net_pct": -0.11417518278078534,
        "funding_usd_unchanged": -0.3855445737811441,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 347897.6442299007,
      "fees_new_usd": 34.78976442299007,
      "passes_economic_period_gate": false,
      "repriced_fresh_placebo": {
        "replicates": 64,
        "one_sided_p_expectancy_unadjusted": 0.015384615384615385,
        "median_mean_net_pct": -0.10927632259852858,
        "same_original_draws_verified": true,
        "max_old_net_reproduction_error_pp": 1.1102230246251565e-16,
        "max_old_gross_reproduction_error_pp": 9.71445146547012e-17
      }
    },
    {
      "name": "ETHUSDT_intraday_impulse_follow_z2.5_h60",
      "old_full": {
        "n": 892,
        "net_usd": -137.89266259517396,
        "mean_net_pct": -0.01545881867658901,
        "PF": 0.9580974391744785,
        "monthly_CI95_mean_net_pct": [
          -0.07366876391639036,
          0.042566996093620836
        ],
        "positive_CI": false,
        "stress_net_usd": -492.0258288811119,
        "stress_mean_net_pct": -0.055159846287120166,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 308,
          "net_usd": -272.2406118065044,
          "mean_net_pct": -0.08838980902808584,
          "PF": 0.7738407031551695,
          "monthly_CI95_mean_net_pct": [
            -0.15791150633031967,
            -0.02117727026698795
          ],
          "positive_CI": false,
          "stress_net_usd": -383.43171293666524,
          "stress_mean_net_pct": -0.12449081588852767,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 302,
          "net_usd": -3.273646196838842,
          "mean_net_pct": -0.001083988806900279,
          "PF": 0.9971281659108286,
          "monthly_CI95_mean_net_pct": [
            -0.11616809435743206,
            0.11735134818644145
          ],
          "positive_CI": false,
          "stress_net_usd": -130.1300786710307,
          "stress_mean_net_pct": -0.0430894300235201,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 282,
          "net_usd": 137.6215954081692,
          "mean_net_pct": 0.04880198418729405,
          "PF": 1.1453049740267738,
          "monthly_CI95_mean_net_pct": [
            -0.05837314552855494,
            0.14829861331076336
          ],
          "positive_CI": false,
          "stress_net_usd": 21.53596272658387,
          "stress_mean_net_pct": 0.007636866215100663,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 174,
        "net_usd": -50.32721250471878,
        "mean_net_pct": -0.02892368534753953,
        "PF": 0.901217969441013,
        "monthly_CI95_mean_net_pct": [
          -0.08982739488227585,
          0.029994872316359857
        ],
        "positive_CI": false,
        "stress_net_usd": -115.92631383974117,
        "stress_mean_net_pct": -0.06662431829870182,
        "funding_usd_unchanged": -0.03429535262251219,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 892,
        "net_usd": -851.5153383340936,
        "mean_net_pct": -0.09546136079978629,
        "PF": 0.7713449756851034,
        "monthly_CI95_mean_net_pct": [
          -0.1536658816558838,
          -0.03741855845250452
        ],
        "positive_CI": false,
        "stress_net_usd": -1205.6776987129995,
        "stress_mean_net_pct": -0.13516566129069502,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 174,
        "net_usd": -189.49783022683,
        "mean_net_pct": -0.10890679898093678,
        "PF": 0.6831557272739871,
        "monthly_CI95_mean_net_pct": [
          -0.16981428611153862,
          -0.04999532384954876
        ],
        "positive_CI": false,
        "stress_net_usd": -255.0937281943453,
        "stress_mean_net_pct": -0.1466055909162904,
        "funding_usd_unchanged": -0.03429535262251219,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 347926.5443052779,
      "fees_new_usd": 34.79265443052778,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_follow_z2_h120",
      "old_full": {
        "n": 1154,
        "net_usd": 149.96268319877217,
        "mean_net_pct": 0.012995033206132772,
        "PF": 1.0307581620793005,
        "monthly_CI95_mean_net_pct": [
          -0.02774867194086167,
          0.05174230524254619
        ],
        "positive_CI": false,
        "stress_net_usd": -345.6380163758924,
        "stress_mean_net_pct": -0.029951301245744574,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 96.0
      },
      "old_thirds": {
        "train": {
          "n": 388,
          "net_usd": -71.25800214894218,
          "mean_net_pct": -0.018365464471376852,
          "PF": 0.9571135382635606,
          "monthly_CI95_mean_net_pct": [
            -0.06695059878291466,
            0.02910205501041958
          ],
          "positive_CI": false,
          "stress_net_usd": -219.58963194265328,
          "stress_mean_net_pct": -0.05659526596460137,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 103.0
        },
        "validation": {
          "n": 391,
          "net_usd": 34.1017813400218,
          "mean_net_pct": 0.008721683207166701,
          "PF": 1.0195203285528687,
          "monthly_CI95_mean_net_pct": [
            -0.0780843790367187,
            0.07824878884610262
          ],
          "positive_CI": false,
          "stress_net_usd": -143.1241285892713,
          "stress_mean_net_pct": -0.036604636467844315,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 83.0
        },
        "test": {
          "n": 375,
          "net_usd": 187.11890400769278,
          "mean_net_pct": 0.04989837440205141,
          "PF": 1.1275518232576305,
          "monthly_CI95_mean_net_pct": [
            -0.024108565031874946,
            0.1322262610360064
          ],
          "positive_CI": false,
          "stress_net_usd": 17.07574415603219,
          "stress_mean_net_pct": 0.0045535317749419175,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 115.0
        }
      },
      "fresh": {
        "n": 247,
        "net_usd": -101.38915811507174,
        "mean_net_pct": -0.041048242151850906,
        "PF": 0.8827895166558147,
        "monthly_CI95_mean_net_pct": [
          -0.10325230433748654,
          0.020147912167988714
        ],
        "positive_CI": false,
        "stress_net_usd": -200.85540245054918,
        "stress_mean_net_pct": -0.0813179767006272,
        "funding_usd_unchanged": -0.1850999985130153,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 1154,
        "net_usd": -773.1941755030796,
        "mean_net_pct": -0.06700122837981624,
        "PF": 0.8577090313331149,
        "monthly_CI95_mean_net_pct": [
          -0.10776130863221153,
          -0.028251684007501932
        ],
        "positive_CI": false,
        "stress_net_usd": -1268.7938623494551,
        "stress_mean_net_pct": -0.10994747507360964,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 96.0
      },
      "original_fresh": {
        "n": 247,
        "net_usd": -299.01069312769226,
        "mean_net_pct": -0.12105696078044222,
        "PF": 0.694361700346685,
        "monthly_CI95_mean_net_pct": [
          -0.18326246964838058,
          -0.059849929887100965
        ],
        "positive_CI": false,
        "stress_net_usd": -398.4704329495838,
        "stress_mean_net_pct": -0.16132406192290843,
        "funding_usd_unchanged": -0.1850999985130153,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 494053.837531551,
      "fees_new_usd": 49.40538375315511,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_intraday_impulse_follow_z2_h60",
      "old_full": {
        "n": 1154,
        "net_usd": -202.4314278191755,
        "mean_net_pct": -0.01754171818190429,
        "PF": 0.9508933224187665,
        "monthly_CI95_mean_net_pct": [
          -0.05564480426378525,
          0.018239881482659513
        ],
        "positive_CI": false,
        "stress_net_usd": -725.1989129268786,
        "stress_mean_net_pct": -0.06284219349453021,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 388,
          "net_usd": -257.2029459666161,
          "mean_net_pct": -0.06628941906356084,
          "PF": 0.823615436440126,
          "monthly_CI95_mean_net_pct": [
            -0.11830570244026321,
            -0.01401751060850417
          ],
          "positive_CI": false,
          "stress_net_usd": -403.07810019180226,
          "stress_mean_net_pct": -0.10388610829685627,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 391,
          "net_usd": -49.781090231855856,
          "mean_net_pct": -0.012731736632188198,
          "PF": 0.9649909178539989,
          "monthly_CI95_mean_net_pct": [
            -0.07714233533257439,
            0.04283100433402823
          ],
          "positive_CI": false,
          "stress_net_usd": -228.65347198215846,
          "stress_mean_net_pct": -0.058479148844541806,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "test": {
          "n": 375,
          "net_usd": 104.55260837929656,
          "mean_net_pct": 0.027880695567812412,
          "PF": 1.084171561622859,
          "monthly_CI95_mean_net_pct": [
            -0.04519945473399785,
            0.10124857585575793
          ],
          "positive_CI": false,
          "stress_net_usd": -93.4673407529179,
          "stress_mean_net_pct": -0.024924624200778105,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 247,
        "net_usd": -193.61208083366367,
        "mean_net_pct": -0.07838545782739419,
        "PF": 0.7343848542972261,
        "monthly_CI95_mean_net_pct": [
          -0.10849294838015072,
          -0.04459690796979429
        ],
        "positive_CI": false,
        "stress_net_usd": -287.7385780317834,
        "stress_mean_net_pct": -0.11649335142987181,
        "funding_usd_unchanged": 0.05554053848076939,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 1154,
        "net_usd": -1125.5661839117886,
        "mean_net_pct": -0.09753606446375984,
        "PF": 0.7598428673785058,
        "monthly_CI95_mean_net_pct": [
          -0.13564016924133804,
          -0.06175591307001186
        ],
        "positive_CI": false,
        "stress_net_usd": -1648.3456445634738,
        "stress_mean_net_pct": -0.1428375775184986,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 247,
        "net_usd": -391.2260447792799,
        "mean_net_pct": -0.15839111124667204,
        "PF": 0.5444000912565219,
        "monthly_CI95_mean_net_pct": [
          -0.1884976556085016,
          -0.12460908676761526
        ],
        "positive_CI": false,
        "stress_net_usd": -485.3504303430907,
        "stress_mean_net_pct": -0.19649814993647394,
        "funding_usd_unchanged": 0.05554053848076939,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 494034.9098640407,
      "fees_new_usd": 49.40349098640407,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_scalp_impulse_follow_z2.5_h15",
      "old_full": {
        "n": 2756,
        "net_usd": -1805.0123537556574,
        "mean_net_pct": -0.06549391704483518,
        "PF": 0.7354402681449703,
        "monthly_CI95_mean_net_pct": [
          -0.08147503919587869,
          -0.049636910954160444
        ],
        "positive_CI": false,
        "stress_net_usd": -2918.3761682826444,
        "stress_mean_net_pct": -0.10589173324683035,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "old_thirds": {
        "train": {
          "n": 936,
          "net_usd": -513.8808802607058,
          "mean_net_pct": -0.0549018034466566,
          "PF": 0.7722060673624176,
          "monthly_CI95_mean_net_pct": [
            -0.08096965024847295,
            -0.029237031535630863
          ],
          "positive_CI": false,
          "stress_net_usd": -865.4673012877947,
          "stress_mean_net_pct": -0.09246445526579003,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "validation": {
          "n": 918,
          "net_usd": -653.2129313788755,
          "mean_net_pct": -0.0711560927427969,
          "PF": 0.7230031064252436,
          "monthly_CI95_mean_net_pct": [
            -0.10179209302083882,
            -0.04119432980554615
          ],
          "positive_CI": false,
          "stress_net_usd": -1058.1120574629103,
          "stress_mean_net_pct": -0.11526275135761552,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 902,
          "net_usd": -637.9185421160764,
          "mean_net_pct": -0.07072267650954285,
          "PF": 0.7111666613361622,
          "monthly_CI95_mean_net_pct": [
            -0.10030063464764534,
            -0.04266449713093729
          ],
          "positive_CI": false,
          "stress_net_usd": -994.7968095319395,
          "stress_mean_net_pct": -0.11028789462660084,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        }
      },
      "fresh": {
        "n": 526,
        "net_usd": -313.98559048097576,
        "mean_net_pct": -0.059693078038208315,
        "PF": 0.7005137232176126,
        "monthly_CI95_mean_net_pct": [
          -0.07315311803127471,
          -0.048261024968613245
        ],
        "positive_CI": false,
        "stress_net_usd": -533.9628421153074,
        "stress_mean_net_pct": -0.10151384831089491,
        "funding_usd_unchanged": -0.30447270958132283,
        "median_hold_minutes": 15.0
      },
      "original_old": {
        "n": 2756,
        "net_usd": -4009.721509868022,
        "mean_net_pct": -0.14549062082249717,
        "PF": 0.5166470195103983,
        "monthly_CI95_mean_net_pct": [
          -0.16147266830177007,
          -0.12963711105778844
        ],
        "positive_CI": false,
        "stress_net_usd": -5123.100427019942,
        "stress_mean_net_pct": -0.18588898501523737,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "original_fresh": {
        "n": 526,
        "net_usd": -734.7916115661277,
        "mean_net_pct": -0.139694222731203,
        "PF": 0.45059102515199795,
        "monthly_CI95_mean_net_pct": [
          -0.15315299419035108,
          -0.12825231039613125
        ],
        "positive_CI": false,
        "stress_net_usd": -954.7718832619754,
        "stress_mean_net_pct": -0.18151556716007136,
        "funding_usd_unchanged": -0.30447270958132283,
        "median_hold_minutes": 15.0
      },
      "actual_fresh_turnover_usd": 1052015.0527128794,
      "fees_new_usd": 105.20150527128794,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_scalp_impulse_follow_z2.5_h30",
      "old_full": {
        "n": 2756,
        "net_usd": -1948.994161747627,
        "mean_net_pct": -0.07071822067299081,
        "PF": 0.758466280553808,
        "monthly_CI95_mean_net_pct": [
          -0.08857070197886331,
          -0.053218935680612235
        ],
        "positive_CI": false,
        "stress_net_usd": -3089.835810918391,
        "stress_mean_net_pct": -0.11211305554856281,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "old_thirds": {
        "train": {
          "n": 936,
          "net_usd": -582.7007158639839,
          "mean_net_pct": -0.06225434998546836,
          "PF": 0.7809800067242433,
          "monthly_CI95_mean_net_pct": [
            -0.09669156459263216,
            -0.027240577589208767
          ],
          "positive_CI": false,
          "stress_net_usd": -940.5551502279777,
          "stress_mean_net_pct": -0.10048666134914291,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "validation": {
          "n": 918,
          "net_usd": -716.3593651867155,
          "mean_net_pct": -0.07803478923602565,
          "PF": 0.7428522644776382,
          "monthly_CI95_mean_net_pct": [
            -0.1123516791126536,
            -0.0464273662022489
          ],
          "positive_CI": false,
          "stress_net_usd": -1142.5845290029417,
          "stress_mean_net_pct": -0.12446454564302198,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 29.0
        },
        "test": {
          "n": 902,
          "net_usd": -649.9340806969276,
          "mean_net_pct": -0.07205477613047977,
          "PF": 0.7522137284918938,
          "monthly_CI95_mean_net_pct": [
            -0.099182852122883,
            -0.044572107867694506
          ],
          "positive_CI": false,
          "stress_net_usd": -1006.6961316874714,
          "stress_mean_net_pct": -0.11160710994317866,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        }
      },
      "fresh": {
        "n": 526,
        "net_usd": -383.4939895993851,
        "mean_net_pct": -0.07290760258543443,
        "PF": 0.6979794823643086,
        "monthly_CI95_mean_net_pct": [
          -0.11237858481489178,
          -0.04125564248246812
        ],
        "positive_CI": false,
        "stress_net_usd": -585.2479964049455,
        "stress_mean_net_pct": -0.11126387764352577,
        "funding_usd_unchanged": -0.24614711254286706,
        "median_hold_minutes": 30.0
      },
      "original_old": {
        "n": 2756,
        "net_usd": -4153.76216733789,
        "mean_net_pct": -0.15071705977278263,
        "PF": 0.563801274381148,
        "monthly_CI95_mean_net_pct": [
          -0.16856981220015146,
          -0.13320975738764523
        ],
        "positive_CI": false,
        "stress_net_usd": -5294.635109812109,
        "stress_mean_net_pct": -0.19211303010929276,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "original_fresh": {
        "n": 526,
        "net_usd": -804.2902370375361,
        "mean_net_pct": -0.15290688917063425,
        "PF": 0.4829082909598417,
        "monthly_CI95_mean_net_pct": [
          -0.19238296970825422,
          -0.12125257555086766
        ],
        "positive_CI": false,
        "stress_net_usd": -1006.0463023818902,
        "stress_mean_net_pct": -0.19126355558591068,
        "funding_usd_unchanged": -0.24614711254286706,
        "median_hold_minutes": 30.0
      },
      "actual_fresh_turnover_usd": 1051990.6185953773,
      "fees_new_usd": 105.19906185953774,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_scalp_impulse_follow_z2_h15",
      "old_full": {
        "n": 3952,
        "net_usd": -2461.346946135753,
        "mean_net_pct": -0.06228104620788849,
        "PF": 0.7306457743579379,
        "monthly_CI95_mean_net_pct": [
          -0.07394626530092659,
          -0.05114663540664367
        ],
        "positive_CI": false,
        "stress_net_usd": -4038.3809204041936,
        "stress_mean_net_pct": -0.10218575203451907,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "old_thirds": {
        "train": {
          "n": 1297,
          "net_usd": -645.9473426119946,
          "mean_net_pct": -0.049803187556823024,
          "PF": 0.7765280488312495,
          "monthly_CI95_mean_net_pct": [
            -0.061930592664512986,
            -0.0374474001815741
          ],
          "positive_CI": false,
          "stress_net_usd": -1143.9404503661528,
          "stress_mean_net_pct": -0.08819895530964941,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "validation": {
          "n": 1336,
          "net_usd": -822.8364937634349,
          "mean_net_pct": -0.06158955791642476,
          "PF": 0.7430375605685978,
          "monthly_CI95_mean_net_pct": [
            -0.08630883611064766,
            -0.04164971368269034
          ],
          "positive_CI": false,
          "stress_net_usd": -1386.0488740726328,
          "stress_mean_net_pct": -0.10374617320902939,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 1319,
          "net_usd": -992.5631097603236,
          "mean_net_pct": -0.07525118345415646,
          "PF": 0.6740652553813418,
          "monthly_CI95_mean_net_pct": [
            -0.09532625845151249,
            -0.059098488954904466
          ],
          "positive_CI": false,
          "stress_net_usd": -1508.3915959654091,
          "stress_mean_net_pct": -0.11435872600192638,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        }
      },
      "fresh": {
        "n": 764,
        "net_usd": -506.51852543550393,
        "mean_net_pct": -0.06629823631354763,
        "PF": 0.6501926967080374,
        "monthly_CI95_mean_net_pct": [
          -0.08263933872746901,
          -0.05439293105058417
        ],
        "positive_CI": false,
        "stress_net_usd": -808.0629373850342,
        "stress_mean_net_pct": -0.1057674001812872,
        "funding_usd_unchanged": -0.40005348260225115,
        "median_hold_minutes": 15.0
      },
      "original_old": {
        "n": 3952,
        "net_usd": -5622.81167379352,
        "mean_net_pct": -0.14227762332473481,
        "PF": 0.4995787734548916,
        "monthly_CI95_mean_net_pct": [
          -0.15394415729071248,
          -0.13114261280195552
        ],
        "positive_CI": false,
        "stress_net_usd": -7199.849938995657,
        "stress_mean_net_pct": -0.1821824377276229,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "original_fresh": {
        "n": 764,
        "net_usd": -1117.7165341247435,
        "mean_net_pct": -0.14629797567077796,
        "PF": 0.40361205470853473,
        "monthly_CI95_mean_net_pct": [
          -0.16264161040303038,
          -0.1343994021709588
        ],
        "positive_CI": false,
        "stress_net_usd": -1419.2521618112823,
        "stress_mean_net_pct": -0.18576598976587466,
        "funding_usd_unchanged": -0.40005348260225115,
        "median_hold_minutes": 15.0
      },
      "actual_fresh_turnover_usd": 1527995.0217230986,
      "fees_new_usd": 152.79950217230984,
      "passes_economic_period_gate": false
    },
    {
      "name": "ETHUSDT_scalp_impulse_follow_z2_h30",
      "old_full": {
        "n": 3952,
        "net_usd": -2456.236661116035,
        "mean_net_pct": -0.06215173737641788,
        "PF": 0.7759703283413343,
        "monthly_CI95_mean_net_pct": [
          -0.07626701718807546,
          -0.048771960924897564
        ],
        "positive_CI": false,
        "stress_net_usd": -4015.6316848438437,
        "stress_mean_net_pct": -0.10161011348289077,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "old_thirds": {
        "train": {
          "n": 1297,
          "net_usd": -584.566516499116,
          "mean_net_pct": -0.045070664340718276,
          "PF": 0.8316777922264793,
          "monthly_CI95_mean_net_pct": [
            -0.06129993330515852,
            -0.029762871400168266
          ],
          "positive_CI": false,
          "stress_net_usd": -1083.9555970024378,
          "stress_mean_net_pct": -0.08357406299170685,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "validation": {
          "n": 1336,
          "net_usd": -857.2864493199165,
          "mean_net_pct": -0.06416814740418537,
          "PF": 0.7747408318622205,
          "monthly_CI95_mean_net_pct": [
            -0.0981426372871958,
            -0.03714348797201059
          ],
          "positive_CI": false,
          "stress_net_usd": -1397.3115331170502,
          "stress_mean_net_pct": -0.10458918661055766,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "test": {
          "n": 1319,
          "net_usd": -1014.3836952970022,
          "mean_net_pct": -0.07690551139476894,
          "PF": 0.724741937073954,
          "monthly_CI95_mean_net_pct": [
            -0.08944463078874272,
            -0.06473891742971534
          ],
          "positive_CI": false,
          "stress_net_usd": -1534.364554724356,
          "stress_mean_net_pct": -0.11632786616560696,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        }
      },
      "fresh": {
        "n": 764,
        "net_usd": -570.610886221919,
        "mean_net_pct": -0.07468728877250248,
        "PF": 0.6782264041675824,
        "monthly_CI95_mean_net_pct": [
          -0.10815320758472773,
          -0.045676829507795516
        ],
        "positive_CI": false,
        "stress_net_usd": -861.2402398961219,
        "stress_mean_net_pct": -0.11272778009111543,
        "funding_usd_unchanged": -0.2990007499594399,
        "median_hold_minutes": 30.0
      },
      "original_old": {
        "n": 3952,
        "net_usd": -5617.707891773751,
        "mean_net_pct": -0.14214847904285807,
        "PF": 0.568498399060691,
        "monthly_CI95_mean_net_pct": [
          -0.15626705512830022,
          -0.12877073685378324
        ],
        "positive_CI": false,
        "stress_net_usd": -7177.110438039091,
        "stress_mean_net_pct": -0.18160704549694057,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "original_fresh": {
        "n": 764,
        "net_usd": -1181.7590264642793,
        "mean_net_pct": -0.15468050084610985,
        "PF": 0.4617215684083012,
        "monthly_CI95_mean_net_pct": [
          -0.1881513268678694,
          -0.12567327652887708
        ],
        "positive_CI": false,
        "stress_net_usd": -1472.3790902961275,
        "stress_mean_net_pct": -0.1927197762167706,
        "funding_usd_unchanged": -0.2990007499594399,
        "median_hold_minutes": 30.0
      },
      "actual_fresh_turnover_usd": 1527870.3506059002,
      "fees_new_usd": 152.78703506059,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_fade_control_z2.5_h120",
      "old_full": {
        "n": 781,
        "net_usd": -174.3900709424512,
        "mean_net_pct": -0.02232907438443677,
        "PF": 0.9514430835342359,
        "monthly_CI95_mean_net_pct": [
          -0.09611948766421699,
          0.053081513460160344
        ],
        "positive_CI": false,
        "stress_net_usd": -480.2166524418853,
        "stress_mean_net_pct": -0.061487407482955864,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 62.0
      },
      "old_thirds": {
        "train": {
          "n": 255,
          "net_usd": -147.8503712956531,
          "mean_net_pct": -0.05798053776300121,
          "PF": 0.8690942888448202,
          "monthly_CI95_mean_net_pct": [
            -0.22729455830204753,
            0.11152063172243656
          ],
          "positive_CI": false,
          "stress_net_usd": -239.43197403469236,
          "stress_mean_net_pct": -0.09389489177831072,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 83.0
        },
        "validation": {
          "n": 274,
          "net_usd": 74.66972259601431,
          "mean_net_pct": 0.027251723575187705,
          "PF": 1.0564250323608917,
          "monthly_CI95_mean_net_pct": [
            -0.08735389325247049,
            0.14065336531007788
          ],
          "positive_CI": false,
          "stress_net_usd": -18.083992713429474,
          "stress_mean_net_pct": -0.006599997340667692,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 39.5
        },
        "test": {
          "n": 252,
          "net_usd": -101.20942224281238,
          "mean_net_pct": -0.040162469143973166,
          "PF": 0.9111162041565513,
          "monthly_CI95_mean_net_pct": [
            -0.1331125167268623,
            0.045556738916417344
          ],
          "positive_CI": false,
          "stress_net_usd": -222.70068569376335,
          "stress_mean_net_pct": -0.0883732879737156,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 77.5
        }
      },
      "fresh": {
        "n": 154,
        "net_usd": -159.13174626599104,
        "mean_net_pct": -0.10333230277012406,
        "PF": 0.7661570985718886,
        "monthly_CI95_mean_net_pct": [
          -0.22100560736203592,
          0.02289242679616047
        ],
        "positive_CI": false,
        "stress_net_usd": -220.70426451343278,
        "stress_mean_net_pct": -0.14331445747625507,
        "funding_usd_unchanged": 0.41017320231792426,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 781,
        "net_usd": -799.1743765900429,
        "mean_net_pct": -0.10232706486428206,
        "PF": 0.7977436378407234,
        "monthly_CI95_mean_net_pct": [
          -0.176139608213595,
          -0.026923010615440043
        ],
        "positive_CI": false,
        "stress_net_usd": -1104.993401101433,
        "stress_mean_net_pct": -0.14148443035869818,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 62.0
      },
      "original_fresh": {
        "n": 154,
        "net_usd": -282.3911789857746,
        "mean_net_pct": -0.18337089544530819,
        "PF": 0.6256824712907718,
        "monthly_CI95_mean_net_pct": [
          -0.301049137016224,
          -0.05719125841934315
        ],
        "positive_CI": false,
        "stress_net_usd": -343.960185810617,
        "stress_mean_net_pct": -0.2233507700068942,
        "funding_usd_unchanged": 0.41017320231792426,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 308148.5817994586,
      "fees_new_usd": 30.814858179945862,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_fade_control_z2.5_h60",
      "old_full": {
        "n": 781,
        "net_usd": -260.61336439440066,
        "mean_net_pct": -0.033369188782893806,
        "PF": 0.9178122363538397,
        "monthly_CI95_mean_net_pct": [
          -0.08845068114602014,
          0.023019121673932785
        ],
        "positive_CI": false,
        "stress_net_usd": -578.3755753966002,
        "stress_mean_net_pct": -0.07405577149764407,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 255,
          "net_usd": -102.6410828475498,
          "mean_net_pct": -0.04025140503825483,
          "PF": 0.8935161474788585,
          "monthly_CI95_mean_net_pct": [
            -0.1754890326808662,
            0.09310255917090209
          ],
          "positive_CI": false,
          "stress_net_usd": -196.02221761555754,
          "stress_mean_net_pct": -0.07687145788845394,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 274,
          "net_usd": 10.642128169607059,
          "mean_net_pct": 0.003883988383068269,
          "PF": 1.0088775653057782,
          "monthly_CI95_mean_net_pct": [
            -0.07090705722299508,
            0.07535347432139854
          ],
          "positive_CI": false,
          "stress_net_usd": -98.84728545610771,
          "stress_mean_net_pct": -0.03607565162631668,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 39.5
        },
        "test": {
          "n": 252,
          "net_usd": -168.61440971645786,
          "mean_net_pct": -0.06691048004621344,
          "PF": 0.8327689589356215,
          "monthly_CI95_mean_net_pct": [
            -0.1332927938608193,
            -0.005643554192277062
          ],
          "positive_CI": false,
          "stress_net_usd": -283.50607232493496,
          "stress_mean_net_pct": -0.11250240965275198,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 154,
        "net_usd": -98.00431963283569,
        "mean_net_pct": -0.06363916859275046,
        "PF": 0.8074925686510298,
        "monthly_CI95_mean_net_pct": [
          -0.15616245519823135,
          0.061658065918282524
        ],
        "positive_CI": false,
        "stress_net_usd": -161.9986896983015,
        "stress_mean_net_pct": -0.10519395434954644,
        "funding_usd_unchanged": -0.10006093796494929,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 781,
        "net_usd": -885.4292371881683,
        "mean_net_pct": -0.11337122115085381,
        "PF": 0.7483307755464695,
        "monthly_CI95_mean_net_pct": [
          -0.1684459212272621,
          -0.05697772235566718
        ],
        "positive_CI": false,
        "stress_net_usd": -1203.1831486615358,
        "stress_mean_net_pct": -0.15405674118585605,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 154,
        "net_usd": -221.27881066084677,
        "mean_net_pct": -0.14368753939016024,
        "PF": 0.6213926413433883,
        "monthly_CI95_mean_net_pct": [
          -0.23616981178156699,
          -0.018405618342337914
        ],
        "positive_CI": false,
        "stress_net_usd": -285.26760217478085,
        "stress_mean_net_pct": -0.18523870271089665,
        "funding_usd_unchanged": -0.10006093796494929,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 308186.22757002764,
      "fees_new_usd": 30.818622757002768,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_fade_control_z2_h120",
      "old_full": {
        "n": 1049,
        "net_usd": -607.8418866643726,
        "mean_net_pct": -0.05794488910051217,
        "PF": 0.8748463090230176,
        "monthly_CI95_mean_net_pct": [
          -0.1127787626195309,
          -0.004747681512318049
        ],
        "positive_CI": false,
        "stress_net_usd": -1019.4068960773421,
        "stress_mean_net_pct": -0.09717892240966083,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 72.0
      },
      "old_thirds": {
        "train": {
          "n": 334,
          "net_usd": -363.12674863264874,
          "mean_net_pct": -0.10872058342294873,
          "PF": 0.7595757066379775,
          "monthly_CI95_mean_net_pct": [
            -0.2102717563364468,
            -0.004148027705241675
          ],
          "positive_CI": false,
          "stress_net_usd": -488.8937361409061,
          "stress_mean_net_pct": -0.1463753701020677,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 90.0
        },
        "validation": {
          "n": 375,
          "net_usd": -187.208901693538,
          "mean_net_pct": -0.04992237378494347,
          "PF": 0.9008916302763863,
          "monthly_CI95_mean_net_pct": [
            -0.14081205929179694,
            0.036019391454255756
          ],
          "positive_CI": false,
          "stress_net_usd": -305.2006146367769,
          "stress_mean_net_pct": -0.08138683056980717,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 41.0
        },
        "test": {
          "n": 340,
          "net_usd": -57.50623633818584,
          "mean_net_pct": -0.016913598922995838,
          "PF": 0.9605439103716014,
          "monthly_CI95_mean_net_pct": [
            -0.10284009618462857,
            0.06673016989004443
          ],
          "positive_CI": false,
          "stress_net_usd": -225.31254529965912,
          "stress_mean_net_pct": -0.06626839567637034,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 91.0
        }
      },
      "fresh": {
        "n": 212,
        "net_usd": -65.20524029156164,
        "mean_net_pct": -0.030757188816774354,
        "PF": 0.919867343180836,
        "monthly_CI95_mean_net_pct": [
          -0.08775165937224769,
          0.04150628736647317
        ],
        "positive_CI": false,
        "stress_net_usd": -145.5077921217764,
        "stress_mean_net_pct": -0.06863575100083792,
        "funding_usd_unchanged": 0.2871463189671714,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 1049,
        "net_usd": -1447.1218263594849,
        "mean_net_pct": -0.13795250966248665,
        "PF": 0.7295878434068892,
        "monthly_CI95_mean_net_pct": [
          -0.19278128457670526,
          -0.08476158416624284
        ],
        "positive_CI": false,
        "stress_net_usd": -1858.6734291268244,
        "stress_mean_net_pct": -0.17718526493106046,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 72.0
      },
      "original_fresh": {
        "n": 212,
        "net_usd": -234.83506404333932,
        "mean_net_pct": -0.11077125662421665,
        "PF": 0.7410876740339326,
        "monthly_CI95_mean_net_pct": [
          -0.16774524702734903,
          -0.038484184152383805
        ],
        "positive_CI": false,
        "stress_net_usd": -315.13101726359116,
        "stress_mean_net_pct": -0.14864670625641094,
        "funding_usd_unchanged": 0.2871463189671714,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 424074.5593794442,
      "fees_new_usd": 42.40745593794443,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_fade_control_z2_h60",
      "old_full": {
        "n": 1049,
        "net_usd": -696.8716404357234,
        "mean_net_pct": -0.06643199622838164,
        "PF": 0.8347820062971171,
        "monthly_CI95_mean_net_pct": [
          -0.11660178366983731,
          -0.016550081331055712
        ],
        "positive_CI": false,
        "stress_net_usd": -1108.3687975034695,
        "stress_mean_net_pct": -0.10565956124913914,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 334,
          "net_usd": -329.11765558464936,
          "mean_net_pct": -0.09853822023492495,
          "PF": 0.7429832209858686,
          "monthly_CI95_mean_net_pct": [
            -0.20025730730219612,
            -0.008562676297896072
          ],
          "positive_CI": false,
          "stress_net_usd": -468.3313061888829,
          "stress_mean_net_pct": -0.14021895394876732,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 375,
          "net_usd": -241.83295464061788,
          "mean_net_pct": -0.06448878790416476,
          "PF": 0.8562185354269626,
          "monthly_CI95_mean_net_pct": [
            -0.15269979345314222,
            0.031151036343770987
          ],
          "positive_CI": false,
          "stress_net_usd": -367.4551686387815,
          "stress_mean_net_pct": -0.09798804497034173,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 41.0
        },
        "test": {
          "n": 340,
          "net_usd": -125.92103021045608,
          "mean_net_pct": -0.03703559712072238,
          "PF": 0.8996976072563292,
          "monthly_CI95_mean_net_pct": [
            -0.0950469207840973,
            0.011645852419401992
          ],
          "positive_CI": false,
          "stress_net_usd": -272.58232267580496,
          "stress_mean_net_pct": -0.08017127137523675,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 212,
        "net_usd": -30.001929590287503,
        "mean_net_pct": -0.014151853580324293,
        "PF": 0.9509903647408404,
        "monthly_CI95_mean_net_pct": [
          -0.06970937949641576,
          0.03960537035406179
        ],
        "positive_CI": false,
        "stress_net_usd": -115.38898383974875,
        "stress_mean_net_pct": -0.05442876596214564,
        "funding_usd_unchanged": -0.14007931451371372,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 1049,
        "net_usd": -1536.2173672822255,
        "mean_net_pct": -0.14644588820612253,
        "PF": 0.6725815618323717,
        "monthly_CI95_mean_net_pct": [
          -0.1966048480602142,
          -0.0965696991371673
        ],
        "positive_CI": false,
        "stress_net_usd": -1947.700129759776,
        "stress_mean_net_pct": -0.18567208100665167,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 212,
        "net_usd": -199.6554829774087,
        "mean_net_pct": -0.09417711461198525,
        "PF": 0.7170127572177847,
        "monthly_CI95_mean_net_pct": [
          -0.14971831617450876,
          -0.04043059333201667
        ],
        "positive_CI": false,
        "stress_net_usd": -285.03414505651347,
        "stress_mean_net_pct": -0.13445006842288373,
        "funding_usd_unchanged": -0.14007931451371372,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 424133.883467803,
      "fees_new_usd": 42.4133883467803,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
      "old_full": {
        "n": 781,
        "net_usd": -878.9144049515654,
        "mean_net_pct": -0.11253705569162167,
        "PF": 0.7766107025319952,
        "monthly_CI95_mean_net_pct": [
          -0.16941009647330812,
          -0.057063142206467535
        ],
        "positive_CI": false,
        "stress_net_usd": -1166.5910236461277,
        "stress_mean_net_pct": -0.14937144989066933,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 55.0
      },
      "old_thirds": {
        "train": {
          "n": 255,
          "net_usd": -371.39505365892603,
          "mean_net_pct": -0.14564511908193178,
          "PF": 0.7015257494567018,
          "monthly_CI95_mean_net_pct": [
            -0.2584579579771812,
            -0.046795104715390515
          ],
          "positive_CI": false,
          "stress_net_usd": -444.4155545746617,
          "stress_mean_net_pct": -0.17428060963712225,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 86.0
        },
        "validation": {
          "n": 274,
          "net_usd": -413.0286184782914,
          "mean_net_pct": -0.1507403717074056,
          "PF": 0.7357579368787156,
          "monthly_CI95_mean_net_pct": [
            -0.24011593545439844,
            -0.06961081911525685
          ],
          "positive_CI": false,
          "stress_net_usd": -507.8235876312551,
          "stress_mean_net_pct": -0.18533707577783035,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "test": {
          "n": 252,
          "net_usd": -94.49073281434778,
          "mean_net_pct": -0.037496322545376104,
          "PF": 0.9161625497164819,
          "monthly_CI95_mean_net_pct": [
            -0.11981657341997241,
            0.03857359039832935
          ],
          "positive_CI": false,
          "stress_net_usd": -214.35188144021072,
          "stress_mean_net_pct": -0.08506027041278202,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 89.5
        }
      },
      "fresh": {
        "n": 154,
        "net_usd": 7.1811259377766685,
        "mean_net_pct": 0.004663068790764071,
        "PF": 1.0117361951772492,
        "monthly_CI95_mean_net_pct": [
          -0.1363666503038029,
          0.13254159367047058
        ],
        "positive_CI": false,
        "stress_net_usd": -48.35264185265413,
        "stress_mean_net_pct": -0.03139781938484035,
        "funding_usd_unchanged": -0.11690903564977556,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 781,
        "net_usd": -1503.7093038292512,
        "mean_net_pct": -0.19253640253895662,
        "PF": 0.6537693539017022,
        "monthly_CI95_mean_net_pct": [
          -0.24940557397163549,
          -0.13708774047813102
        ],
        "positive_CI": false,
        "stress_net_usd": -1791.3600377798132,
        "stress_mean_net_pct": -0.22936748243019373,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 55.0
      },
      "original_fresh": {
        "n": 154,
        "net_usd": -116.08384215528712,
        "mean_net_pct": -0.07537911828265396,
        "PF": 0.8292571030871028,
        "monthly_CI95_mean_net_pct": [
          -0.21635799471166461,
          0.052520892345902105
        ],
        "positive_CI": false,
        "stress_net_usd": -171.61379177174757,
        "stress_mean_net_pct": -0.11143752712451142,
        "funding_usd_unchanged": -0.11690903564977556,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 308162.42023265944,
      "fees_new_usd": 30.816242023265943,
      "passes_economic_period_gate": false,
      "repriced_fresh_placebo": {
        "replicates": 64,
        "one_sided_p_expectancy_unadjusted": 0.015384615384615385,
        "median_mean_net_pct": -0.04136107509295253,
        "same_original_draws_verified": true,
        "max_old_net_reproduction_error_pp": 1.249000902703301e-16,
        "max_old_gross_reproduction_error_pp": 9.8879238130678e-17
      }
    },
    {
      "name": "XRPUSDT_intraday_impulse_follow_z2.5_h60",
      "old_full": {
        "n": 781,
        "net_usd": -879.5253008185746,
        "mean_net_pct": -0.11261527539290328,
        "PF": 0.7510026715553586,
        "monthly_CI95_mean_net_pct": [
          -0.170947484126579,
          -0.058792388165319676
        ],
        "positive_CI": false,
        "stress_net_usd": -1185.6613838925966,
        "stress_mean_net_pct": -0.15181323737421212,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 55.0
      },
      "old_thirds": {
        "train": {
          "n": 255,
          "net_usd": -385.6920428175836,
          "mean_net_pct": -0.15125178149709162,
          "PF": 0.6529361771725556,
          "monthly_CI95_mean_net_pct": [
            -0.26167714373036544,
            -0.0476237913598292
          ],
          "positive_CI": false,
          "stress_net_usd": -472.7337535198185,
          "stress_mean_net_pct": -0.18538578569404648,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 274,
          "net_usd": -381.18179045989706,
          "mean_net_pct": -0.13911744177368507,
          "PF": 0.7332877887015861,
          "monthly_CI95_mean_net_pct": [
            -0.23757575923240468,
            -0.058684138279986274
          ],
          "positive_CI": false,
          "stress_net_usd": -487.6619305717941,
          "stress_mean_net_pct": -0.17797880677802705,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "test": {
          "n": 252,
          "net_usd": -112.65146754109402,
          "mean_net_pct": -0.04470296330995794,
          "PF": 0.8864149032300891,
          "monthly_CI95_mean_net_pct": [
            -0.1187093199666046,
            0.03037158524362185
          ],
          "positive_CI": false,
          "stress_net_usd": -225.2656998009841,
          "stress_mean_net_pct": -0.08939115071467622,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 154,
        "net_usd": -59.29007078746615,
        "mean_net_pct": -0.03850004596588711,
        "PF": 0.8809189119563492,
        "monthly_CI95_mean_net_pct": [
          -0.12791452504152162,
          0.035770630202620946
        ],
        "positive_CI": false,
        "stress_net_usd": -110.94426013536518,
        "stress_mean_net_pct": -0.07204172736062674,
        "funding_usd_unchanged": 0.13316026188854982,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 781,
        "net_usd": -1504.3713434481388,
        "mean_net_pct": -0.19262117073599727,
        "PF": 0.617270317369033,
        "monthly_CI95_mean_net_pct": [
          -0.25095017708307676,
          -0.1387946265586229
        ],
        "positive_CI": false,
        "stress_net_usd": -1810.4971542830674,
        "stress_mean_net_pct": -0.23181781744981655,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 55.0
      },
      "original_fresh": {
        "n": 154,
        "net_usd": -182.5559304947818,
        "mean_net_pct": -0.11854281200959857,
        "PF": 0.6800545921625182,
        "monthly_CI95_mean_net_pct": [
          -0.20793922417273908,
          -0.04424629641023252
        ],
        "positive_CI": false,
        "stress_net_usd": -234.2101182291267,
        "stress_mean_net_pct": -0.15208449235657576,
        "funding_usd_unchanged": 0.13316026188854982,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 308164.64926828904,
      "fees_new_usd": 30.816464926828907,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_follow_z2_h120",
      "old_full": {
        "n": 1049,
        "net_usd": -892.6704628654636,
        "mean_net_pct": -0.08509727958679347,
        "PF": 0.823843113651609,
        "monthly_CI95_mean_net_pct": [
          -0.13173625703288835,
          -0.03857428403039114
        ],
        "positive_CI": false,
        "stress_net_usd": -1365.3131713944626,
        "stress_mean_net_pct": -0.1301537818297867,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 65.0
      },
      "old_thirds": {
        "train": {
          "n": 334,
          "net_usd": -441.9806534311647,
          "mean_net_pct": -0.13232953695543853,
          "PF": 0.7119246211619198,
          "monthly_CI95_mean_net_pct": [
            -0.21104832141887814,
            -0.06181396600043668
          ],
          "positive_CI": false,
          "stress_net_usd": -543.9950916496459,
          "stress_mean_net_pct": -0.1628727819310317,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 102.0
        },
        "validation": {
          "n": 375,
          "net_usd": -249.99122756741508,
          "mean_net_pct": -0.06666432735131068,
          "PF": 0.8753428580870124,
          "monthly_CI95_mean_net_pct": [
            -0.15990976733664464,
            0.03142308213325234
          ],
          "positive_CI": false,
          "stress_net_usd": -448.34593362866775,
          "stress_mean_net_pct": -0.1195589156343114,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 38.0
        },
        "test": {
          "n": 340,
          "net_usd": -200.69858186688379,
          "mean_net_pct": -0.05902899466673052,
          "PF": 0.8686347230347918,
          "monthly_CI95_mean_net_pct": [
            -0.11757959389735292,
            -0.005548377594676268
          ],
          "positive_CI": false,
          "stress_net_usd": -372.972146116149,
          "stress_mean_net_pct": -0.10969769003416148,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 92.5
        }
      },
      "fresh": {
        "n": 212,
        "net_usd": -166.16239563365792,
        "mean_net_pct": -0.07837848850644241,
        "PF": 0.8121432948033838,
        "monthly_CI95_mean_net_pct": [
          -0.13103461857932858,
          -0.03805594387747612
        ],
        "positive_CI": false,
        "stress_net_usd": -230.9732419054576,
        "stress_mean_net_pct": -0.10894964240823471,
        "funding_usd_unchanged": -0.3322716032976015,
        "median_hold_minutes": 120.0
      },
      "original_old": {
        "n": 1049,
        "net_usd": -1731.9733828083677,
        "mean_net_pct": -0.16510709083015898,
        "PF": 0.6912776089387862,
        "monthly_CI95_mean_net_pct": [
          -0.2117356081417671,
          -0.11857769751953344
        ],
        "positive_CI": false,
        "stress_net_usd": -2204.5798494171463,
        "stress_mean_net_pct": -0.21016013817131995,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 65.0
      },
      "original_fresh": {
        "n": 212,
        "net_usd": -335.7978230589065,
        "mean_net_pct": -0.15839519955608797,
        "PF": 0.6594186275851045,
        "monthly_CI95_mean_net_pct": [
          -0.21104812459726116,
          -0.11806782052892631
        ],
        "positive_CI": false,
        "stress_net_usd": -400.6110628166812,
        "stress_mean_net_pct": -0.1889674824606987,
        "funding_usd_unchanged": -0.3322716032976015,
        "median_hold_minutes": 120.0
      },
      "actual_fresh_turnover_usd": 424088.5685631213,
      "fees_new_usd": 42.408856856312134,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_intraday_impulse_follow_z2_h60",
      "old_full": {
        "n": 1049,
        "net_usd": -919.7229050103244,
        "mean_net_pct": -0.08767615872357716,
        "PF": 0.7953961768857956,
        "monthly_CI95_mean_net_pct": [
          -0.12833420602756268,
          -0.04835503027270855
        ],
        "positive_CI": false,
        "stress_net_usd": -1384.8952184891843,
        "stress_mean_net_pct": -0.13202051653853042,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "old_thirds": {
        "train": {
          "n": 334,
          "net_usd": -396.65484967077924,
          "mean_net_pct": -0.1187589370271794,
          "PF": 0.7094963601608767,
          "monthly_CI95_mean_net_pct": [
            -0.16591929120505655,
            -0.07029847465222759
          ],
          "positive_CI": false,
          "stress_net_usd": -511.38640806516366,
          "stress_mean_net_pct": -0.15310970301352206,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        },
        "validation": {
          "n": 375,
          "net_usd": -318.43818162813614,
          "mean_net_pct": -0.08491684843416963,
          "PF": 0.8231275086647927,
          "monthly_CI95_mean_net_pct": [
            -0.17010374594150487,
            -0.0037865386936775623
          ],
          "positive_CI": false,
          "stress_net_usd": -509.2021654373917,
          "stress_mean_net_pct": -0.13578724411663778,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 38.0
        },
        "test": {
          "n": 340,
          "net_usd": -204.629873711409,
          "mean_net_pct": -0.06018525697394383,
          "PF": 0.8460681345108491,
          "monthly_CI95_mean_net_pct": [
            -0.11448357700882106,
            0.006957795476620069
          ],
          "positive_CI": false,
          "stress_net_usd": -364.30664498662895,
          "stress_mean_net_pct": -0.10714901323136145,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 60.0
        }
      },
      "fresh": {
        "n": 212,
        "net_usd": -234.4717502776372,
        "mean_net_pct": -0.11059988220643263,
        "PF": 0.6785533680113323,
        "monthly_CI95_mean_net_pct": [
          -0.1599483305601439,
          -0.06830680442674868
        ],
        "positive_CI": false,
        "stress_net_usd": -307.31685775033156,
        "stress_mean_net_pct": -0.14496078195770357,
        "funding_usd_unchanged": 0.10922711552155955,
        "median_hold_minutes": 60.0
      },
      "original_old": {
        "n": 1049,
        "net_usd": -1759.0757685685276,
        "mean_net_pct": -0.16769073103608462,
        "PF": 0.6503297012223184,
        "monthly_CI95_mean_net_pct": [
          -0.20835014143318872,
          -0.1283713961501728
        ],
        "positive_CI": false,
        "stress_net_usd": -2224.216528889059,
        "stress_mean_net_pct": -0.2120320809236472,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 60.0
      },
      "original_fresh": {
        "n": 212,
        "net_usd": -404.1227312911288,
        "mean_net_pct": -0.19062392985430604,
        "PF": 0.5175096441320667,
        "monthly_CI95_mean_net_pct": [
          -0.23999652094687474,
          -0.14830605315482379
        ],
        "positive_CI": false,
        "stress_net_usd": -476.97057301642343,
        "stress_mean_net_pct": -0.22498611934736956,
        "funding_usd_unchanged": 0.10922711552155955,
        "median_hold_minutes": 60.0
      },
      "actual_fresh_turnover_usd": 424127.45253372897,
      "fees_new_usd": 42.4127452533729,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_scalp_impulse_follow_z2.5_h15",
      "old_full": {
        "n": 2501,
        "net_usd": -2051.2202347945104,
        "mean_net_pct": -0.08201600299058417,
        "PF": 0.6956343872457911,
        "monthly_CI95_mean_net_pct": [
          -0.10111228623453584,
          -0.06332897454504235
        ],
        "positive_CI": false,
        "stress_net_usd": -3063.722530544244,
        "stress_mean_net_pct": -0.12249990126126525,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "old_thirds": {
        "train": {
          "n": 817,
          "net_usd": -618.1040665349983,
          "mean_net_pct": -0.07565533250122378,
          "PF": 0.7097732844017196,
          "monthly_CI95_mean_net_pct": [
            -0.11097080300123792,
            -0.046127482715975214
          ],
          "positive_CI": false,
          "stress_net_usd": -948.1254636273038,
          "stress_mean_net_pct": -0.11604962835095518,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "validation": {
          "n": 852,
          "net_usd": -659.6919135471661,
          "mean_net_pct": -0.07742862835060636,
          "PF": 0.7394837261088473,
          "monthly_CI95_mean_net_pct": [
            -0.11814122555446162,
            -0.04628766012451127
          ],
          "positive_CI": false,
          "stress_net_usd": -1013.3325083702167,
          "stress_mean_net_pct": -0.11893574041903952,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 832,
          "net_usd": -773.4242547123459,
          "mean_net_pct": -0.09295964599908005,
          "PF": 0.627687617555923,
          "monthly_CI95_mean_net_pct": [
            -0.1217302359121393,
            -0.06540585181781768
          ],
          "positive_CI": false,
          "stress_net_usd": -1102.2645585467233,
          "stress_mean_net_pct": -0.13248372097917346,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        }
      },
      "fresh": {
        "n": 484,
        "net_usd": -518.7582381122713,
        "mean_net_pct": -0.10718145415542794,
        "PF": 0.5493697484770241,
        "monthly_CI95_mean_net_pct": [
          -0.14034794222251337,
          -0.07160270853273058
        ],
        "positive_CI": false,
        "stress_net_usd": -714.118260824156,
        "stress_mean_net_pct": -0.14754509521160247,
        "funding_usd_unchanged": 0.023432933537212514,
        "median_hold_minutes": 15.0
      },
      "original_old": {
        "n": 2501,
        "net_usd": -4052.1278406432516,
        "mean_net_pct": -0.16202030550352864,
        "PF": 0.49915458970001053,
        "monthly_CI95_mean_net_pct": [
          -0.1811195737076473,
          -0.1433288827769747
        ],
        "positive_CI": false,
        "stress_net_usd": -5064.630282367273,
        "stress_mean_net_pct": -0.20250420961084656,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "original_fresh": {
        "n": 484,
        "net_usd": -906.0290632198638,
        "mean_net_pct": -0.18719608744212063,
        "PF": 0.36425327774990124,
        "monthly_CI95_mean_net_pct": [
          -0.22035239676165863,
          -0.15162066961193632
        ],
        "positive_CI": false,
        "stress_net_usd": -1101.3945777933334,
        "stress_mean_net_pct": -0.2275608631804408,
        "funding_usd_unchanged": 0.023432933537212514,
        "median_hold_minutes": 15.0
      },
      "actual_fresh_turnover_usd": 968177.0627689807,
      "fees_new_usd": 96.81770627689808,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_scalp_impulse_follow_z2.5_h30",
      "old_full": {
        "n": 2501,
        "net_usd": -2052.617275616579,
        "mean_net_pct": -0.08207186227975126,
        "PF": 0.7385691656488518,
        "monthly_CI95_mean_net_pct": [
          -0.10518895981025897,
          -0.06222053225072261
        ],
        "positive_CI": false,
        "stress_net_usd": -3094.359292696906,
        "stress_mean_net_pct": -0.12372488175517417,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 25.0
      },
      "old_thirds": {
        "train": {
          "n": 817,
          "net_usd": -486.1332597075981,
          "mean_net_pct": -0.05950223497033024,
          "PF": 0.79943057710531,
          "monthly_CI95_mean_net_pct": [
            -0.08968724992716834,
            -0.03546078791380056
          ],
          "positive_CI": false,
          "stress_net_usd": -826.4577859419355,
          "stress_mean_net_pct": -0.101157623738303,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 29.0
        },
        "validation": {
          "n": 852,
          "net_usd": -825.9244991935113,
          "mean_net_pct": -0.09693949521050602,
          "PF": 0.7252653897000965,
          "monthly_CI95_mean_net_pct": [
            -0.14982510188453202,
            -0.05701673962196733
          ],
          "positive_CI": false,
          "stress_net_usd": -1198.580456528063,
          "stress_mean_net_pct": -0.14067845733897452,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 832,
          "net_usd": -740.5595167154694,
          "mean_net_pct": -0.08900955729753238,
          "PF": 0.6941662799068506,
          "monthly_CI95_mean_net_pct": [
            -0.11919836948717544,
            -0.05912367675152315
          ],
          "positive_CI": false,
          "stress_net_usd": -1069.3210502269071,
          "stress_mean_net_pct": -0.12852416469073402,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        }
      },
      "fresh": {
        "n": 484,
        "net_usd": -522.6596740464347,
        "mean_net_pct": -0.10798753596000717,
        "PF": 0.6158642090193447,
        "monthly_CI95_mean_net_pct": [
          -0.15413709198442652,
          -0.05329551902879157
        ],
        "positive_CI": false,
        "stress_net_usd": -726.4555981474987,
        "stress_mean_net_pct": -0.15009413184865678,
        "funding_usd_unchanged": 0.3318185914438462,
        "median_hold_minutes": 30.0
      },
      "original_old": {
        "n": 2501,
        "net_usd": -4053.5664719267857,
        "mean_net_pct": -0.16207782774597304,
        "PF": 0.5585165235204361,
        "monthly_CI95_mean_net_pct": [
          -0.18519350885920047,
          -0.14222727641528218
        ],
        "positive_CI": false,
        "stress_net_usd": -5095.313342252906,
        "stress_mean_net_pct": -0.2037310412736068,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 25.0
      },
      "original_fresh": {
        "n": 484,
        "net_usd": -909.9000076482365,
        "mean_net_pct": -0.18799586934880919,
        "PF": 0.4397727078169696,
        "monthly_CI95_mean_net_pct": [
          -0.2341252126983111,
          -0.13330506481297888
        ],
        "positive_CI": false,
        "stress_net_usd": -1113.7075338068785,
        "stress_mean_net_pct": -0.2301048623567931,
        "funding_usd_unchanged": 0.3318185914438462,
        "median_hold_minutes": 30.0
      },
      "actual_fresh_turnover_usd": 968100.8340045044,
      "fees_new_usd": 96.81008340045044,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_scalp_impulse_follow_z2_h15",
      "old_full": {
        "n": 3566,
        "net_usd": -2536.2668849256984,
        "mean_net_pct": -0.07112358062046266,
        "PF": 0.7164065132875238,
        "monthly_CI95_mean_net_pct": [
          -0.0890553692013965,
          -0.053045602919449084
        ],
        "positive_CI": false,
        "stress_net_usd": -3957.9240312000993,
        "stress_mean_net_pct": -0.11099057855300334,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "old_thirds": {
        "train": {
          "n": 1159,
          "net_usd": -729.6734616160265,
          "mean_net_pct": -0.06295715803416968,
          "PF": 0.7401750844064308,
          "monthly_CI95_mean_net_pct": [
            -0.09088026601560623,
            -0.04252097849504937
          ],
          "positive_CI": false,
          "stress_net_usd": -1185.3326639940474,
          "stress_mean_net_pct": -0.10227201587524135,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "validation": {
          "n": 1211,
          "net_usd": -805.0757828693233,
          "mean_net_pct": -0.06648024631456015,
          "PF": 0.7589978198177797,
          "monthly_CI95_mean_net_pct": [
            -0.10053211014220473,
            -0.03699991222128067
          ],
          "positive_CI": false,
          "stress_net_usd": -1294.70813060776,
          "stress_mean_net_pct": -0.10691231466620646,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        },
        "test": {
          "n": 1196,
          "net_usd": -1001.5176404403485,
          "mean_net_pct": -0.08373893314718633,
          "PF": 0.6416057398665094,
          "monthly_CI95_mean_net_pct": [
            -0.11728996181357956,
            -0.046281843249862696
          ],
          "positive_CI": false,
          "stress_net_usd": -1477.883236598292,
          "stress_mean_net_pct": -0.12356883249149597,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 15.0
        }
      },
      "fresh": {
        "n": 718,
        "net_usd": -497.4563846797724,
        "mean_net_pct": -0.06928361903618,
        "PF": 0.6565289759314811,
        "monthly_CI95_mean_net_pct": [
          -0.07622107813193155,
          -0.059974297473528795
        ],
        "positive_CI": false,
        "stress_net_usd": -820.4937062500626,
        "stress_mean_net_pct": -0.11427488944986944,
        "funding_usd_unchanged": 0.08785318126931367,
        "median_hold_minutes": 15.0
      },
      "original_old": {
        "n": 3566,
        "net_usd": -5389.280923017755,
        "mean_net_pct": -0.15112958281036892,
        "PF": 0.5027425367245771,
        "monthly_CI95_mean_net_pct": [
          -0.16906053613094127,
          -0.13305246215719005
        ],
        "positive_CI": false,
        "stress_net_usd": -6810.948669220801,
        "stress_mean_net_pct": -0.19099687799273138,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 15.0
      },
      "original_fresh": {
        "n": 718,
        "net_usd": -1071.896315206199,
        "mean_net_pct": -0.14928918039083552,
        "PF": 0.41569193086840034,
        "monthly_CI95_mean_net_pct": [
          -0.1562359665344807,
          -0.13997131148882938
        ],
        "positive_CI": false,
        "stress_net_usd": -1394.935162501072,
        "stress_mean_net_pct": -0.19428066330098495,
        "funding_usd_unchanged": 0.08785318126931367,
        "median_hold_minutes": 15.0
      },
      "actual_fresh_turnover_usd": 1436099.8263160668,
      "fees_new_usd": 143.6099826316067,
      "passes_economic_period_gate": false
    },
    {
      "name": "XRPUSDT_scalp_impulse_follow_z2_h30",
      "old_full": {
        "n": 3566,
        "net_usd": -2534.59210500977,
        "mean_net_pct": -0.071076615395675,
        "PF": 0.7604698724929877,
        "monthly_CI95_mean_net_pct": [
          -0.08946105344560541,
          -0.05177171570366106
        ],
        "positive_CI": false,
        "stress_net_usd": -4021.6520497180168,
        "stress_mean_net_pct": -0.11277767946489109,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "old_thirds": {
        "train": {
          "n": 1159,
          "net_usd": -625.3420758340731,
          "mean_net_pct": -0.05395531284159388,
          "PF": 0.8065300238748006,
          "monthly_CI95_mean_net_pct": [
            -0.08082922991151274,
            -0.0319018465811455
          ],
          "positive_CI": false,
          "stress_net_usd": -1113.4661023252793,
          "stress_mean_net_pct": -0.0960712771635271,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        },
        "validation": {
          "n": 1211,
          "net_usd": -954.2799288474085,
          "mean_net_pct": -0.07880098504107419,
          "PF": 0.7621708388597812,
          "monthly_CI95_mean_net_pct": [
            -0.12332179130524522,
            -0.033865808926644994
          ],
          "positive_CI": false,
          "stress_net_usd": -1469.309162017542,
          "stress_mean_net_pct": -0.12133023633505713,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 19.0
        },
        "test": {
          "n": 1196,
          "net_usd": -954.9701003282884,
          "mean_net_pct": -0.07984699835520805,
          "PF": 0.7138077877121218,
          "monthly_CI95_mean_net_pct": [
            -0.10315249192273492,
            -0.053962426595693246
          ],
          "positive_CI": false,
          "stress_net_usd": -1438.876785375196,
          "stress_mean_net_pct": -0.12030742352635419,
          "funding_usd_unchanged": 0.0,
          "median_hold_minutes": 30.0
        }
      },
      "fresh": {
        "n": 718,
        "net_usd": -400.476637692327,
        "mean_net_pct": -0.05577669048639651,
        "PF": 0.768915280180878,
        "monthly_CI95_mean_net_pct": [
          -0.07897047716422649,
          -0.030265782066628902
        ],
        "positive_CI": false,
        "stress_net_usd": -757.0450978858332,
        "stress_mean_net_pct": -0.10543803591724697,
        "funding_usd_unchanged": 0.44709609640681497,
        "median_hold_minutes": 30.0
      },
      "original_old": {
        "n": 3566,
        "net_usd": -5387.669973747938,
        "mean_net_pct": -0.1510844075644402,
        "PF": 0.567541136683573,
        "monthly_CI95_mean_net_pct": [
          -0.16946528524315616,
          -0.13178436516833744
        ],
        "positive_CI": false,
        "stress_net_usd": -6874.730231438111,
        "stress_mean_net_pct": -0.19278548041049107,
        "funding_usd_unchanged": 0.0,
        "median_hold_minutes": 30.0
      },
      "original_fresh": {
        "n": 718,
        "net_usd": -974.8759710969334,
        "mean_net_pct": -0.13577659764581246,
        "PF": 0.5365202464459423,
        "monthly_CI95_mean_net_pct": [
          -0.15898377973859432,
          -0.1102713253563336
        ],
        "positive_CI": false,
        "stress_net_usd": -1331.454734579911,
        "stress_mean_net_pct": -0.18543937807519653,
        "funding_usd_unchanged": 0.44709609640681497,
        "median_hold_minutes": 30.0
      },
      "actual_fresh_turnover_usd": 1435998.3335115162,
      "fees_new_usd": 143.59983335115163,
      "passes_economic_period_gate": false
    }
  ],
  "sources": [
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_fade_control_z2.5_h120.csv",
      "sha256": "99510b3529331dfda0363016abb38af7e4f41af61acef735789872b274e881a4"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_fade_control_z2.5_h120.csv",
      "sha256": "21f63180654d8ff17474a3531e6655dfeef10cd16ebbe69fbd0f1eaa1959b1ac"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_fade_control_z2.5_h60.csv",
      "sha256": "49013b73dea82037b896877ac91c35965ff0b07a6d51a24bcada2cab0b135ad7"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_fade_control_z2.5_h60.csv",
      "sha256": "4f5ae4d6db82fc77038351d8ed6322f6c0f3afc88a29885ec4d5c5b0344eff84"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_fade_control_z2_h120.csv",
      "sha256": "3b4763f3e32f312a012477b6b891b7184dc19d97e0e40839f48854165bfd5d8f"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_fade_control_z2_h120.csv",
      "sha256": "b5c9fe78b5856619bee6b647ef458aae0afd6a22faf9158123bd5bd03eea78a0"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_fade_control_z2_h60.csv",
      "sha256": "3e0450f24ccb4164600dff85d68df21fac368e4a59c6cbe65e9672b2fdbb5254"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_fade_control_z2_h60.csv",
      "sha256": "5a81cca823a24d00390d3aee455179a2380743fba25ccd802fac19470bf87376"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_follow_z2.5_h120.csv",
      "sha256": "3a90db064f25a7521b3912485b56d316371a218d68914b791f2999a1ef0f177e"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_follow_z2.5_h120.csv",
      "sha256": "565c029a3b473527aedc051e3d290b65ef96bdefd5b6f4b96fbb659222714bd8"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_follow_z2.5_h60.csv",
      "sha256": "37f518d5c613c7ff456fb8c7d77a7fe02cdca9779e5b9e7ff4d911d514df1c5b"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_follow_z2.5_h60.csv",
      "sha256": "964394b524d7c83d28ec4c35bb1ed508ec613f630d57e2d365546497e2177c24"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_follow_z2_h120.csv",
      "sha256": "b34f48f73779c6548f5253c790857e15c24685f5f9373914bb09bfedd4a2e2ae"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_follow_z2_h120.csv",
      "sha256": "b4cf9d4e6b713f75a90b8c58719b2926a453452fe5dae6d6c511f49ed6257f52"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_intraday_impulse_follow_z2_h60.csv",
      "sha256": "ae2d4af14855cca70168dec62347a7c1bd53323605b363ab5e30842865da8ebc"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_intraday_impulse_follow_z2_h60.csv",
      "sha256": "b1068489158b53ea6f75f96b38e5f0a873c623735c229fdb857f5ec6a49eef65"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_scalp_impulse_follow_z2.5_h15.csv",
      "sha256": "f4451e43db299804da551369b5556a4371cea34caa2d7aa6e9bf425acc6f3301"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_scalp_impulse_follow_z2.5_h15.csv",
      "sha256": "aa93fa9bd37030834db7d491258157e34f5944b527d79f9b958049cfc82b204f"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_scalp_impulse_follow_z2.5_h30.csv",
      "sha256": "af010858f854f30ff0bf0d59009de777a6248b6722d98e6a6df0686c93bac2ce"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_scalp_impulse_follow_z2.5_h30.csv",
      "sha256": "99f65823258bdbd976136348b9b98c9d3b7c85f0b01daec5500bcbbd95110ed7"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_scalp_impulse_follow_z2_h15.csv",
      "sha256": "62d8807951fd0c958c65573e20d17b9a3579b663a9f5cbbad20b7acef6ff826f"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_scalp_impulse_follow_z2_h15.csv",
      "sha256": "ca7a6f85c43bd60c2b03f79fa1aac0cec9da9caddb35b3980afbb01d308a84a7"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_BTCUSDT_scalp_impulse_follow_z2_h30.csv",
      "sha256": "af65167ee385cbe553b8109ea306f8e91e1a769710e3c0d62c37f9293048c3f0"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_BTCUSDT_scalp_impulse_follow_z2_h30.csv",
      "sha256": "7f4c192416fc03d0fece795d4d791a7dd69574d32f38046544e0c9066126c538"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_fade_control_z2.5_h120.csv",
      "sha256": "427e9e6f97b9c8d97c08dea86f890e8a2e2ab6dcac1c820bfa8c44eb60e4ef68"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_fade_control_z2.5_h120.csv",
      "sha256": "c69d8c779114a1a302a7c5f682bfac70e86225f763470e64fb7efc3b4f6b76ba"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_fade_control_z2.5_h60.csv",
      "sha256": "dd2c9616d5c7bf47c7d3b3541c774e3657f87485ecc3531d0ad69b53eccd4050"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_fade_control_z2.5_h60.csv",
      "sha256": "251085b04511185bf518601d5bddc4e9aa38191f51e4125f7af2080b93efb7bd"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_fade_control_z2_h120.csv",
      "sha256": "f32a829c520b68356e980845ffd2b612bd1bc54e52bf96617486f390725156fa"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_fade_control_z2_h120.csv",
      "sha256": "f142fee04bfd9321bc79234234189d3b451b92f6938d91c882b9060b26278e8b"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_fade_control_z2_h60.csv",
      "sha256": "b8368e417fe13ff03d4e000b9e41de8d937d45f3c2355b879fd704e002fd8705"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_fade_control_z2_h60.csv",
      "sha256": "2707d89006d44bec6e1d5ed9c1991cd37bf42b435f62005cec97ed4d38ad66d6"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_follow_z2.5_h120.csv",
      "sha256": "5a8e70f292bba7fd742efa32911b3dc91a48de51792ff0b0ab5d4a3ca36fefd1"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_follow_z2.5_h120.csv",
      "sha256": "8622db644296a0002210bfa52d746ce9e6c913aca45e1364adb0a15a58a6f985"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_follow_z2.5_h60.csv",
      "sha256": "fba185cfa1d98039b7c37391c4899a77becebedc4eeb1c7bd25a13e7f4ed06bc"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_follow_z2.5_h60.csv",
      "sha256": "3c787096fff3d2e37ef17b506f5f571aa37291a1d457c0b6ec638b70af0ee031"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_follow_z2_h120.csv",
      "sha256": "42425f92c7296122d9d6b4a08d51d915b112ca32a214317b868b7c0e615652a0"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_follow_z2_h120.csv",
      "sha256": "00ea26aea391c68c1b8d6b854af9cf0e5d7e69bfb0fafa35dc396fcfc9f1e238"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_intraday_impulse_follow_z2_h60.csv",
      "sha256": "67bf176268931f84eb857aee2755fc47fee4b0dfa2e0af965ce6d10b837dfee1"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_intraday_impulse_follow_z2_h60.csv",
      "sha256": "d08d9a7c3c4795baf3e5ad230d6e32a58978360a8896f349ddb49079864d6014"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_scalp_impulse_follow_z2.5_h15.csv",
      "sha256": "dcf451b2beb3df1c7a1042972a9e87467a3ce14cbd9474fc4443ba2e140464bf"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_scalp_impulse_follow_z2.5_h15.csv",
      "sha256": "a80793885ed0a7d99c06bfd078d9bc9b90a4c0ce185b8dd452cd2dafff941d5a"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_scalp_impulse_follow_z2.5_h30.csv",
      "sha256": "d99520a3fabe90f987b0fbf1d751300b4e9c41392b54c2a851c4a5b239654fa1"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_scalp_impulse_follow_z2.5_h30.csv",
      "sha256": "b4b64c716094b4a587804e9727b5708d34f9831431b68ffd2467a3920fa92043"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_scalp_impulse_follow_z2_h15.csv",
      "sha256": "53db376daf6bf868044cdb1311c94136513e7c6ccd40f6d548c5e5b05e96d919"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_scalp_impulse_follow_z2_h15.csv",
      "sha256": "46a40db44dcdd92e8d1d5c2f5bb0739e4b86e3c7d371edfee4201ebf69ae74ff"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_ETHUSDT_scalp_impulse_follow_z2_h30.csv",
      "sha256": "0bec5c9b9e3516721346119eee5a50f4ea810027b6570a0af9aa4af0aca0dacd"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_ETHUSDT_scalp_impulse_follow_z2_h30.csv",
      "sha256": "6f5d9252f4ffc367b2c7eb56fd7bea89b447ea5bbca361c8622f74cce3fa547d"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_fade_control_z2.5_h120.csv",
      "sha256": "ddde97286f1e1f6e0e89bfe1fa5b3b2cac906d13250e0bac84d06813cd0f2423"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_fade_control_z2.5_h120.csv",
      "sha256": "477c4590fd340d24042f96536fd579b5cf718c3991d5fe8e7a92d334b1eb3057"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_fade_control_z2.5_h60.csv",
      "sha256": "de1a585f003fef9c3777d297888611380257b756e2284bc7ebb65aaf4f843063"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_fade_control_z2.5_h60.csv",
      "sha256": "6d85dffcb20c623e8ec9bea31cb6f607592f118271c7f39b911fc85226449110"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_fade_control_z2_h120.csv",
      "sha256": "ac91307b404d0a1ef52204458790edf730b023f7f2fc28a5de9fefa329dc7604"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_fade_control_z2_h120.csv",
      "sha256": "fe8d76a8196f9bcfd1cf493828b0f323f490514443d33ee5d500c828e56e0351"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_fade_control_z2_h60.csv",
      "sha256": "4d6169ff6e45622948e0505d9e1d745338930ced4a9f152001c9482eb1ccaabc"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_fade_control_z2_h60.csv",
      "sha256": "0e10513ed341f9974f38b1d672c38a27a3806393721575003187811d08fd44b2"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_follow_z2.5_h120.csv",
      "sha256": "8cd70e69c0d7f4f21043c119aa983b8384ce25de68e6527fd5d6d406dc69fe22"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_follow_z2.5_h120.csv",
      "sha256": "1298fdad6146ae3af15ccba93ec2a5dec77565c3238e915f461da72aae0b9c57"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_follow_z2.5_h60.csv",
      "sha256": "118bcca03cfbd867403ee7631b9e816229edbcd1bc63f9a1137f22f2a6e582c7"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_follow_z2.5_h60.csv",
      "sha256": "0c5a1785e8b69b73ba03c5da6d967693687a3bee178b71a4803b8f9c929014b6"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_follow_z2_h120.csv",
      "sha256": "2f98976d59762e7f4a1ebbba713a453af48f76563104eaff91629687b3ac4293"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_follow_z2_h120.csv",
      "sha256": "0def873f66b83c7cf9dfc5b7a1abe8fa23ae25c3f3ee3e3549127361f08c7ba9"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_intraday_impulse_follow_z2_h60.csv",
      "sha256": "58d79af4a5110006702d0920f1a63c924349726714a3c0896dfe4e5d0f2578f3"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_intraday_impulse_follow_z2_h60.csv",
      "sha256": "0e321a32785034a7c524fdcc3685a35a0d1af2b01e82df3ee3c19a3fda4170c9"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_scalp_impulse_follow_z2.5_h15.csv",
      "sha256": "4aec048e3aa8ef3c8c19143907c3952dbe8083e1f47a959b68bf0537e23c1dd1"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_scalp_impulse_follow_z2.5_h15.csv",
      "sha256": "ed233335d572f0748a54b431f0a197cc0629ede8438722fea809ed0fdb732d73"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_scalp_impulse_follow_z2.5_h30.csv",
      "sha256": "2873a2f1766854ced2e97f09d0eb0ce34fb8ab8562d8c706a2d46cb8f2de061c"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_scalp_impulse_follow_z2.5_h30.csv",
      "sha256": "f98c1fa35d37397fb1d4c824bc014d9dfceb1644f8dc0c7f56baf0a0844be83a"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_scalp_impulse_follow_z2_h15.csv",
      "sha256": "ea424c19aec39a0c01122b20ad6dbc9fe4dc3ec59a3ef71402a0b6ff5081059c"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_scalp_impulse_follow_z2_h15.csv",
      "sha256": "6e76160e197c654e561a8abe5c001997c8cf3f09106c5013ace23080628861a0"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\trades_XRPUSDT_scalp_impulse_follow_z2_h30.csv",
      "sha256": "1acec3c5f4b55a73fb076435b627da771ded0b408e8eeb24e34f82785e066cab"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_trades_XRPUSDT_scalp_impulse_follow_z2_h30.csv",
      "sha256": "316034c823bed3a4cef5fc87e8da859c7ff52952bb79e350318af52a512d54a8"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\spec.json",
      "sha256": "14217aa6b8e21623574c8610503bbd574038800ee756e6a786e195832911a9bb"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\run_intraday.py",
      "sha256": "df78bb89aaddc9d4c7bfa57d9aa3c8eec92cb1fd21dcb81ce641df9be296c6c3"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\validate_fresh.py",
      "sha256": "0addc81cddaa1eb03ba2075c6dbf41dbce85da6a66180c4fc1df6f59dc07d521"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\intraday\\fresh_audit.json",
      "sha256": "110f765101b9ab6f61b92b63cd6db71c4c45eef69f7e1d662658a930228ab408"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_BTCUSDT_funding.csv",
      "sha256": "010ee5a28b9a2d616cd0be7a07c6a4b60226fcf7d973bbd5ad5af58658e6ce14"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_BTCUSDT_1m.csv",
      "sha256": "e10c39164c6111c151b45d8cffce3bfd1cdbe86221e8dbebad02a84c5b0394f2"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_funding.csv",
      "sha256": "46bb8603c2988336deb0ed7eb75477a2cc0981b848b3816aa21e44920bdd449a"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_ETHUSDT_1m.csv",
      "sha256": "352556b14ffcc1e3d6811e96c823c57c8ee9633002385701d78226cfd9f5f3c8"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_funding.csv",
      "sha256": "148a92ce5743d8fc59ec40703fbce7ecfcde356e041690fcdee663a32781d4bf"
    },
    {
      "path": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_XRPUSDT_1m.csv",
      "sha256": "d6e61c811e0d7e2f8b98e66fd67928ad2d574790a051cb52cdbb8783050c42f6"
    }
  ],
  "controls_repriced_scope": "Original 64 accepted fresh draws on the three previously described z2.5/120 reference cells; no new search.",
  "verification": {
    "base_and_stress_reference_cash_match_original_engine_at_new_fee": true,
    "original_control_draws_and_old_fee_results_reproduced": true
  }
}
```

</details>

<details>
<summary>manual/manual_placebo_sensitivity.json</summary>

```json
[
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 1,
    "shift_weeks": [
      15
    ],
    "n": 158,
    "new_mean_net_pct": -0.10748400307640882,
    "old_mean_net_pct_verified": -0.18750866459103718
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 2,
    "shift_weeks": [
      16
    ],
    "n": 158,
    "new_mean_net_pct": -0.07894116426502606,
    "old_mean_net_pct_verified": -0.15896094416176335
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 3,
    "shift_weeks": [
      8
    ],
    "n": 158,
    "new_mean_net_pct": -0.1184652237462201,
    "old_mean_net_pct_verified": -0.1984895018431857
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 4,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 5,
    "shift_weeks": [
      11
    ],
    "n": 158,
    "new_mean_net_pct": -0.08667715726942538,
    "old_mean_net_pct_verified": -0.16665192528614706
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 6,
    "shift_weeks": [
      19
    ],
    "n": 158,
    "new_mean_net_pct": -0.02503753857284093,
    "old_mean_net_pct_verified": -0.10504888466669964
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 7,
    "shift_weeks": [
      19
    ],
    "n": 158,
    "new_mean_net_pct": -0.02503753857284093,
    "old_mean_net_pct_verified": -0.10504888466669964
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 8,
    "shift_weeks": [
      6
    ],
    "n": 158,
    "new_mean_net_pct": -0.10285918197152318,
    "old_mean_net_pct_verified": -0.18285207227680672
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 9,
    "shift_weeks": [
      18
    ],
    "n": 158,
    "new_mean_net_pct": -0.13537872110754307,
    "old_mean_net_pct_verified": -0.21538798194641393
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 10,
    "shift_weeks": [
      11
    ],
    "n": 158,
    "new_mean_net_pct": -0.08667715726942538,
    "old_mean_net_pct_verified": -0.16665192528614706
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 11,
    "shift_weeks": [
      3
    ],
    "n": 158,
    "new_mean_net_pct": -0.11489057799544172,
    "old_mean_net_pct_verified": -0.19489637988476216
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 12,
    "shift_weeks": [
      5
    ],
    "n": 158,
    "new_mean_net_pct": -0.1497740324209459,
    "old_mean_net_pct_verified": -0.22976742489398652
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 13,
    "shift_weeks": [
      19
    ],
    "n": 158,
    "new_mean_net_pct": -0.02503753857284093,
    "old_mean_net_pct_verified": -0.10504888466669964
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 14,
    "shift_weeks": [
      12
    ],
    "n": 158,
    "new_mean_net_pct": -0.08339837380079981,
    "old_mean_net_pct_verified": -0.16340183689307347
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 15,
    "shift_weeks": [
      16
    ],
    "n": 158,
    "new_mean_net_pct": -0.07894116426502606,
    "old_mean_net_pct_verified": -0.15896094416176335
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 16,
    "shift_weeks": [
      6
    ],
    "n": 158,
    "new_mean_net_pct": -0.10285918197152318,
    "old_mean_net_pct_verified": -0.18285207227680672
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 17,
    "shift_weeks": [
      3
    ],
    "n": 158,
    "new_mean_net_pct": -0.11489057799544172,
    "old_mean_net_pct_verified": -0.19489637988476216
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 18,
    "shift_weeks": [
      17
    ],
    "n": 158,
    "new_mean_net_pct": -0.06541763326815318,
    "old_mean_net_pct_verified": -0.14541616935830518
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 19,
    "shift_weeks": [
      14
    ],
    "n": 158,
    "new_mean_net_pct": 0.02739396889278426,
    "old_mean_net_pct_verified": -0.05259978212539451
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 20,
    "shift_weeks": [
      18
    ],
    "n": 158,
    "new_mean_net_pct": -0.13537872110754307,
    "old_mean_net_pct_verified": -0.21538798194641393
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 21,
    "shift_weeks": [
      18
    ],
    "n": 158,
    "new_mean_net_pct": -0.13537872110754307,
    "old_mean_net_pct_verified": -0.21538798194641393
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 22,
    "shift_weeks": [
      4
    ],
    "n": 158,
    "new_mean_net_pct": -0.010616499938828891,
    "old_mean_net_pct_verified": -0.09061124178171225
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 23,
    "shift_weeks": [
      5
    ],
    "n": 158,
    "new_mean_net_pct": -0.1497740324209459,
    "old_mean_net_pct_verified": -0.22976742489398652
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 24,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 25,
    "shift_weeks": [
      2
    ],
    "n": 158,
    "new_mean_net_pct": -0.14181578324223906,
    "old_mean_net_pct_verified": -0.22183244918057002
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 26,
    "shift_weeks": [
      18
    ],
    "n": 158,
    "new_mean_net_pct": -0.13537872110754307,
    "old_mean_net_pct_verified": -0.21538798194641393
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 27,
    "shift_weeks": [
      10
    ],
    "n": 157,
    "new_mean_net_pct": -0.07845514187608348,
    "old_mean_net_pct_verified": -0.15844589752066807
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 28,
    "shift_weeks": [
      16
    ],
    "n": 158,
    "new_mean_net_pct": -0.07894116426502606,
    "old_mean_net_pct_verified": -0.15896094416176335
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 29,
    "shift_weeks": [
      4
    ],
    "n": 158,
    "new_mean_net_pct": -0.010616499938828891,
    "old_mean_net_pct_verified": -0.09061124178171225
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 30,
    "shift_weeks": [
      12
    ],
    "n": 158,
    "new_mean_net_pct": -0.08339837380079981,
    "old_mean_net_pct_verified": -0.16340183689307347
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 31,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 32,
    "shift_weeks": [
      19
    ],
    "n": 158,
    "new_mean_net_pct": -0.02503753857284093,
    "old_mean_net_pct_verified": -0.10504888466669964
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 33,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 34,
    "shift_weeks": [
      2
    ],
    "n": 158,
    "new_mean_net_pct": -0.14181578324223906,
    "old_mean_net_pct_verified": -0.22183244918057002
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 35,
    "shift_weeks": [
      16
    ],
    "n": 158,
    "new_mean_net_pct": -0.07894116426502606,
    "old_mean_net_pct_verified": -0.15896094416176335
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 36,
    "shift_weeks": [
      18
    ],
    "n": 158,
    "new_mean_net_pct": -0.13537872110754307,
    "old_mean_net_pct_verified": -0.21538798194641393
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 37,
    "shift_weeks": [
      13
    ],
    "n": 158,
    "new_mean_net_pct": -0.08919240664781075,
    "old_mean_net_pct_verified": -0.16920082510470535
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 38,
    "shift_weeks": [
      12
    ],
    "n": 158,
    "new_mean_net_pct": -0.08339837380079981,
    "old_mean_net_pct_verified": -0.16340183689307347
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 39,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 40,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 41,
    "shift_weeks": [
      4
    ],
    "n": 158,
    "new_mean_net_pct": -0.010616499938828891,
    "old_mean_net_pct_verified": -0.09061124178171225
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 42,
    "shift_weeks": [
      11
    ],
    "n": 158,
    "new_mean_net_pct": -0.08667715726942538,
    "old_mean_net_pct_verified": -0.16665192528614706
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 43,
    "shift_weeks": [
      10
    ],
    "n": 157,
    "new_mean_net_pct": -0.07845514187608348,
    "old_mean_net_pct_verified": -0.15844589752066807
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 44,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 45,
    "shift_weeks": [
      12
    ],
    "n": 158,
    "new_mean_net_pct": -0.08339837380079981,
    "old_mean_net_pct_verified": -0.16340183689307347
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 46,
    "shift_weeks": [
      6
    ],
    "n": 158,
    "new_mean_net_pct": -0.10285918197152318,
    "old_mean_net_pct_verified": -0.18285207227680672
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 47,
    "shift_weeks": [
      8
    ],
    "n": 158,
    "new_mean_net_pct": -0.1184652237462201,
    "old_mean_net_pct_verified": -0.1984895018431857
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 48,
    "shift_weeks": [
      12
    ],
    "n": 158,
    "new_mean_net_pct": -0.08339837380079981,
    "old_mean_net_pct_verified": -0.16340183689307347
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 49,
    "shift_weeks": [
      16
    ],
    "n": 158,
    "new_mean_net_pct": -0.07894116426502606,
    "old_mean_net_pct_verified": -0.15896094416176335
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 50,
    "shift_weeks": [
      13
    ],
    "n": 158,
    "new_mean_net_pct": -0.08919240664781075,
    "old_mean_net_pct_verified": -0.16920082510470535
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 51,
    "shift_weeks": [
      14
    ],
    "n": 158,
    "new_mean_net_pct": 0.02739396889278426,
    "old_mean_net_pct_verified": -0.05259978212539451
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 52,
    "shift_weeks": [
      16
    ],
    "n": 158,
    "new_mean_net_pct": -0.07894116426502606,
    "old_mean_net_pct_verified": -0.15896094416176335
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 53,
    "shift_weeks": [
      3
    ],
    "n": 158,
    "new_mean_net_pct": -0.11489057799544172,
    "old_mean_net_pct_verified": -0.19489637988476216
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 54,
    "shift_weeks": [
      17
    ],
    "n": 158,
    "new_mean_net_pct": -0.06541763326815318,
    "old_mean_net_pct_verified": -0.14541616935830518
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 55,
    "shift_weeks": [
      12
    ],
    "n": 158,
    "new_mean_net_pct": -0.08339837380079981,
    "old_mean_net_pct_verified": -0.16340183689307347
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 56,
    "shift_weeks": [
      17
    ],
    "n": 158,
    "new_mean_net_pct": -0.06541763326815318,
    "old_mean_net_pct_verified": -0.14541616935830518
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 57,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 58,
    "shift_weeks": [
      17
    ],
    "n": 158,
    "new_mean_net_pct": -0.06541763326815318,
    "old_mean_net_pct_verified": -0.14541616935830518
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 59,
    "shift_weeks": [
      6
    ],
    "n": 158,
    "new_mean_net_pct": -0.10285918197152318,
    "old_mean_net_pct_verified": -0.18285207227680672
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 60,
    "shift_weeks": [
      17
    ],
    "n": 158,
    "new_mean_net_pct": -0.06541763326815318,
    "old_mean_net_pct_verified": -0.14541616935830518
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 61,
    "shift_weeks": [
      2
    ],
    "n": 158,
    "new_mean_net_pct": -0.14181578324223906,
    "old_mean_net_pct_verified": -0.22183244918057002
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 62,
    "shift_weeks": [
      7
    ],
    "n": 158,
    "new_mean_net_pct": -0.051196306684614584,
    "old_mean_net_pct_verified": -0.13119105811355625
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 63,
    "shift_weeks": [
      17
    ],
    "n": 158,
    "new_mean_net_pct": -0.06541763326815318,
    "old_mean_net_pct_verified": -0.14541616935830518
  },
  {
    "name": "BTCUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 64,
    "shift_weeks": [
      10
    ],
    "n": 157,
    "new_mean_net_pct": -0.07845514187608348,
    "old_mean_net_pct_verified": -0.15844589752066807
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 1,
    "shift_weeks": [
      15
    ],
    "n": 174,
    "new_mean_net_pct": -0.11256340243774939,
    "old_mean_net_pct_verified": -0.1925956772367299
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 2,
    "shift_weeks": [
      16
    ],
    "n": 174,
    "new_mean_net_pct": -0.15267724272716918,
    "old_mean_net_pct_verified": -0.23270614701693687
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 3,
    "shift_weeks": [
      8
    ],
    "n": 174,
    "new_mean_net_pct": -0.0229264522344753,
    "old_mean_net_pct_verified": -0.10294675185710025
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 4,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 5,
    "shift_weeks": [
      11
    ],
    "n": 174,
    "new_mean_net_pct": -0.12621475081803324,
    "old_mean_net_pct_verified": -0.20621373380673466
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 6,
    "shift_weeks": [
      19
    ],
    "n": 174,
    "new_mean_net_pct": -0.026606482287077845,
    "old_mean_net_pct_verified": -0.10660288029324962
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 7,
    "shift_weeks": [
      19
    ],
    "n": 174,
    "new_mean_net_pct": -0.026606482287077845,
    "old_mean_net_pct_verified": -0.10660288029324962
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 8,
    "shift_weeks": [
      6
    ],
    "n": 174,
    "new_mean_net_pct": -0.16726034288856573,
    "old_mean_net_pct_verified": -0.2472550240922689
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 9,
    "shift_weeks": [
      18
    ],
    "n": 174,
    "new_mean_net_pct": -0.15816467066460055,
    "old_mean_net_pct_verified": -0.23817794470845505
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 10,
    "shift_weeks": [
      11
    ],
    "n": 174,
    "new_mean_net_pct": -0.12621475081803324,
    "old_mean_net_pct_verified": -0.20621373380673466
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 11,
    "shift_weeks": [
      3
    ],
    "n": 174,
    "new_mean_net_pct": -0.08638563880491061,
    "old_mean_net_pct_verified": -0.1663864292197605
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 12,
    "shift_weeks": [
      5
    ],
    "n": 174,
    "new_mean_net_pct": -0.07409268256599354,
    "old_mean_net_pct_verified": -0.15409451601427762
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 13,
    "shift_weeks": [
      19
    ],
    "n": 174,
    "new_mean_net_pct": -0.026606482287077845,
    "old_mean_net_pct_verified": -0.10660288029324962
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 14,
    "shift_weeks": [
      12
    ],
    "n": 174,
    "new_mean_net_pct": -0.10927632259852858,
    "old_mean_net_pct_verified": -0.18927921259945477
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 15,
    "shift_weeks": [
      16
    ],
    "n": 174,
    "new_mean_net_pct": -0.15267724272716918,
    "old_mean_net_pct_verified": -0.23270614701693687
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 16,
    "shift_weeks": [
      6
    ],
    "n": 174,
    "new_mean_net_pct": -0.16726034288856573,
    "old_mean_net_pct_verified": -0.2472550240922689
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 17,
    "shift_weeks": [
      3
    ],
    "n": 174,
    "new_mean_net_pct": -0.08638563880491061,
    "old_mean_net_pct_verified": -0.1663864292197605
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 18,
    "shift_weeks": [
      17
    ],
    "n": 174,
    "new_mean_net_pct": -0.07278150766794564,
    "old_mean_net_pct_verified": -0.15277136776021685
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 19,
    "shift_weeks": [
      14
    ],
    "n": 174,
    "new_mean_net_pct": -0.03125784895225487,
    "old_mean_net_pct_verified": -0.11123462955711318
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 20,
    "shift_weeks": [
      18
    ],
    "n": 174,
    "new_mean_net_pct": -0.15816467066460055,
    "old_mean_net_pct_verified": -0.23817794470845505
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 21,
    "shift_weeks": [
      18
    ],
    "n": 174,
    "new_mean_net_pct": -0.15816467066460055,
    "old_mean_net_pct_verified": -0.23817794470845505
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 22,
    "shift_weeks": [
      4
    ],
    "n": 174,
    "new_mean_net_pct": -0.11092701067503756,
    "old_mean_net_pct_verified": -0.190905647448393
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 23,
    "shift_weeks": [
      5
    ],
    "n": 174,
    "new_mean_net_pct": -0.07409268256599354,
    "old_mean_net_pct_verified": -0.15409451601427762
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 24,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 25,
    "shift_weeks": [
      2
    ],
    "n": 174,
    "new_mean_net_pct": -0.16605585289153313,
    "old_mean_net_pct_verified": -0.24603814589984493
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 26,
    "shift_weeks": [
      18
    ],
    "n": 174,
    "new_mean_net_pct": -0.15816467066460055,
    "old_mean_net_pct_verified": -0.23817794470845505
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 27,
    "shift_weeks": [
      10
    ],
    "n": 173,
    "new_mean_net_pct": -0.0772821071611266,
    "old_mean_net_pct_verified": -0.1572736885336226
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 28,
    "shift_weeks": [
      16
    ],
    "n": 174,
    "new_mean_net_pct": -0.15267724272716918,
    "old_mean_net_pct_verified": -0.23270614701693687
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 29,
    "shift_weeks": [
      4
    ],
    "n": 174,
    "new_mean_net_pct": -0.11092701067503756,
    "old_mean_net_pct_verified": -0.190905647448393
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 30,
    "shift_weeks": [
      12
    ],
    "n": 174,
    "new_mean_net_pct": -0.10927632259852858,
    "old_mean_net_pct_verified": -0.18927921259945477
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 31,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 32,
    "shift_weeks": [
      19
    ],
    "n": 174,
    "new_mean_net_pct": -0.026606482287077845,
    "old_mean_net_pct_verified": -0.10660288029324962
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 33,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 34,
    "shift_weeks": [
      2
    ],
    "n": 174,
    "new_mean_net_pct": -0.16605585289153313,
    "old_mean_net_pct_verified": -0.24603814589984493
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 35,
    "shift_weeks": [
      16
    ],
    "n": 174,
    "new_mean_net_pct": -0.15267724272716918,
    "old_mean_net_pct_verified": -0.23270614701693687
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 36,
    "shift_weeks": [
      18
    ],
    "n": 174,
    "new_mean_net_pct": -0.15816467066460055,
    "old_mean_net_pct_verified": -0.23817794470845505
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 37,
    "shift_weeks": [
      13
    ],
    "n": 174,
    "new_mean_net_pct": -0.15548151539736083,
    "old_mean_net_pct_verified": -0.23547053454608027
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 38,
    "shift_weeks": [
      12
    ],
    "n": 174,
    "new_mean_net_pct": -0.10927632259852858,
    "old_mean_net_pct_verified": -0.18927921259945477
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 39,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 40,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 41,
    "shift_weeks": [
      4
    ],
    "n": 174,
    "new_mean_net_pct": -0.11092701067503756,
    "old_mean_net_pct_verified": -0.190905647448393
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 42,
    "shift_weeks": [
      11
    ],
    "n": 174,
    "new_mean_net_pct": -0.12621475081803324,
    "old_mean_net_pct_verified": -0.20621373380673466
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 43,
    "shift_weeks": [
      10
    ],
    "n": 173,
    "new_mean_net_pct": -0.0772821071611266,
    "old_mean_net_pct_verified": -0.1572736885336226
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 44,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 45,
    "shift_weeks": [
      12
    ],
    "n": 174,
    "new_mean_net_pct": -0.10927632259852858,
    "old_mean_net_pct_verified": -0.18927921259945477
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 46,
    "shift_weeks": [
      6
    ],
    "n": 174,
    "new_mean_net_pct": -0.16726034288856573,
    "old_mean_net_pct_verified": -0.2472550240922689
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 47,
    "shift_weeks": [
      8
    ],
    "n": 174,
    "new_mean_net_pct": -0.0229264522344753,
    "old_mean_net_pct_verified": -0.10294675185710025
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 48,
    "shift_weeks": [
      12
    ],
    "n": 174,
    "new_mean_net_pct": -0.10927632259852858,
    "old_mean_net_pct_verified": -0.18927921259945477
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 49,
    "shift_weeks": [
      16
    ],
    "n": 174,
    "new_mean_net_pct": -0.15267724272716918,
    "old_mean_net_pct_verified": -0.23270614701693687
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 50,
    "shift_weeks": [
      13
    ],
    "n": 174,
    "new_mean_net_pct": -0.15548151539736083,
    "old_mean_net_pct_verified": -0.23547053454608027
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 51,
    "shift_weeks": [
      14
    ],
    "n": 174,
    "new_mean_net_pct": -0.03125784895225487,
    "old_mean_net_pct_verified": -0.11123462955711318
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 52,
    "shift_weeks": [
      16
    ],
    "n": 174,
    "new_mean_net_pct": -0.15267724272716918,
    "old_mean_net_pct_verified": -0.23270614701693687
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 53,
    "shift_weeks": [
      3
    ],
    "n": 174,
    "new_mean_net_pct": -0.08638563880491061,
    "old_mean_net_pct_verified": -0.1663864292197605
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 54,
    "shift_weeks": [
      17
    ],
    "n": 174,
    "new_mean_net_pct": -0.07278150766794564,
    "old_mean_net_pct_verified": -0.15277136776021685
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 55,
    "shift_weeks": [
      12
    ],
    "n": 174,
    "new_mean_net_pct": -0.10927632259852858,
    "old_mean_net_pct_verified": -0.18927921259945477
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 56,
    "shift_weeks": [
      17
    ],
    "n": 174,
    "new_mean_net_pct": -0.07278150766794564,
    "old_mean_net_pct_verified": -0.15277136776021685
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 57,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 58,
    "shift_weeks": [
      17
    ],
    "n": 174,
    "new_mean_net_pct": -0.07278150766794564,
    "old_mean_net_pct_verified": -0.15277136776021685
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 59,
    "shift_weeks": [
      6
    ],
    "n": 174,
    "new_mean_net_pct": -0.16726034288856573,
    "old_mean_net_pct_verified": -0.2472550240922689
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 60,
    "shift_weeks": [
      17
    ],
    "n": 174,
    "new_mean_net_pct": -0.07278150766794564,
    "old_mean_net_pct_verified": -0.15277136776021685
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 61,
    "shift_weeks": [
      2
    ],
    "n": 174,
    "new_mean_net_pct": -0.16605585289153313,
    "old_mean_net_pct_verified": -0.24603814589984493
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 62,
    "shift_weeks": [
      7
    ],
    "n": 174,
    "new_mean_net_pct": -0.01708071136883372,
    "old_mean_net_pct_verified": -0.09706520322423043
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 63,
    "shift_weeks": [
      17
    ],
    "n": 174,
    "new_mean_net_pct": -0.07278150766794564,
    "old_mean_net_pct_verified": -0.15277136776021685
  },
  {
    "name": "ETHUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 64,
    "shift_weeks": [
      10
    ],
    "n": 173,
    "new_mean_net_pct": -0.0772821071611266,
    "old_mean_net_pct_verified": -0.1572736885336226
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 1,
    "shift_weeks": [
      15
    ],
    "n": 154,
    "new_mean_net_pct": -0.03840474929370912,
    "old_mean_net_pct_verified": -0.11841360882668076
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 2,
    "shift_weeks": [
      16
    ],
    "n": 154,
    "new_mean_net_pct": -0.0929389303669159,
    "old_mean_net_pct_verified": -0.17295587333624785
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 3,
    "shift_weeks": [
      8
    ],
    "n": 153,
    "new_mean_net_pct": -0.09615025994401931,
    "old_mean_net_pct_verified": -0.1761454404385842
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 4,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 5,
    "shift_weeks": [
      11
    ],
    "n": 154,
    "new_mean_net_pct": -0.1972879467849003,
    "old_mean_net_pct_verified": -0.2772694928357395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 6,
    "shift_weeks": [
      19
    ],
    "n": 154,
    "new_mean_net_pct": -0.04431740089219595,
    "old_mean_net_pct_verified": -0.12431333260717044
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 7,
    "shift_weeks": [
      19
    ],
    "n": 154,
    "new_mean_net_pct": -0.04431740089219595,
    "old_mean_net_pct_verified": -0.12431333260717044
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 8,
    "shift_weeks": [
      6
    ],
    "n": 154,
    "new_mean_net_pct": -0.2007004393869375,
    "old_mean_net_pct_verified": -0.28070620398870905
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 9,
    "shift_weeks": [
      18
    ],
    "n": 154,
    "new_mean_net_pct": -0.027766772168312297,
    "old_mean_net_pct_verified": -0.10775467520096395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 10,
    "shift_weeks": [
      11
    ],
    "n": 154,
    "new_mean_net_pct": -0.1972879467849003,
    "old_mean_net_pct_verified": -0.2772694928357395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 11,
    "shift_weeks": [
      3
    ],
    "n": 154,
    "new_mean_net_pct": -0.053431211006514025,
    "old_mean_net_pct_verified": -0.13341550676219674
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 12,
    "shift_weeks": [
      5
    ],
    "n": 154,
    "new_mean_net_pct": -0.10104864887708254,
    "old_mean_net_pct_verified": -0.18101961687925658
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 13,
    "shift_weeks": [
      19
    ],
    "n": 154,
    "new_mean_net_pct": -0.04431740089219595,
    "old_mean_net_pct_verified": -0.12431333260717044
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 14,
    "shift_weeks": [
      12
    ],
    "n": 154,
    "new_mean_net_pct": -0.03464240577881868,
    "old_mean_net_pct_verified": -0.11466340894065351
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 15,
    "shift_weeks": [
      16
    ],
    "n": 154,
    "new_mean_net_pct": -0.0929389303669159,
    "old_mean_net_pct_verified": -0.17295587333624785
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 16,
    "shift_weeks": [
      6
    ],
    "n": 154,
    "new_mean_net_pct": -0.2007004393869375,
    "old_mean_net_pct_verified": -0.28070620398870905
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 17,
    "shift_weeks": [
      3
    ],
    "n": 154,
    "new_mean_net_pct": -0.053431211006514025,
    "old_mean_net_pct_verified": -0.13341550676219674
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 18,
    "shift_weeks": [
      17
    ],
    "n": 154,
    "new_mean_net_pct": -0.017559993438438816,
    "old_mean_net_pct_verified": -0.09758522172702609
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 19,
    "shift_weeks": [
      14
    ],
    "n": 154,
    "new_mean_net_pct": -0.15222196997151358,
    "old_mean_net_pct_verified": -0.2321970681077036
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 20,
    "shift_weeks": [
      18
    ],
    "n": 154,
    "new_mean_net_pct": -0.027766772168312297,
    "old_mean_net_pct_verified": -0.10775467520096395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 21,
    "shift_weeks": [
      18
    ],
    "n": 154,
    "new_mean_net_pct": -0.027766772168312297,
    "old_mean_net_pct_verified": -0.10775467520096395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 22,
    "shift_weeks": [
      4
    ],
    "n": 154,
    "new_mean_net_pct": -0.10491901618078242,
    "old_mean_net_pct_verified": -0.18490073555823822
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 23,
    "shift_weeks": [
      5
    ],
    "n": 154,
    "new_mean_net_pct": -0.10104864887708254,
    "old_mean_net_pct_verified": -0.18101961687925658
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 24,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 25,
    "shift_weeks": [
      2
    ],
    "n": 154,
    "new_mean_net_pct": -0.003291332803847377,
    "old_mean_net_pct_verified": -0.08327968431575232
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 26,
    "shift_weeks": [
      18
    ],
    "n": 154,
    "new_mean_net_pct": -0.027766772168312297,
    "old_mean_net_pct_verified": -0.10775467520096395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 27,
    "shift_weeks": [
      10
    ],
    "n": 153,
    "new_mean_net_pct": -0.1375498507346272,
    "old_mean_net_pct_verified": -0.21755052524884108
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 28,
    "shift_weeks": [
      16
    ],
    "n": 154,
    "new_mean_net_pct": -0.0929389303669159,
    "old_mean_net_pct_verified": -0.17295587333624785
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 29,
    "shift_weeks": [
      4
    ],
    "n": 154,
    "new_mean_net_pct": -0.10491901618078242,
    "old_mean_net_pct_verified": -0.18490073555823822
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 30,
    "shift_weeks": [
      12
    ],
    "n": 154,
    "new_mean_net_pct": -0.03464240577881868,
    "old_mean_net_pct_verified": -0.11466340894065351
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 31,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 32,
    "shift_weeks": [
      19
    ],
    "n": 154,
    "new_mean_net_pct": -0.04431740089219595,
    "old_mean_net_pct_verified": -0.12431333260717044
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 33,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 34,
    "shift_weeks": [
      2
    ],
    "n": 154,
    "new_mean_net_pct": -0.003291332803847377,
    "old_mean_net_pct_verified": -0.08327968431575232
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 35,
    "shift_weeks": [
      16
    ],
    "n": 154,
    "new_mean_net_pct": -0.0929389303669159,
    "old_mean_net_pct_verified": -0.17295587333624785
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 36,
    "shift_weeks": [
      18
    ],
    "n": 154,
    "new_mean_net_pct": -0.027766772168312297,
    "old_mean_net_pct_verified": -0.10775467520096395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 37,
    "shift_weeks": [
      13
    ],
    "n": 154,
    "new_mean_net_pct": -0.020682663177824724,
    "old_mean_net_pct_verified": -0.1006528957355546
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 38,
    "shift_weeks": [
      12
    ],
    "n": 154,
    "new_mean_net_pct": -0.03464240577881868,
    "old_mean_net_pct_verified": -0.11466340894065351
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 39,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 40,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 41,
    "shift_weeks": [
      4
    ],
    "n": 154,
    "new_mean_net_pct": -0.10491901618078242,
    "old_mean_net_pct_verified": -0.18490073555823822
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 42,
    "shift_weeks": [
      11
    ],
    "n": 154,
    "new_mean_net_pct": -0.1972879467849003,
    "old_mean_net_pct_verified": -0.2772694928357395
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 43,
    "shift_weeks": [
      10
    ],
    "n": 153,
    "new_mean_net_pct": -0.1375498507346272,
    "old_mean_net_pct_verified": -0.21755052524884108
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 44,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 45,
    "shift_weeks": [
      12
    ],
    "n": 154,
    "new_mean_net_pct": -0.03464240577881868,
    "old_mean_net_pct_verified": -0.11466340894065351
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 46,
    "shift_weeks": [
      6
    ],
    "n": 154,
    "new_mean_net_pct": -0.2007004393869375,
    "old_mean_net_pct_verified": -0.28070620398870905
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 47,
    "shift_weeks": [
      8
    ],
    "n": 153,
    "new_mean_net_pct": -0.09615025994401931,
    "old_mean_net_pct_verified": -0.1761454404385842
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 48,
    "shift_weeks": [
      12
    ],
    "n": 154,
    "new_mean_net_pct": -0.03464240577881868,
    "old_mean_net_pct_verified": -0.11466340894065351
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 49,
    "shift_weeks": [
      16
    ],
    "n": 154,
    "new_mean_net_pct": -0.0929389303669159,
    "old_mean_net_pct_verified": -0.17295587333624785
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 50,
    "shift_weeks": [
      13
    ],
    "n": 154,
    "new_mean_net_pct": -0.020682663177824724,
    "old_mean_net_pct_verified": -0.1006528957355546
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 51,
    "shift_weeks": [
      14
    ],
    "n": 154,
    "new_mean_net_pct": -0.15222196997151358,
    "old_mean_net_pct_verified": -0.2321970681077036
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 52,
    "shift_weeks": [
      16
    ],
    "n": 154,
    "new_mean_net_pct": -0.0929389303669159,
    "old_mean_net_pct_verified": -0.17295587333624785
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 53,
    "shift_weeks": [
      3
    ],
    "n": 154,
    "new_mean_net_pct": -0.053431211006514025,
    "old_mean_net_pct_verified": -0.13341550676219674
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 54,
    "shift_weeks": [
      17
    ],
    "n": 154,
    "new_mean_net_pct": -0.017559993438438816,
    "old_mean_net_pct_verified": -0.09758522172702609
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 55,
    "shift_weeks": [
      12
    ],
    "n": 154,
    "new_mean_net_pct": -0.03464240577881868,
    "old_mean_net_pct_verified": -0.11466340894065351
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 56,
    "shift_weeks": [
      17
    ],
    "n": 154,
    "new_mean_net_pct": -0.017559993438438816,
    "old_mean_net_pct_verified": -0.09758522172702609
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 57,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 58,
    "shift_weeks": [
      17
    ],
    "n": 154,
    "new_mean_net_pct": -0.017559993438438816,
    "old_mean_net_pct_verified": -0.09758522172702609
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 59,
    "shift_weeks": [
      6
    ],
    "n": 154,
    "new_mean_net_pct": -0.2007004393869375,
    "old_mean_net_pct_verified": -0.28070620398870905
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 60,
    "shift_weeks": [
      17
    ],
    "n": 154,
    "new_mean_net_pct": -0.017559993438438816,
    "old_mean_net_pct_verified": -0.09758522172702609
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 61,
    "shift_weeks": [
      2
    ],
    "n": 154,
    "new_mean_net_pct": -0.003291332803847377,
    "old_mean_net_pct_verified": -0.08327968431575232
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 62,
    "shift_weeks": [
      7
    ],
    "n": 154,
    "new_mean_net_pct": -0.025478305173672097,
    "old_mean_net_pct_verified": -0.10546522634961986
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 63,
    "shift_weeks": [
      17
    ],
    "n": 154,
    "new_mean_net_pct": -0.017559993438438816,
    "old_mean_net_pct_verified": -0.09758522172702609
  },
  {
    "name": "XRPUSDT_intraday_impulse_follow_z2.5_h120",
    "draw": 64,
    "shift_weeks": [
      10
    ],
    "n": 153,
    "new_mean_net_pct": -0.1375498507346272,
    "old_mean_net_pct_verified": -0.21755052524884108
  }
]
```

</details>
