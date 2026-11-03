# Парный тест флета с исправленным maker на гэпах

Поручение пользователя: сравнить продолжение сетки, отмену доборов и отмену с закрытием остатка при 2%. Общие входы, одинаковые расходы и общий горизонт. Отдельно свежий период. Проверка офлайн.

В свежем периоде, на основном 14-дневном горизонте, чистый итог и H1-просадка составили **-457,26 / 765,30** при продолжении, **126,18 / 407,75** при отмене доборов и **107,88 / 407,75** при немедленном закрытии. Отмена изменила итог относительно продолжения на 583,44 USDT. Закрытие остатка дополнительно изменило итог относительно одной отмены на -18,30 USDT. Это различие политик на одинаковых эпизодах, с тем же состоянием до первой реакции.

## Исполнение и входы

Исправление в отдельном `kernel.py`. Модель хранит один действительно стоящий входной лимит на сторону. При гэпе может заполниться этот лимит, если цена прошла за него на 1 б.п. Новый пересекающий цену лимит отклоняется как post-only. Его можно выставить после возврата к пассивной цене и заполнить на последующем пересечении. На непрерывном сегменте внутриминутного пути каждый новый лимит сначала выставляется, потом пересекается. Это решает дефект синтетического гэпа 100 → 90 → 91, где старое ядро засчитывало новые maker-доборы выше 91. Цена старого пассивного лимита при гэпе используется консервативно, без предполагаемого улучшения цены. [Публичное описание post-only Bybit](https://bybit-exchange.github.io/docs/v5/order/create-order).

Пять регрессионных проверок проходят: зеркальные гэпы LONG/SHORT, возврат к пассивной цене и последующее пересечение, проход на 1 б.п., совпадение состояния до реакции с начислением funding до выхода, сохранение отметки до гэпа на границе. Для каждого исторического эпизода также проверено точное совпадение кривой до триггера и состояния на нём между ветками. На основном свежем прогоне продолжения зарегистрировано 0 maker-входов ранее стоявших заявок через гэп и 145 отклонений пересекающих цену лимитов. Это счётчики исправленной модели, а не пересчёт разницы к старому движку.

Использованы непрерывные минутки Binance BTCUSDT USD-M с 2024-02-01 00:00:00+00:00 до 03.11.2026 00:00 UTC без конечной минуты. 1,448,640 минут и 3,018 расчётов funding, пропусков нет. Funding по ставке × mark из записи расчёта, время округлено к минуте, максимальное исходное отклонение 26 мс. Для прогрева EMA использованы более ранние H1 того же инструмента. У Claude цены Binance spot, поэтому сравнение относится к эффекту действия внутри этой модели, а не к воспроизведению его денежных сумм или всего 2018–2026. [Публичные свечи Binance](https://github.com/binance/binance-public-data). [История funding Binance](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#funding-rate-history-market-data).

Обе стороны стартуют одновременно на закрытии H4 при |наклоне EMA200 за 24 часа| ≤0,4% и |close/EMA200−1| ≤2%. Шаг 0,6%, цель 1,4%, ордер 100 USDT и до 3000 USDT входного номинала на сторону. После первого adverse-пробоя для LONG `close < 0,98 × EMA200`, для SHORT `close > 1,02 × EMA200`, по открытию минуты на границе H4 сначала начисляется funding, затем применяется действие. При одной отмене TP продолжают работать. Горизонт общий, 14 дней от включения, следующий старт после него. Нет отбора эпизодов по будущему пробою. На горизонте остаток обеих сторон ликвидируется с расходами. Новые входы после раннего выхода запрещены до общего горизонта. Это парный тест реакции, а не полная стратегия с динамическим перезапуском.

## Основные результаты

| Окно | Политика | Пар эпизодов | Net | DD H1 | DD M1 | Комиссии | Funding | Входных fill |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Общий с 01.04.24 | Продолжить | 44 | -350,11 | 821,55 | 841,28 | 168,70 | 25,74 | 4284 |
| Общий с 01.04.24 | Отменить доборы, оставить TP | 44 | 35,11 | 451,12 | 467,20 | 77,43 | 4,57 | 2027 |
| Общий с 01.04.24 | Отменить доборы и закрыть остаток | 44 | 108,75 | 407,75 | 425,50 | 85,01 | -2,51 | 2027 |
| Свежий с 01.08.24 | Продолжить | 38 | -457,26 | 765,30 | 785,74 | 140,40 | 23,48 | 3552 |
| Свежий с 01.08.24 | Отменить доборы, оставить TP | 38 | 126,18 | 407,75 | 425,50 | 65,65 | 3,68 | 1724 |
| Свежий с 01.08.24 | Отменить доборы и закрыть остаток | 38 | 107,88 | 407,75 | 425,50 | 72,28 | -1,50 | 1724 |

Суммы в USDT. Funding со знаком. Комиссии включены в net, как и 0,02% slip каждого рыночного выхода. DD от нуля по синхронной кривой двух сторон с плавающим остатком, отдельная отметка ликвидации на каждой границе. DD H1 и M1 различаются частотой отметок. Нет моделирования очереди, реальных bid/ask, маржи и округления лотов. В свежем периоде 57 боковых триггеров, из них 57 с открытым инвентарём. У незатронутых сторон поведение одинаково.

| Окно | Сравнение | Δnet | Лучше | Хуже | Одинаково |
| --- | --- | --- | --- | --- | --- |
| Общий с 01.04.24 | Отменить доборы, оставить TP против Продолжить | 385,22 | 16 | 28 | 0 |
| Общий с 01.04.24 | Отменить доборы и закрыть остаток против Продолжить | 458,86 | 12 | 32 | 0 |
| Общий с 01.04.24 | Отменить доборы и закрыть остаток против Отменить доборы, оставить TP | 73,64 | 21 | 23 | 0 |
| Свежий с 01.08.24 | Отменить доборы, оставить TP против Продолжить | 583,44 | 14 | 24 | 0 |
| Свежий с 01.08.24 | Отменить доборы и закрыть остаток против Продолжить | 565,14 | 10 | 28 | 0 |
| Свежий с 01.08.24 | Отменить доборы и закрыть остаток против Отменить доборы, оставить TP | -18,30 | 17 | 21 | 0 |

Изменения считаются по общим эпизодам с суммой LONG+SHORT. Первая разница выделяет отказ от новых доборов. Вторая дополнительная разница `close − cancel` выделяет закрытие уже накопленной позиции относительно ожидания её TP или общего конца. Число эпизодов без отличий тоже учитывается.

В большинстве пар защитные ветки уступили продолжению. Улучшение итоговой суммы связано с сокращением более крупных потерь. Ниже описательные 95% интервалы суммарного Δnet, 5000 круговых блоковых повторов. LONG и SHORT внутри эпизода остаются вместе. Блок задан в соседних эпизодах, а не в равных календарных отрезках. Все интервалы включают ноль. Они показывают разброс оценки на этих данных и не являются независимым подтверждением эффекта.

| Сравнение в свежем периоде | Блок 3 эпизода | Блок 6 эпизодов |
| --- | --- | --- |
| Отменить доборы, оставить TP против Продолжить | -494,91 … 1 968,66 | -379,12 … 1 718,07 |
| Отменить доборы и закрыть остаток против Продолжить | -696,43 … 2 002,78 | -364,74 … 1 561,79 |
| Отменить доборы и закрыть остаток против Отменить доборы, оставить TP | -582,21 … 605,77 | -544,18 … 539,61 |

Свежий период, чистый итог по сторонам:

| Сторона | Продолжить | Отменить | Закрыть | Закрыть − отменить |
| --- | --- | --- | --- | --- |
| LONG | 529,74 | 198,62 | 1,78 | -196,84 |
| SHORT | -987,00 | -72,45 | 106,10 | 178,54 |

Пример различия в обе стороны. В эпизоде с 15.08.2026 SHORT пересёк порог 19.08 16:00 UTC с 15 лотами. Продолжение дало −360,52, отмена −245,86, закрытие −53,10 USDT по этой стороне. В эпизоде с 19.12.2024 немедленное закрытие двух сторон сократило итог на 86,89 USDT относительно отмены с сохранением TP. Первый случай показывает пользу закрытия при дальнейшем движении против остатка, второй — цену отказа от восстановления. Выбирать действие по стороне по этим же данным означало бы добавить новый фильтр задним числом.

## Чувствительность свежего периода, net / DD H1

| Горизонт, дни | Путь | Продолжить | Отменить | Закрыть |
| --- | --- | --- | --- | --- |
| 14 | color | -457,26 / 765,30 | 126,18 / 407,75 | 107,88 / 407,75 |
| 7 | color | -910,90 / 1 003,61 | -216,82 / 375,05 | 94,54 / 294,74 |
| 28 | color | -542,66 / 1 140,78 | -463,14 / 616,08 | -374,13 / 584,25 |
| 14 | OHLC | -381,60 / 743,38 | 192,26 / 396,80 | 173,96 / 396,80 |
| 14 | OLHC | -343,58 / 754,30 | 215,65 / 407,75 | 189,99 / 407,75 |

`color` — путь по цвету минуты из прежнего подхода. OHLC/OLHC — фиксированные порядки high/low. 7 и 28 дней меняют длительность и расписание эпизодов, поэтому используются для проверки знака сравнений внутри каждой строки. Не являются подбором лучшего горизонта.

Обе защитные ветки во всех пяти свежих сравнениях дали больший net и меньшую H1-DD, чем продолжение сетки. На 14 днях отмена с сохранением TP обошла немедленное закрытие при всех трёх путях; на 7 и 28 днях выиграло закрытие. На 28 днях все три политики остались убыточны. Этот парный тест поддерживает идею ограничить новые доборы после пробоя в рамках модели, а выбор способа закрытия остатка зависит от горизонта. Положительное математическое ожидание для торговли не установлено.

Файлы локально: `research/flat_paired_20261103/PROTOCOL.md`, `data_manifest.json`, `metrics.csv`, `episodes_*.csv`, `equity_*.csv`. Данные SHA256 `7beb0a8bd4ebbe91f43026434690a986fbe151634db7dabae5f663a55e503a51`. Команда воспроизведения из C:/bot7: `python research/flat_paired_20261103/build_data.py`, `python -m unittest discover -s research/flat_paired_20261103 -p test_kernel.py -v`, `python research/flat_paired_20261103/run.py`.

<details><summary>kernel.py</summary>

```python
"""Offline one-sided grid with an explicit resting order and gap handling.

The input path is a bar approximation, not a reconstruction of the book.
Prices are transformed so that a move down is adverse for both sides.
"""

import numpy as np


def run_episode(bars, funding, start, trigger, end, side, policy, *, step=.006,
                target=.014, order_usd=100., cap=3000., maker=.00016,
                taker=.00048, slip=.0002, through=.0001, path='color', journal=False):
    """Replay [start,end); funding is rate times mark per unit at each bar open.

    At trigger, charge funding on carried lots and then apply the policy before
    processing the open. At end, liquidate at the next available open or the
    final close. `equity` contains marks at each bar close, before the separate
    terminal liquidation. `net` includes liquidation costs.
    """
    if policy not in ('continue', 'cancel', 'close'):
        raise ValueError(f'Unknown policy: {policy}')
    if path not in ('color', 'OHLC', 'OLHC'):
        raise ValueError(f'Unknown bar path: {path}')
    if side not in (-1, 1) or not 0 <= start < end <= len(bars) or len(funding) != len(bars):
        raise ValueError('Invalid side, interval, or funding length')
    if trigger is not None and not start <= trigger <= end:
        raise ValueError('Trigger must be within the interval or its final boundary')
    if not 0 <= through < min(step, target) or not 0 < step < 1 or not 0 < target < 1:
        raise ValueError('Require positive step/target and smaller trade-through')

    # Each lot stores actual unsigned entry, quantity and signed take price.
    lots = []
    resting = None
    rejected = None
    anchor = None
    quantity = cost = gross = fees = paid = 0.
    fills = tps = gap_fills = rejects = 0
    max_exposure = 0.
    equity = np.empty(end-start)
    enabled = True
    trigger_state = None
    events = [] if journal else None

    def record(kind, price, **fields):
        if events is not None:
            events.append(dict(index=i, kind=kind, price=price, **fields))

    def quote(point):
        """Submit only a passive order. Rejected orders cannot fill later as resting."""
        nonlocal resting, rejected, rejects, anchor
        if not enabled:
            return
        if lots:
            anchor = min(side*lot[0] for lot in lots)
        else:
            anchor = max(anchor, point) if anchor is not None else point
        level = anchor * (1 - side*step)
        if resting == level:
            return
        resting = None
        if level >= point:
            if rejected != level:
                rejects += 1
                rejected = level
                record('post_only_reject', side*level, market=side*point)
            return
        rejected = None
        if max(cost, quantity*abs(point)) + order_usd <= cap + 1e-9:
            resting = level
            record('resting_entry', side*level, market=side*point)

    def fill(point, gap):
        nonlocal resting, quantity, cost, fees, fills, gap_fills, max_exposure
        px = side * resting
        q = order_usd/px
        lots.append((px, q, side*px*(1+side*target)))
        quantity += q
        cost += order_usd
        fees += order_usd*maker
        fills += 1
        gap_fills += int(gap)
        resting = None
        max_exposure = max(max_exposure, quantity*abs(point))
        record('maker_entry_gap' if gap else 'maker_entry', px, market=side*point, quantity=q)

    def take(point):
        nonlocal lots, quantity, cost, gross, fees, tps
        remain = []
        for entry, q, level in lots:
            if point >= level + abs(level)*through and point > level:
                px = side*level
                gross += side*q*(px-entry)
                fees += q*px*maker
                quantity -= q
                cost -= q*entry
                tps += 1
                record('maker_take', px, market=side*point, quantity=q)
            else:
                remain.append((entry, q, level))
        lots = remain
        if not lots:
            quantity = cost = 0.

    def liquidate(raw, reason):
        nonlocal lots, quantity, cost, gross, fees, resting
        px = raw*(1-side*slip)
        if lots:
            gross += side*(quantity*px-cost)
            fees += quantity*px*taker
            record(reason, px, market=raw, quantity=quantity)
        lots = []
        quantity = cost = 0.
        resting = None

    def snapshot(raw):
        return dict(lots=len(lots), quantity=quantity, entry_notional=cost,
                    exposure=quantity*raw, gross=gross, fees=fees, funding=paid,
                    fills=fills, tps=tps, gap_maker_fills=gap_fills,
                    post_only_rejections=rejects,
                    resting_entry=side*resting if resting is not None else None)

    def traverse(a, b):
        """Only orders already resting at a crossing can execute."""
        if b > a:
            if lots:
                take(b)
            quote(b)
        elif b < a:
            while resting is not None:
                threshold = resting-abs(resting)*through
                if b > threshold or b >= resting or a < threshold:
                    break
                fill(threshold, False)
                quote(threshold)
                a = threshold

    for i in range(start, end):
        o,h,l,c = bars[i]
        if quantity:
            paid -= side*quantity*funding[i]
            max_exposure = max(max_exposure, quantity*o)
        if trigger == i:
            trigger_state = snapshot(o)
            if policy != 'continue':
                enabled = False
                resting = None
                record('cancel_entry', o)
            if policy == 'close':
                liquidate(o, 'trigger_exit')
                equity[i-start:] = gross-fees+paid
                break

        opening = side*o
        # Opening gap is one event. Even if multiple hypothetical grid levels
        # lie above the new market, only the already resting entry can fill.
        if lots:
            take(opening)
        if resting is not None and opening < resting and opening <= resting-abs(resting)*through:
            fill(opening, True)
        quote(opening)

        high_first = path == 'OHLC' or (path == 'color' and c < o)
        a,b = (h,l) if high_first else (l,h)
        traverse(opening, side*a)
        traverse(side*a, side*b)
        traverse(side*b, side*c)
        max_exposure = max(max_exposure, quantity*c)
        equity[i-start] = gross-fees+paid+side*(quantity*c-cost)
    else:
        i = end
        raw = bars[end][0] if end<len(bars) else bars[end-1][3]
        if end<len(bars) and quantity:
            paid -= side*quantity*funding[end]
            max_exposure = max(max_exposure, quantity*raw)
        if trigger == end:
            trigger_state = snapshot(raw)
        liquidate(raw, 'terminal_exit')

    net = gross-fees+paid
    marks = np.r_[0., equity, net]
    dd = float(np.max(np.maximum.accumulate(marks)-marks))
    return dict(net=net, gross=gross, fees=fees, funding=paid, fills=fills,
                tps=tps, gap_maker_fills=gap_fills, post_only_rejections=rejects,
                trigger_state=trigger_state, max_exposure=max_exposure, dd=dd,
                equity=equity, journal=events)

```
</details>

<details><summary>run.py</summary>

```python
"""Paired offline grid test. Fixed entry schedule and episode clocks."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from kernel import run_episode

P = Path(__file__).resolve().parent
POLICIES = ('continue', 'cancel', 'close')


def schedule(index, signals, start, horizon):
    first = pd.Timestamp(start,tz='UTC')
    end = index[-1]+pd.Timedelta(minutes=1)
    available = first
    for time, row in signals.loc[(signals.index>=first)&(signals.index<end)].iterrows():
        if time<available or not row.arm:
            continue
        stop = min(time+pd.Timedelta(days=horizon),end)
        block = signals.loc[(signals.index>time)&(signals.index<stop)]
        def first_trigger(mask):
            selected=block.index[mask]
            return int(index.searchsorted(selected[0])) if len(selected) else None
        yield (int(index.searchsorted(time)),int(index.searchsorted(stop)),
               {1:first_trigger(block.long_cut),-1:first_trigger(block.short_cut)})
        available = stop


def drawdown(curve):
    marks=np.r_[0.,curve]
    dd=np.maximum.accumulate(marks)-marks
    return float(dd.max()),int(dd.argmax())


def scenario(index, bars, funding, signals, start, horizon, path):
    curves={key:np.zeros(len(index)+1) for key in POLICIES}
    episodes=[]
    for no,(a,b,triggers) in enumerate(schedule(index,signals,start,horizon),1):
        for side,trigger in triggers.items():
            base=run_episode(bars,funding,a,trigger,b,side,'continue',path=path)
            for key in POLICIES:
                r=base if key=='continue' or trigger is None else run_episode(bars,funding,a,trigger,b,side,key,path=path)
                assert r['trigger_state']==base['trigger_state']
                prefix=(trigger-a) if trigger is not None else b-a
                np.testing.assert_array_equal(r['equity'][:prefix],base['equity'][:prefix])
                assert abs(r['net']-(r['gross']-r['fees']+r['funding']))<1e-8
                curves[key][a:b]+=r['equity']
                # Realized PnL persists after the episode. A sparse carry vector
                # is integrated below, avoiding a linear update for every episode.
                s=r['trigger_state'] or {}
                episodes.append(dict(episode=no,side=side,policy=key,start=str(index[a]),
                    end=str(index[0]+pd.Timedelta(minutes=b)),end_index=b,
                    trigger=str(index[trigger]) if trigger is not None else '',
                    trigger_lots=s.get('lots',0),trigger_exposure=s.get('exposure',0.),
                    **{k:r[k] for k in ['net','gross','fees','funding','fills','tps','gap_maker_fills','post_only_rejections','max_exposure']}))
    table=pd.DataFrame(episodes)
    assert len(table)>0
    hourly=(index+pd.Timedelta(minutes=1)).minute==0
    close_points=np.flatnonzero(hourly)+1
    metrics=[]
    out_curves={}
    for key,curve in curves.items():
        rows=table[table.policy==key]
        carry=np.zeros(len(curve))
        np.add.at(carry,rows.end_index.to_numpy(),rows.net.to_numpy())
        realized=np.cumsum(carry)
        curve+=realized
        assert abs(curve[-1]-rows.net.sum())<1e-8
        ends=np.unique(rows.end_index.to_numpy())
        # Include the execution mark after the previous minute close, before
        # any next episode's first close, even at the same clock timestamp.
        marks=np.insert(curve[:-1],ends,realized[ends])
        mark_points=np.insert(np.arange(1,len(index)+1),ends,ends)
        where=np.searchsorted(close_points,ends,side='right')
        hh=np.insert(curve[:-1][hourly],where,realized[ends])
        hour_points=np.insert(close_points,where,ends)
        md,loc=drawdown(marks)
        hd,_=drawdown(hh)
        metrics.append(dict(start=start,horizon=horizon,path=path,policy=key,net=float(curve[-1]),
            dd_minute=md,dd_hour=hd,dd_minute_time=str(index[0]+pd.Timedelta(minutes=int(mark_points[loc-1]) if loc else 0)),
            episodes=int(rows.episode.nunique()),sides=len(rows),triggered=int((rows.trigger!='').sum()),
            triggered_inventory=int((rows.trigger_lots>0).sum()),
            **{k:float(rows[k].sum()) for k in ['gross','fees','funding','fills','tps','gap_maker_fills','post_only_rejections']}))
        out_curves[key]=hh
    return metrics,table,pd.DataFrame(out_curves,index=index[0]+pd.to_timedelta(hour_points,unit='min'))


def main():
    d=pd.read_parquet(P/'bars.parquet').sort_index()
    assert d.index.equals(pd.date_range(d.index[0],d.index[-1],freq='1min'))
    assert d[['open','high','low','close','funding']].notna().all().all()
    h4=d.close.resample('4h').agg(['last','count']).query('count==240')['last']
    warmup=P.parent/'expectancy_20261006'/'public_data'/'binance_futures_BTCUSDT_1h.csv'
    old=pd.read_csv(warmup,usecols=['ts','close'])
    old.index=pd.to_datetime(old.pop('ts'),unit='ms',utc=True)
    prefix=old.loc[old.index<h4.index[0],'close'].resample('4h').agg(['last','count']).query('count==4')['last']
    h4=pd.concat([prefix,h4])
    assert h4.index.equals(pd.date_range(h4.index[0],h4.index[-1],freq='4h'))
    h4.index+=pd.Timedelta(hours=4)
    ema=h4.ewm(span=200,adjust=False).mean()
    gap=h4/ema-1
    signals=pd.DataFrame(dict(arm=(ema.pct_change(6).abs()<=.004)&(gap.abs()<=.02),long_cut=gap<-.02,short_cut=gap>.02))
    b=d[['open','high','low','close']].to_numpy()
    funding=d.funding.to_numpy()
    all_rows=[]
    for start,horizon,path in [('2024-04-01',14,'color'),('2024-08-01',14,'color'),
                                ('2024-08-01',7,'color'),('2024-08-01',28,'color'),
                                ('2024-08-01',14,'OHLC'),('2024-08-01',14,'OLHC')]:
        metrics,episodes,equity=scenario(d.index,b,funding,signals,start,horizon,path)
        all_rows+=metrics
        label=f'{start}_{horizon}_{path}'
        episodes.to_csv(P/f'episodes_{label}.csv',index=False)
        equity.to_csv(P/f'equity_{label}.csv')
        print(label,[(x['policy'],round(x['net'],2),round(x['dd_hour'],2)) for x in metrics],flush=True)
        pd.DataFrame(all_rows).to_csv(P/'metrics.csv',index=False)
    (P/'coverage.json').write_text(json.dumps(dict(first=str(d.index[0]),end_exclusive=str(d.index[-1]+pd.Timedelta(minutes=1)),minutes=len(d))))


if __name__=='__main__':
    main()

```
</details>

<details><summary>build_data.py</summary>

```python
"""Assemble public Binance USD-M prices and funding for the paired flat study."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import urlopen
import zipfile

import numpy as np
import pandas as pd


P = Path(__file__).resolve().parent
ROOT = P.parents[1]
CACHE = ROOT / 'research/expectancy_20261006/public_data'
RAW = P / 'public_prices'
RAW.mkdir(exist_ok=True)
SYMBOL = 'BTCUSDT'
FIRST = pd.Timestamp('2024-02-01', tz='UTC')
CACHE_START = pd.Timestamp('2026-05-07', tz='UTC')
TAIL = pd.Timestamp('2026-10-06', tz='UTC')
END = pd.Timestamp('2026-11-03', tz='UTC')
COLS = ['ts', 'open', 'high', 'low', 'close']


def stamp(t):
    return int(t.timestamp() * 1000)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def retrieve(url, path):
    if path.is_file():
        return path.read_bytes()
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as reply:
                raw = reply.read()
            path.write_bytes(raw)
            return raw
        except HTTPError as error:
            if error.code == 404 or attempt == 2:
                raise
            time.sleep(attempt + 1)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def price_archive(task):
    scope, date, start, end = task
    name = f'{SYMBOL}-1m-{date}.zip'
    url = f'https://data.binance.vision/data/futures/um/{scope}/klines/{SYMBOL}/1m/{name}'
    try:
        raw = retrieve(url, RAW/name)
    except HTTPError as error:
        if error.code != 404 or scope != 'daily':
            raise
        name = f'{SYMBOL}-1m-{date}.json'
        url = 'https://fapi.binance.com/fapi/v1/klines?' + urlencode(dict(
            symbol=SYMBOL, interval='1m', startTime=stamp(start), endTime=stamp(end)-1, limit=1500))
        raw = retrieve(url, RAW/name)
        frame = pd.DataFrame([row[:5] for row in json.loads(raw)], columns=COLS)
        frame[COLS[1:]] = frame[COLS[1:]].astype(float)
    else:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            csv = archive.read(archive.namelist()[0])
        header = 0 if csv.split(b',', 1)[0].isdigit() else 1
        frame = pd.read_csv(io.BytesIO(csv), skiprows=header, header=None, usecols=list(range(5)), names=COLS)
    expected = np.arange(stamp(start), stamp(end), 60000, dtype=np.int64)
    actual = frame.ts.to_numpy(dtype=np.int64)
    if not np.array_equal(actual, expected):
        raise RuntimeError(f'{name} minute coverage differs: {len(actual)} vs {len(expected)}; first {actual[0]}, last {actual[-1]}')
    return frame, {'file': name, 'url': url, 'sha256': digest(raw), 'minutes': len(frame)}


def assemble():
    months = pd.date_range(FIRST, pd.Timestamp('2026-04-01', tz='UTC'), freq='MS')
    front = pd.date_range(pd.Timestamp('2026-05-01', tz='UTC'), CACHE_START, freq='D', inclusive='left')
    tail = pd.date_range(TAIL, END, freq='D', inclusive='left')
    tasks = [('monthly', t.strftime('%Y-%m'), t, t+pd.offsets.MonthBegin()) for t in months]
    tasks += [('daily', t.strftime('%Y-%m-%d'), t, t+pd.Timedelta(days=1)) for t in front.union(tail)]
    inputs = []
    parts = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for frame, source in pool.map(price_archive, tasks):
            parts.append(frame)
            inputs.append(source)
            print(source['file'], source['minutes'], flush=True)
    cached = CACHE / 'binance_futures_BTCUSDT_1m.csv'
    parts.append(pd.read_csv(cached, usecols=COLS))
    inputs.append({'file': str(cached.relative_to(ROOT)), 'sha256': digest(cached.read_bytes())})
    prices = pd.concat(parts, ignore_index=True).sort_values('ts').reset_index(drop=True)
    expected = np.arange(stamp(FIRST), stamp(END), 60000, dtype=np.int64)
    assert np.array_equal(prices.ts.to_numpy(), expected)
    assert np.isfinite(prices[COLS[1:]]).all().all()
    assert (prices.low > 0).all()
    assert (prices.low <= prices[['open','close']].min(axis=1)).all()
    assert (prices.high >= prices[['open','close']].max(axis=1)).all()

    cached_funding = CACHE / 'binance_futures_BTCUSDT_funding.csv'
    url = 'https://fapi.binance.com/fapi/v1/fundingRate?' + urlencode(dict(
        symbol=SYMBOL, startTime=stamp(TAIL), endTime=stamp(END)-1, limit=1000))
    raw = retrieve(url, RAW / 'funding_2026-10-06_to_2026-11-03.json')
    extra_funding = pd.DataFrame(json.loads(raw))
    funding = pd.concat([pd.read_csv(cached_funding), extra_funding], ignore_index=True)
    assert (funding.symbol == SYMBOL).all()
    raw_times = funding.fundingTime.astype(np.int64)
    aligned = ((raw_times + 30000) // 60000) * 60000
    max_jitter = int((raw_times - aligned).abs().max())
    assert max_jitter <= 1000
    funding['ts'] = aligned
    funding = funding.loc[funding.ts.between(stamp(FIRST), stamp(END)-1)].sort_values('ts')
    assert np.array_equal(funding.ts.to_numpy(), np.arange(stamp(FIRST), stamp(END), 28800000, dtype=np.int64))
    funding['funding'] = funding.fundingRate.astype(float) * funding.markPrice.astype(float)
    assert np.isfinite(funding.funding).all()
    prices = prices.join(funding.set_index('ts').funding, on='ts')
    prices.funding = prices.funding.fillna(0.)
    prices.index = pd.DatetimeIndex(pd.to_datetime(prices.pop('ts'), unit='ms', utc=True), name='time')
    prices.to_parquet(P/'bars.parquet')
    inputs += [{'file': str(cached_funding.relative_to(ROOT)), 'sha256': digest(cached_funding.read_bytes())},
               {'file': 'funding_2026-10-06_to_2026-11-03.json', 'url': url, 'sha256': digest(raw)}]
    manifest = {'instrument': 'Binance USD-M BTCUSDT perpetual', 'start': str(FIRST), 'end_exclusive': str(END),
                'minutes': len(prices), 'funding_events': len(funding), 'max_funding_alignment_ms': max_jitter,
                'funding_units': 'settled rate times event markPrice, USDT per BTC',
                'missing_price_minutes': 0, 'missing_funding_events': 0,
                'bars_sha256': digest((P/'bars.parquet').read_bytes()), 'inputs': inputs}
    (P/'data_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='inputs'}, indent=2), flush=True)


if __name__ == '__main__':
    assemble()

```
</details>

<details><summary>metrics.csv</summary>

```csv
start,horizon,path,policy,net,dd_minute,dd_hour,dd_minute_time,episodes,sides,triggered,triggered_inventory,gross,fees,funding,fills,tps,gap_maker_fills,post_only_rejections
2024-04-01,14,color,continue,-350.110636422428,841.2751905511589,821.552546071137,2024-11-13 16:13:00+00:00,44,88,67,67,-207.153085904207,168.6952099157648,25.737659397543744,4284.0,3318.0,0.0,149.0
2024-04-01,14,color,cancel,35.11178120312819,467.1952566506475,451.1206898316842,2024-08-08 23:02:00+00:00,44,88,67,67,107.96816030240888,77.4291147643754,4.57273566509463,2027.0,1643.0,0.0,8.0
2024-04-01,14,color,close,108.74746219117247,425.5049353357598,407.74843206743566,2024-08-08 23:02:00+00:00,44,88,67,67,196.26576101052567,85.01272522812239,-2.50557359123078,2027.0,1399.0,0.0,8.0
2024-08-01,14,color,continue,-457.2613439874256,785.7415304873214,765.3009970789536,2024-11-13 16:13:00+00:00,38,76,57,57,-340.3405184468037,140.40370454700962,23.48287900638766,3552.0,2739.0,0.0,145.0
2024-08-01,14,color,cancel,126.17622243779616,425.50493533575974,407.7484320674356,2024-08-08 23:02:00+00:00,38,76,57,57,188.15200928231872,65.65223007457314,3.6764432300506185,1724.0,1405.0,0.0,8.0
2024-08-01,14,color,close,107.87918857289088,425.50493533575974,407.7484320674356,2024-08-08 23:02:00+00:00,38,76,57,57,181.6577606450275,72.27545736650723,-1.503114705629363,1724.0,1192.0,0.0,8.0
2024-08-01,7,color,continue,-910.900864381883,1015.8041382244587,1003.6139095811205,2026-09-21 20:27:00+00:00,68,136,84,84,-776.0825524029957,145.9528067861336,11.134494807246782,3466.0,2382.0,0.0,108.0
2024-08-01,7,color,cancel,-216.81519651749744,378.2872943498768,375.0501562831845,2026-08-21 09:00:00+00:00,68,136,84,84,-136.69710742892693,86.79233645611237,6.674247367541932,2109.0,1512.0,0.0,0.0
2024-08-01,7,color,close,94.53933072872444,298.1507363163526,294.74133503490464,2025-03-06 05:59:00+00:00,68,136,84,84,182.7132137372082,93.23579776993809,5.061914761454306,2109.0,1308.0,0.0,0.0
2024-08-01,28,color,continue,-542.6601346194144,1150.407648620183,1140.7831466242606,2024-11-22 19:37:00+00:00,23,46,41,41,-454.4226953980844,145.8505008362257,57.613061614895685,3906.0,3284.0,0.0,347.0
2024-08-01,28,color,cancel,-463.13815734956705,629.253321097922,616.0830383968948,2026-08-28 01:33:00+00:00,23,46,41,41,-423.42552304805787,50.431390458360355,10.718756156851216,1352.0,1146.0,0.0,47.0
2024-08-01,28,color,close,-374.1344625528799,588.3114139400689,584.2520160170443,2024-10-07 01:10:00+00:00,23,46,41,41,-314.1215609467704,55.8919816512564,-4.120919954853158,1352.0,969.0,0.0,47.0
2024-08-01,14,OHLC,continue,-381.59925965090116,763.8183125879779,743.3777791796101,2024-11-13 16:13:00+00:00,38,76,57,57,-262.9882277023875,142.16275172016913,23.55171977165575,3607.0,2794.0,0.0,145.0
2024-08-01,14,OHLC,cancel,192.25878418412083,416.3087196053849,396.80264006743556,2024-08-08 23:02:00+00:00,38,76,57,57,255.70229336235695,67.18615821093157,3.742649032695387,1772.0,1453.0,0.0,8.0
2024-08-01,14,OHLC,close,173.9617503192156,416.3087196053849,396.80264006743556,2024-08-08 23:02:00+00:00,38,76,57,57,249.2080447250658,73.80938550286562,-1.436908902984595,1772.0,1240.0,0.0,8.0
2024-08-01,14,OLHC,continue,-343.57909439991715,774.7358306520146,754.2952972436468,2024-11-13 16:13:00+00:00,38,76,57,57,-224.4522459839501,142.53374217622743,23.406893760260452,3621.0,2810.0,0.0,145.0
2024-08-01,14,OLHC,cancel,215.6543443201498,425.5049353357597,407.74843206743554,2024-08-08 23:02:00+00:00,38,76,57,57,279.5781673160557,67.43349751871695,3.5096745228110655,1781.0,1463.0,0.0,8.0
2024-08-01,14,OLHC,close,189.98672556387442,425.5049353357597,407.74843206743554,2024-08-08 23:02:00+00:00,38,76,57,57,265.5510076594082,74.0603406079403,-1.5039414875934982,1781.0,1250.0,0.0,8.0

```
</details>
