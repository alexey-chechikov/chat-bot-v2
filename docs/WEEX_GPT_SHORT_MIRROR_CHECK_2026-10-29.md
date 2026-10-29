# Проверка зеркального шорта на тех же шести окнах — 29.10.2026

Продолжение разборов ab39ffa8 и 59eff905. Пользователь заметил, что на показанном падающем участке
большинство циклов могли быть прибыльны в шорт. Проверка выполнена отдельно, без изменения торговых
исходников, настроек или процессов и без повторного обучения/подбора параметров.

## Результат

Для ETH предположение подтвердилось: **все шесть окон прибыльны в зеркальном шорте**.
Для BTC — три прибыльных окна и три окна без исполнений. Пустые окна не считаются выигрышными сделками.
Во всех 12 проверяемых окнах конечный short-остаток равен нулю: прибыль уже реализована внутри модели.
Незавершённость шестого исходного LONG-цикла не означает открытый шорт: BTC №6 закрыл обе продажи тейками,
ETH №6 — все четыре. Это шесть фиксированных окон, не шесть завершений автономного short-контроллера.

| Вариант, условные USDT | BTC | ETH |
|---|---:|---:|
| Исходная лонг-сетка | -8.706 | -30.125 |
| Зеркальная шорт-сетка в тех же окнах | +4.349 | +15.347 |

Все суммы условные, не реальные сделки или балансы. Включены комиссии, funding, неблагоприятное
проскальзывание рыночного закрытия. Оценка расходов на конечный остаток здесь нулевая: short-позиций не осталось.

| Цикл | BTC short net | BTC входов / тейков | ETH short net | ETH входов / тейков | Статус окна |
|---|---:|---:|---:|---:|---|
| 1 | +0.000 | 0 / 0 | +1.370 | 1 / 1 | до исходной даты завершения; short flat |
| 2 | +0.000 | 0 / 0 | +0.229 | 1 / 0 | до исходной даты завершения; short flat |
| 3 | +1.372 | 1 / 1 | +2.746 | 2 / 2 | до исходной даты завершения; short flat |
| 4 | +0.228 | 1 / 0 | +4.123 | 3 / 3 | до исходной даты завершения; short flat |
| 5 | +0.000 | 0 / 0 | +1.383 | 1 / 1 | до исходной даты завершения; short flat |
| 6 | +2.749 | 2 / 2 | +5.496 | 4 / 4 | до конца истории; short flat, long был открыт |

## Что именно зеркалили

- Сохранены исходные моменты запуска, первого запрета добора и завершения каждого лонгового цикла.
- Шорт продаёт лимиткой на 0.6% выше опоры; тейк покупает на 1.4% ниже цены продажи.
  Без лотов опора следует за минимумом; с лотами — самая высокая цена открытой продажи.
- Те же условные 100 USDT на заявку и потолок номинала 1000, maker 0.016%, taker 0.048%,
  проскальзывание 0.02%. Для покрытия шорта проскальзывание повышает цену покупки.
- Комиссия остаётся расходом. Знак funding для шорта обратный. Объём стоящей заявки сохраняется.
- При наступлении исходного stop_new новые продажи запрещены; существующие тейки остаются.
  В исходную дату закрытия остаток выкупается. В последнем исходном окне оценивается остаток на конце данных;
  фактически short-лотов на конце не осталось у обоих активов.

Это **проверка на фиксированных ретроспективных окнах**, а не автономная short-стратегия.
Собственные пороги прибыли/потери шорта не меняли заранее зафиксированные границы окон.
В ETH №6 часовая оценка достигала собственного порога +5; автономный контроллер мог бы закрыть его раньше.
Следовательно, приведённый итог нельзя выдавать за результат полного контроллера шорт-сетки с неизменными правилами выхода.

## Почему результат отличается от визуального подсчёта стрелок

Простое направление open запуска → open завершения (для открытого окна — последний close)
даёт **4 из 6** в пользу одиночного шорта у каждого актива, без учёта расходов.
Но сетка может заработать на промежуточном снижении и закрыть тейки даже при росте цены между концами окна.
И наоборот: если цена сразу падает, лимитная продажа выше опоры может не исполниться.
Именно поэтому ETH имеет больше прибыльных сеточных окон, а BTC — три пустых.

Знак лонгового net нельзя просто поменять: комиссии не становятся доходом, места/объёмы исполнений,
тейки и сроки получения funding меняются. Проверка использует отдельный short-ledger.

## Что это меняет в выводах

Исходный тест описывал управление лонгами. Его отрицательный результат на падающем отрезке
не позволяет отвергнуть идею выбора направления по факторам. В этой ретроспективе short-сторона заметно лучше.

Однако направление выбрано после просмотра графика, а окна взяты у модели, обученной на исходах лонгов.
Не доказано, что доступные в момент решения факторы заранее выбрали бы шорт. Следующая содержательная проверка —
раздельные исходы LONG/SHORT/WAIT для одних и тех же прошлых состояний, выбор только по зрелой истории,
общий учёт текущей позиции и независимый тестовый отрезок. Шорт нельзя объявлять правильным направлением всегда.

## Проверки

**8 синтетических тестов прошли:** short MTM и стоимость покрытия, знак funding, тейк и комиссии,
сохранение количества стоящей заявки, отсутствие исполнения при непрерывном падении, прекращение добора,
ограничение номинала, полностью реализованный short в незавершённом исходном long-окне.
Фиксированный replay лонга совпал по всем 12 исходным циклам до 1e-8:
net, gross, комиссии, funding, входы, тейки и остаток. SHA исходных модулей совпали с сохранённым прогоном.
Проверки не подтверждают точность реального исполнения WEEX: остаются H1/OHLC, полные исполнения касаний,
отсутствие очереди/частичных исполнений и непроверенное историческое время публикации факторов.

## Воспроизведение

Нужны ранее переданные каталоги multifactor_grid_20261029 (исходники, output) и grid_cycle_review_20261029/audit.json.
Файлы ниже сохранить в research/short_mirror_check_20261029. Зависимости исходного пакета сохраняются.

```sh
python research/short_mirror_check_20261029/short_check.py --html /path/to/metrics_20261029_0802.html
python -m pytest --noconftest -c research/multifactor_grid_20261029/pytest.ini -q research/short_mirror_check_20261029/test_short_check.py
```

Исходный HTML SHA-256: `a2502aec14a6fb05d203a33193503eb1624808f6d28ed3d4c1f79723c5f6fe65`.
Результаты и исходники включены в один документ; сырых аккаунтных данных и ключей нет.

### FILE: short_check.py
````python
"""Retrospective same-window short-grid check; no learning or live operations."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parent / "multifactor_grid_20261029"
sys.path.insert(0, str(SOURCE))
from controller import Config, GridBook, Lot, PendingEntry
from prototype import load_html


class ShortBook(GridBook):
    """Linear-perpetual mirror: sell higher, buy lower; funding sign reversed."""
    def __init__(self, config):
        super().__init__(config)
        if not 0 < config.target_pct < 100:
            raise ValueError("Short take-profit percentage must be below 100")

    def net(self, price):
        return self.realized - self.fees - self.funding + self.cost - self.qty * price

    def liquidation_net(self, price):
        px = price * (1 + self.config.slippage)
        return self.net(px) - self.qty * px * self.config.taker_fee

    def settle_funding(self, price, rate):
        self.funding -= self.qty * price * rate

    def point(self, price, allow_new=True):
        keep, took = [], False
        for lot in self.lots:
            if price <= lot.tp:
                self.realized += lot.qty * (lot.entry - lot.tp)
                self.fees += lot.qty * lot.tp * self.config.maker_fee
                self.turnover += lot.qty * lot.tp
                self.takes += 1
                took = True
            else:
                keep.append(lot)
        self.lots = keep
        if not allow_new:
            self.cancel_entry()
            return
        if took:
            self.pending = None
        if self.lots:
            self.reference = max(x.entry for x in self.lots)
        elif self.reference is None or price < self.reference:
            self.reference = price
            self.pending = None
        if self.pending is None:
            level = self.reference * (1 + self.config.step_pct / 100)
            qty = self.config.order_notional / level
            if max(self.cost, self.qty * level) + qty * level <= self.config.capital_cap + 1e-9:
                self.pending = PendingEntry(level, qty)
        order = self.pending
        if order is not None and price >= order.price:
            if max(self.cost, self.qty * order.price) + order.qty * order.price <= self.config.capital_cap + 1e-9:
                self.lots.append(Lot(order.price, order.qty, order.price * (1 - self.config.target_pct / 100)))
                self.fees += order.qty * order.price * self.config.maker_fee
                self.turnover += order.qty * order.price
                self.entries += 1
                self.max_lots = max(self.max_lots, len(self.lots))
                self.pending = None

    def flatten(self, open_price):
        self.cancel_entry()
        px = open_price * (1 + self.config.slippage)
        self.realized += self.cost - self.qty * px
        self.fees += self.qty * px * self.config.taker_fee
        self.turnover += self.qty * px
        self.lots = []


def frozen_window(bars, cycle, cls, config):
    """Fix original launch/stop-new/end times; do not re-optimize short exits.

    This diagnostic ignores the short's own risk/profit/time triggers. Thus it
    measures the user's same-six-windows conjecture, not a deployable strategy.
    """
    start, end = pd.Timestamp(cycle["start"]), pd.Timestamp(cycle["end"])
    stop = pd.Timestamp(cycle["first_stop_new"]["bar_start"]) if cycle.get("first_stop_new") else None
    book = cls(config)
    min_liq, max_liq, closed = 0.0, 0.0, cycle["status"] == "closed"
    for at, row in bars.loc[start:end].iterrows():
        o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        book.settle_funding(o, float(row["funding_rate"]))
        if closed and at == end:
            book.flatten(o)
            mark = o
            min_liq = min(min_liq, book.net(mark))
            max_liq = max(max_liq, book.net(mark))
            break
        for price in ((o, l, h, c) if c >= o else (o, h, l, c)):
            book.point(price, allow_new=stop is None or at < stop)
        mark = c
        min_liq = min(min_liq, book.liquidation_net(c))
        max_liq = max(max_liq, book.liquidation_net(c))
    return {"net_pnl": book.net(mark), "estimated_liquidation_net": book.liquidation_net(mark),
            "realized_gross": book.realized, "fees": book.fees, "funding_paid": book.funding,
            "entries": book.entries, "takes": book.takes, "open_qty": book.qty,
            "min_liquidation_at_observed_points": min_liq, "max_liquidation_at_observed_points": max_liq,
            "own_profit_threshold_observed": max_liq >= config.profit_target,
            "own_loss_threshold_observed": min_liq <= -config.loss_limit,
            "position_status": "open_inventory" if book.qty > 0 else "flat",
            "status": "closed_at_frozen_end" if closed else "marked_at_data_end"}


def run(html):
    original = json.loads((SOURCE / "output/results.json").read_text(encoding="utf-8"))
    audit = json.loads((BASE.parent / "grid_cycle_review_20261029/audit.json").read_text(encoding="utf-8"))
    for name, digest in original["source_code_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
    frames, provenance = load_html(html)
    assert provenance["source_sha256"] == original["provenance"]["source_sha256"]
    cfg = Config(**original["config"])
    results = {"status": "RETROSPECTIVE_FIXED_LONG_WINDOWS_SHORT_COUNTERFACTUAL",
               "source_html_sha256": provenance["source_sha256"], "source_code_unchanged": True,
               "assumptions": ["Same original long launch, stop-new and terminal times, selected retrospectively",
                               "Short is not separately trained; no directional selection model is tested",
                               "Same step 0.6%, lot target 1.4%, notional 100, cap 1000, fees and adverse slippage",
                               "Full OHLC touch fills, no production execution parity",
                               "Short risk/profit triggers are measured but do not change the fixed windows",
                               "Last original long window is unfinished; short inventory status is reported separately"],
               "symbols": {}}
    for sym, source in frames.items():
        rows = []
        for c in audit["symbols"][sym]["multifactor"]["cycles"]:
            long = frozen_window(source, c, GridBook, cfg)
            for field in ("net_pnl", "estimated_liquidation_net", "realized_gross", "fees", "entries", "takes", "open_qty"):
                assert abs(long[field] - c[field]) < 1e-8, (sym, c["cycle_id"], field)
            assert abs(long["funding_paid"] - c["funding"]) < 1e-8
            short = frozen_window(source, c, ShortBook, cfg)
            begin = float(source.loc[pd.Timestamp(c["start"]), "open"])
            finish = float(source.loc[pd.Timestamp(c["end"]), "open" if c["status"] == "closed" else "close"])
            rows.append({"cycle_id": c["cycle_id"], "start": c["start"], "end": c["end"],
                         "original_status": c["status"], "direction_short_gross_pct": (begin-finish)/begin*100,
                         "long": long, "short": short})
        results["symbols"][sym] = {"cycles": rows, "summary": {
            "windows": len(rows), "price_direction_short_positive": sum(r["direction_short_gross_pct"] > 0 for r in rows),
            "short_grid_positive_mark_or_close": sum(r["short"]["estimated_liquidation_net"] > 1e-9 for r in rows),
            "short_grid_positive_original_closed_windows": sum(r["original_status"] == "closed" and r["short"]["net_pnl"] > 1e-9 for r in rows),
            "short_grid_positive_flat_windows": sum(r["short"]["open_qty"] == 0 and r["short"]["net_pnl"] > 1e-9 for r in rows),
            "short_grid_windows_with_open_inventory_at_end": sum(r["short"]["open_qty"] > 0 for r in rows),
            "short_grid_empty": sum(r["short"]["entries"] == 0 for r in rows),
            "long_net_total": sum(r["long"]["estimated_liquidation_net"] for r in rows),
            "short_net_total": sum(r["short"]["estimated_liquidation_net"] for r in rows),
            "own_short_profit_threshold_windows": [r["cycle_id"] for r in rows if r["short"]["own_profit_threshold_observed"]],
            "own_short_loss_threshold_windows": [r["cycle_id"] for r in rows if r["short"]["own_loss_threshold_observed"]]}}
    (BASE / "results.json").write_bytes((json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))
    print(json.dumps({s:v["summary"] for s,v in results["symbols"].items()},indent=2))
    return results


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--html", required=True)
    run(p.parse_args().html)
````

### FILE: test_short_check.py
````python
from dataclasses import replace
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from short_check import Config, ShortBook, Lot, PendingEntry, frozen_window


def test_short_inventory_mark_and_adverse_cover():
    cfg=Config(taker_fee=.001,slippage=.002)
    b=ShortBook(cfg);b.lots=[Lot(100,2,98)]
    assert b.net(110)==-20
    expected=200-2*90*1.002-2*90*1.002*.001
    assert b.liquidation_net(90)==pytest.approx(expected)
    b.flatten(90)
    assert b.net(90)==pytest.approx(expected) and b.qty==0


def test_positive_funding_received_and_negative_paid():
    b=ShortBook(Config());b.lots=[Lot(100,2,98)]
    b.settle_funding(100,.01)
    assert b.funding==-2 and b.net(100)==2
    b.settle_funding(100,-.02)
    assert b.funding==2 and b.net(100)==-2


def test_short_take_profit_and_fees():
    b=ShortBook(Config(maker_fee=.001));b.lots=[Lot(100,2,98)]
    b.point(98,allow_new=False)
    assert b.qty==0 and b.takes==1 and b.realized==4
    assert b.net(98)==pytest.approx(4-.196)


def test_standing_sell_order_retains_quantity():
    b=ShortBook(Config(target_pct=10,maker_fee=0))
    b.lots=[Lot(100,1,90)];b.pending=PendingEntry(101,2)
    b.point(101)
    assert b.qty==3 and b.turnover==202


def test_falling_price_without_bounce_does_not_fill_short_entry():
    b=ShortBook(Config())
    for price in (100,99,98,97): b.point(price)
    assert b.entries==0 and b.net(97)==0
    assert b.pending.price==pytest.approx(97*1.006)


def test_stop_new_keeps_short_inventory_until_take():
    b=ShortBook(Config(maker_fee=0));b.lots=[Lot(100,1,98)];b.pending=PendingEntry(101,2)
    b.point(105,allow_new=False)
    assert b.qty==1 and b.pending is None
    b.point(98,allow_new=False)
    assert b.qty==0 and b.realized==2


def test_short_cap_prevents_new_order():
    b=ShortBook(Config(capital_cap=100,order_notional=100));b.lots=[Lot(100,1,98)]
    b.point(101)
    assert b.qty==1 and b.entries==0


def test_unfinished_long_window_can_have_fully_realized_short_profit():
    import pandas as pd
    ix=pd.date_range('2026-01-01',periods=3,freq='h',tz='UTC')
    bars=pd.DataFrame([(100,102,100,100,0),(99,99,99,99,0),(90,90,90,90,0)],
                      columns=['open','high','low','close','funding_rate'],index=ix)
    cycle={'start':ix[0].isoformat(),'end':ix[-1].isoformat(),'status':'open',
           'first_stop_new':{'bar_start':ix[1].isoformat()}}
    cfg=Config(step_pct=1,target_pct=1,maker_fee=0,taker_fee=0,slippage=0)
    result=frozen_window(bars,cycle,ShortBook,cfg)
    assert result['status']=='marked_at_data_end'
    assert result['position_status']=='flat' and result['open_qty']==0
    assert result['takes']==1 and result['net_pnl']==pytest.approx(1)
    assert result['realized_gross']==pytest.approx(result['net_pnl'])
````

### FILE: results.json
````json
{
  "status": "RETROSPECTIVE_FIXED_LONG_WINDOWS_SHORT_COUNTERFACTUAL",
  "source_html_sha256": "a2502aec14a6fb05d203a33193503eb1624808f6d28ed3d4c1f79723c5f6fe65",
  "source_code_unchanged": true,
  "assumptions": [
    "Same original long launch, stop-new and terminal times, selected retrospectively",
    "Short is not separately trained; no directional selection model is tested",
    "Same step 0.6%, lot target 1.4%, notional 100, cap 1000, fees and adverse slippage",
    "Full OHLC touch fills, no production execution parity",
    "Short risk/profit triggers are measured but do not change the fixed windows",
    "Last original long window is unfinished; short inventory status is reported separately"
  ],
  "symbols": {
    "BTCUSDT": {
      "cycles": [
        {
          "cycle_id": 1,
          "start": "2026-10-21T22:00:00+00:00",
          "end": "2026-10-22T22:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": 3.949882075471698,
          "long": {
            "net_pnl": -8.603320025758592,
            "estimated_liquidation_net": -8.603320025758592,
            "realized_gross": -8.415278711101564,
            "fees": 0.18796066621867125,
            "funding_paid": 8.064843835564519e-05,
            "entries": 3,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -9.58409987225036,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 0.0,
            "estimated_liquidation_net": 0.0,
            "realized_gross": 0.0,
            "fees": 0.0,
            "funding_paid": 0.0,
            "entries": 0,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 2,
          "start": "2026-10-23T06:00:00+00:00",
          "end": "2026-10-23T10:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": 0.2178289712531731,
          "long": {
            "net_pnl": 0.0,
            "estimated_liquidation_net": 0.0,
            "realized_gross": 0.0,
            "fees": 0.0,
            "funding_paid": 0.0,
            "entries": 0,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 0.0,
            "estimated_liquidation_net": 0.0,
            "realized_gross": 0.0,
            "fees": 0.0,
            "funding_paid": 0.0,
            "entries": 0,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 3,
          "start": "2026-10-24T00:00:00+00:00",
          "end": "2026-10-25T00:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": 0.3896012686067838,
          "long": {
            "net_pnl": 0.07573975479925305,
            "estimated_liquidation_net": 0.07573975479925305,
            "realized_gross": 0.1536183366036994,
            "fees": 0.06407373680156978,
            "funding_paid": 0.013804845002876565,
            "entries": 1,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -1.2536837584817035,
            "max_liquidation_at_observed_points": 0.23962174873885073,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 1.3716397261864595,
            "estimated_liquidation_net": 1.3716397261864595,
            "realized_gross": 1.4000000000000041,
            "fees": 0.031776,
            "funding_paid": -0.0034157261864554427,
            "entries": 1,
            "takes": 1,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 1.3716397261864595,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 4,
          "start": "2026-10-26T00:00:00+00:00",
          "end": "2026-10-27T00:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": -0.002121968237876496,
          "long": {
            "net_pnl": 1.5499195986535874,
            "estimated_liquidation_net": 1.5499195986535874,
            "realized_gross": 1.6823385583710189,
            "fees": 0.0963595225080181,
            "funding_paid": 0.0360594372094134,
            "entries": 2,
            "takes": 1,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -0.5075678611002152,
            "max_liquidation_at_observed_points": 2.059576291827042,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 0.22846352364506886,
            "estimated_liquidation_net": 0.22846352364506886,
            "realized_gross": 0.2644470022025871,
            "fees": 0.06387306543894275,
            "funding_paid": -0.02788958688142452,
            "entries": 1,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -0.2788739333886776,
            "max_liquidation_at_observed_points": 0.9230808699515695,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 5,
          "start": "2026-10-27T20:00:00+00:00",
          "end": "2026-10-27T22:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": -0.12318152499965954,
          "long": {
            "net_pnl": 0.0,
            "estimated_liquidation_net": 0.0,
            "realized_gross": 0.0,
            "fees": 0.0,
            "funding_paid": 0.0,
            "entries": 0,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 0.0,
            "estimated_liquidation_net": 0.0,
            "realized_gross": 0.0,
            "fees": 0.0,
            "funding_paid": 0.0,
            "entries": 0,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 6,
          "start": "2026-10-28T16:00:00+00:00",
          "end": "2026-10-29T06:00:00+00:00",
          "original_status": "open",
          "direction_short_gross_pct": 0.734402940592085,
          "long": {
            "net_pnl": -1.6610421129302608,
            "estimated_liquidation_net": -1.7279182706045444,
            "realized_gross": 0.0,
            "fees": 0.016,
            "funding_paid": 0.006219094215238224,
            "entries": 1,
            "takes": 0,
            "open_qty": 0.0012304898754923897,
            "min_liquidation_at_observed_points": -1.8785507950162952,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "open_inventory",
            "status": "marked_at_data_end"
          },
          "short": {
            "net_pnl": 2.748915201862877,
            "estimated_liquidation_net": 2.748915201862877,
            "realized_gross": 2.800000000000005,
            "fees": 0.063552,
            "funding_paid": -0.012467201862871763,
            "entries": 2,
            "takes": 2,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -1.3165162567450206,
            "max_liquidation_at_observed_points": 2.748915201862877,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "marked_at_data_end"
          }
        }
      ],
      "summary": {
        "windows": 6,
        "price_direction_short_positive": 4,
        "short_grid_positive_mark_or_close": 3,
        "short_grid_positive_original_closed_windows": 2,
        "short_grid_positive_flat_windows": 3,
        "short_grid_windows_with_open_inventory_at_end": 0,
        "short_grid_empty": 3,
        "long_net_total": -8.705578942910297,
        "short_net_total": 4.3490184516944055,
        "own_short_profit_threshold_windows": [],
        "own_short_loss_threshold_windows": []
      }
    },
    "ETHUSDT": {
      "cycles": [
        {
          "cycle_id": 1,
          "start": "2026-10-21T18:00:00+00:00",
          "end": "2026-10-22T18:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": 5.368366616278155,
          "long": {
            "net_pnl": -24.678617393088253,
            "estimated_liquidation_net": -24.678617393088253,
            "realized_gross": -24.11992466954996,
            "fees": 0.500422436158616,
            "funding_paid": 0.05827028737967621,
            "entries": 8,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -24.681877403819712,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 1.3696360927645053,
            "estimated_liquidation_net": 1.3696360927645053,
            "realized_gross": 1.4000000000000061,
            "fees": 0.031776,
            "funding_paid": -0.0014120927644991382,
            "entries": 1,
            "takes": 1,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -0.12555811422978766,
            "max_liquidation_at_observed_points": 1.3696360927645053,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 2,
          "start": "2026-10-23T05:00:00+00:00",
          "end": "2026-10-23T08:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": -0.29163654899535885,
          "long": {
            "net_pnl": 0.0,
            "estimated_liquidation_net": 0.0,
            "realized_gross": 0.0,
            "fees": 0.0,
            "funding_paid": 0.0,
            "entries": 0,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 0.0,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 0.228552248651328,
            "estimated_liquidation_net": 0.228552248651328,
            "realized_gross": 0.2865856100346349,
            "fees": 0.06386243890718338,
            "funding_paid": -0.0058290775238765,
            "entries": 1,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -0.1255562607209543,
            "max_liquidation_at_observed_points": 0.228552248651328,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 3,
          "start": "2026-10-23T19:00:00+00:00",
          "end": "2026-10-24T19:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": 2.6667721769407375,
          "long": {
            "net_pnl": -5.088809297775378,
            "estimated_liquidation_net": -5.088809297775378,
            "realized_gross": -4.885118144535056,
            "fees": 0.18965514329062316,
            "funding_paid": 0.01403600994969845,
            "entries": 3,
            "takes": 0,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -9.162875296945893,
            "max_liquidation_at_observed_points": 1.1793659434915598,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 2.7464773384585945,
            "estimated_liquidation_net": 2.7464773384585945,
            "realized_gross": 2.799999999999988,
            "fees": 0.063552,
            "funding_paid": -0.010029338458606828,
            "entries": 2,
            "takes": 2,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -1.406931907652908,
            "max_liquidation_at_observed_points": 2.7464773384585945,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 4,
          "start": "2026-10-25T08:00:00+00:00",
          "end": "2026-10-26T08:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": 1.2531477828104365,
          "long": {
            "net_pnl": 0.5825691028497413,
            "estimated_liquidation_net": 0.5825691028497413,
            "realized_gross": 0.7018850346422432,
            "fees": 0.09588890481662828,
            "funding_paid": 0.023427026975873653,
            "entries": 2,
            "takes": 1,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -0.20790404296088938,
            "max_liquidation_at_observed_points": 2.3121353833515257,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 4.123173849643147,
            "estimated_liquidation_net": 4.123173849643147,
            "realized_gross": 4.200000000000002,
            "fees": 0.095328,
            "funding_paid": -0.01850184964314553,
            "entries": 3,
            "takes": 3,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -1.8850010682533298,
            "max_liquidation_at_observed_points": 4.123173849643147,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 5,
          "start": "2026-10-26T17:00:00+00:00",
          "end": "2026-10-27T16:00:00+00:00",
          "original_status": "closed",
          "direction_short_gross_pct": -1.1114750424506736,
          "long": {
            "net_pnl": 1.3529010149360101,
            "estimated_liquidation_net": 1.3529010149360101,
            "realized_gross": 1.3999999999999952,
            "fees": 0.032224,
            "funding_paid": 0.014874985063985057,
            "entries": 1,
            "takes": 1,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -0.8519204639753175,
            "max_liquidation_at_observed_points": 1.3529010149360101,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          },
          "short": {
            "net_pnl": 1.3830392642041296,
            "estimated_liquidation_net": 1.3830392642041296,
            "realized_gross": 1.400000000000008,
            "fees": 0.031776,
            "funding_paid": -0.014815264204121764,
            "entries": 1,
            "takes": 1,
            "open_qty": 0,
            "min_liquidation_at_observed_points": 0.0,
            "max_liquidation_at_observed_points": 1.3830392642041296,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "closed_at_frozen_end"
          }
        },
        {
          "cycle_id": 6,
          "start": "2026-10-28T15:00:00+00:00",
          "end": "2026-10-29T06:00:00+00:00",
          "original_status": "open",
          "direction_short_gross_pct": 0.8531874482835343,
          "long": {
            "net_pnl": -2.1607087555047997,
            "estimated_liquidation_net": -2.293392826387458,
            "realized_gross": 2.8000000000000123,
            "fees": 0.096448,
            "funding_paid": 0.015445161936712604,
            "entries": 4,
            "takes": 2,
            "open_qty": 0.08438860659383095,
            "min_liquidation_at_observed_points": -2.672040051074999,
            "max_liquidation_at_observed_points": 2.0237884004289666,
            "own_profit_threshold_observed": false,
            "own_loss_threshold_observed": false,
            "position_status": "open_inventory",
            "status": "marked_at_data_end"
          },
          "short": {
            "net_pnl": 5.496224124737601,
            "estimated_liquidation_net": 5.496224124737601,
            "realized_gross": 5.600000000000026,
            "fees": 0.127104,
            "funding_paid": -0.023328124737575485,
            "entries": 4,
            "takes": 4,
            "open_qty": 0,
            "min_liquidation_at_observed_points": -2.4197462600488655,
            "max_liquidation_at_observed_points": 5.496224124737601,
            "own_profit_threshold_observed": true,
            "own_loss_threshold_observed": false,
            "position_status": "flat",
            "status": "marked_at_data_end"
          }
        }
      ],
      "summary": {
        "windows": 6,
        "price_direction_short_positive": 4,
        "short_grid_positive_mark_or_close": 6,
        "short_grid_positive_original_closed_windows": 5,
        "short_grid_positive_flat_windows": 6,
        "short_grid_windows_with_open_inventory_at_end": 0,
        "short_grid_empty": 0,
        "long_net_total": -30.125349399465335,
        "short_net_total": 15.347102918459306,
        "own_short_profit_threshold_windows": [
          6
        ],
        "own_short_loss_threshold_windows": []
      }
    }
  }
}
````

