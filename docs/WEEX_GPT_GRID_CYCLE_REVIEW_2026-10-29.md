# Разбор циклов многофакторной сетки — 29.10.2026

Продолжение пакета `ab39ffa8` (WEEX_GPT_MULTIFACTOR_GRID_PROTOTYPE_2026-10-29.md).
Запрос пользователя: показать, где модель запускала/закрывала сетку, какие факторы видела и почему получился минус.
Живые торговые исходники, настройки, заявки и процессы не менялись. Разбирается ранее сохранённый офлайн-прогон;
параметры и модель не подбирались заново. Все суммы ниже условные, не данные счёта.

## Основной вывод

В этом прогоне модель умела разрешить запуск и остановить добор, но **не показала завершения по прогнозному сигналу выхода**.
Ни одного закрытия по цели полного net +5 тоже не было. Для BTC и ETH по три цикла завершились по сроку 24 часа,
по два — после запрета добора, когда лотов не осталось, ещё по одному остались открыты.
Запрет добора сохранял текущую позицию. Поэтому положительная оценка её закрытия могла позже стать убытком.

Вход проверял переход среднего исхода 20 прошлых аналогов в >0. У **всех 12 запусков q20 был отрицательным**,
но это значение не ограничивало запуск. Это не доказывает полезность нового порога q20: такой порог требует независимого теста.
Аналоги перекрываются; число отрицательных исходов нельзя называть вероятностью будущего убытка.

## Откуда взялся минус

| Составляющая, условные USDT | BTC | ETH |
|---|---:|---:|
| Тейки до расходов | +1.400 | +5.600 |
| Рыночные закрытия остатка, с проскальзыванием | -7.979 | -29.703 |
| Переоценка открытого остатка | -1.639 | -4.849 |
| Комиссии | -0.364 | -0.915 |
| Funding | -0.056 | -0.126 |
| Оценка расходов на закрытие открытого остатка | -0.067 | -0.133 |
| Итог с оценкой закрытия остатка | -8.706 | -30.125 |

Главная отрицательная составляющая — ценовой результат рыночного закрытия и оставшегося инвентаря.
Комиссии и funding уменьшают итог, но не объясняют основную часть убытка. Gross рыночных закрытий уже включает
проскальзывание; второй раз оно не вычитается. Открытый остаток не объявлен закрытой сделкой.

## Все циклы

| Актив / цикл | Запуск UTC | Покупок / тейков | Среднее / q20 при запуске | Оценка закрытия при запрете добора | Конец / причина | Итог |
|---|---|---:|---:|---:|---|---:|
| BTC №1 | 10-21 22:00 | 3 / 0 | +0.156 / -1.568 | -3.490 (10-22 03:00) | 10-22 22:00, 24 часа | -8.603 |
| BTC №2 | 10-23 06:00 | 0 / 0 | +0.641 / -1.442 | +0.000 (10-23 09:00) | 10-23 10:00, лотов нет | +0.000 |
| BTC №3 | 10-24 00:00 | 1 / 0 | +0.135 / -1.170 | -0.096 (10-24 08:00) | 10-25 00:00, 24 часа | +0.076 |
| BTC №4 | 10-26 00:00 | 2 / 1 | +0.069 / -1.261 | +1.237 (10-26 09:00) | 10-27 00:00, 24 часа | +1.550 |
| BTC №5 | 10-27 20:00 | 0 / 0 | +0.110 / -1.758 | +0.000 (10-27 21:00) | 10-27 22:00, лотов нет | +0.000 |
| BTC №6 | 10-28 16:00 | 1 / 0 | +0.124 / -0.705 | -0.342 (10-29 01:00) | 10-29 07:00, открыт | -1.728 |
| ETH №1 | 10-21 18:00 | 8 / 0 | +0.888 / -0.811 | -15.490 (10-22 10:00) | 10-22 18:00, 24 часа | -24.679 |
| ETH №2 | 10-23 05:00 | 0 / 0 | +1.064 / -0.687 | +0.000 (10-23 07:00) | 10-23 08:00, лотов нет | +0.000 |
| ETH №3 | 10-23 19:00 | 3 / 0 | +0.218 / -1.121 | +1.175 (10-24 00:00) | 10-24 19:00, 24 часа | -5.089 |
| ETH №4 | 10-25 08:00 | 2 / 1 | +0.149 / -3.114 | +2.178 (10-25 19:00) | 10-26 08:00, 24 часа | +0.583 |
| ETH №5 | 10-26 17:00 | 1 / 1 | +0.312 / -1.814 | -0.453 (10-26 19:00) | 10-27 16:00, лотов нет | +1.353 |
| ETH №6 | 10-28 15:00 | 4 / 2 | +0.910 / -0.035 | +2.025 (10-28 22:00) | 10-29 07:00, открыт | -2.293 |

BTC: шесть запусков, четыре с покупками и два пустых. ETH: шесть запусков, пять с покупками и один пустой.
Нулевые пустые циклы не считаются прибыльными сделками. Последняя строка каждого актива — оценка на 29.10 07:00 UTC,
а не выполненный выход. Время заполнения лимиток известно лишь как час и условная OHLC-точка.

## Четыре показательных случая

1. **BTC №1, 21.10 22:00 → 22.10 22:00 UTC.** При запуске среднее +0.1558, q20 −1.5679, отрицательных исходов 10 из 20.
   Добор прекратился через пять часов: оценка закрытия портфеля −3.490. Но лоты остались открыты; по сроку получено −8.603.
   При выходе контекстный прогноз новой пустой сетки оставался положительным (+0.0601); закрытие вызвано таймером.
2. **ETH №1, 21.10 18:00 → 22.10 18:00 UTC.** Среднее +0.8876, q20 −0.8111, отрицательных аналогов 7 из 20.
   При остановке добора через 16 часов оценка закрытия −15.490; итог по таймеру −24.679.
   Контекстный прогноз при выходе +1.1478, но это не прогноз удержания уже накопленного остатка.
3. **ETH №3.** При запрете добора 24.10 00:00 оценка закрытия была **+1.175**, а по истечении 24 часов итог **−5.089**.
   Прототип не фиксировал эту положительную оценку: правило stop_new запрещало новые покупки и оставляло существующие лоты.
4. **ETH №6.** При запрете добора 28.10 22:00 оценка закрытия **+2.025**. В конце истории MTM **−2.161**,
   с оценкой расходов на закрытие **−2.293**. Цикл ещё открыт. Его тейки +2.800 не компенсировали остаток и расходы.

Оценки на stop_new рассчитаны по open соответствующего часа, **после funding и до OHLC-пути**.
Это оценка имеющегося портфеля с допущениями проскальзывания/комиссии, не исполненный результат альтернативной стратегии.
Из выбранных постфактум примеров нельзя заключить «всегда закрывать по первому stop_new».

## Какие факторы были доступны алгоритму

Для действия в t используются значения часа t−2; этот час закрылся в t−1. Реальное время первой публикации
исторических значений CoinGlass неизвестно, поэтому речь об индексах прототипа, а не доказанном архиве доступности.
Для 12 запусков и 36 контекстов восстановлены исходные 20 аналогов, значения всех 93 признаков и факт их участия
в расстоянии. Среднее, q20 и число аналогов совпали с сохранёнными оценками.

Пример BTC №1: цена за прошлые 6ч +0.136%, OI −0.389%, net поток примерно −1.213 стандартного отклонения от прошлого окна,
стакан −1.154; доля ликвидаций лонгов 16.795%; корреляция доходности и net потока за 24ч +0.839.
Алгоритм не использовал явное правило «этот набор разрешает лонг». Он нашёл ближайшие состояния и получил среднее +0.1558.
Отдельный фактор нельзя объявить причиной убытка по одному такому эпизоду. Расстояния семейств описывают сходство,
не причинный вклад в прогноз. Funding в исходнике уже выражен в процентах; изменения OI/цены преобразованы из log-change
в обычные проценты только для отображения. Buy/sell дисбаланс не выдуман: исходные отдельные ряды отсутствуют.

## Интерактивный разбор

Артефакт: `research/grid_cycle_review_20261029/grid_cycle_review.html`, полностью автономный, без CDN/запросов в браузере.
Переключатели BTC/ETH, цикл и событие; графики цены, полного net и прогноза; запуск/закрытие/открытый конец различаются.
В карточке — разложение результата, условие действия, значения факторов и 20 исторических аналогов; отдельно журнал исполнений.
Запуск пустой сетки отличается от заполнения лимитной заявки. Контекст факторов при таймерном выходе не назван его причиной.
Кривая net ставится на момент доступности переоценки (закрытие часа), а не на его начало.

SHA-256 HTML: `f9dd8931b5917069cc734fb119f64eee77389397a391baff199c9cd46f236530`.
SHA-256 исходного HTML метрик: `a2502aec14a6fb05d203a33193503eb1624808f6d28ed3d4c1f79723c5f6fe65`.

## Проверка

Повторно воспроизведены все десять комбинаций (пять вариантов × два актива). Каждый цикл, полная кривая и итог
совпали с сохранённым прогоном до 1e-8. Журнал восстановлен временным подклассом GridBook только в процессе исследования;
исходник контроллера не менялся. Отдельно сверены тейки, рыночные закрытия, комиссии, funding и остаток.
Восстановленные 36 наборов аналогов используют только зрелые прошлые исходы. Проверены временной сдвиг и сумма
компонент в карточках; SHA исходников совпали с исходным результатом.

Логика интерфейса проверена в памяти без браузера: два актива, 12 циклов, 36 контекстов, переключатели, клик по маркеру,
масштабирование/сброс и данные трёх графиков. Политика встроенного браузера отклонила file://: визуальная проверка HTML
не выполнена, обход не предпринимался. Отдельный обзорный PNG построен Matplotlib и просмотрен.
В HTML показаны 27 ключевых признаков; все 93 значения каждого контекста сохранены в explanations.json.

Точность исполнения остаётся ограничена H1-моделью полного заполнения касаний, условным OHLC-путём и отсутствием
архива публикаций факторов. Это объяснение поведения прототипа, не доказанный разбор реальных сделок WEEX.
SMA разрешала LONG весь отрезок и совпала с постоянной сеткой, поэтому этот график не проверяет пользу её отсечения.

## Проверяемое продолжение для Claude

Нужна модель результата **для текущего состояния позиции**, сравнивающая продолжение, прекращение добора и закрытие.
Оценку новой пустой сетки нельзя считать оценкой удержания накопленных лотов. Отдельно проверить предварительно заданное
ограничение нижнего хвоста исходов при входе; не подбирать порог на этих 12 запусках. Сравнение проводить на независимом
периоде с непрерывными данными исполнения/факторов и реальными сменами режима. До этого не менять живую торговлю.

## Воспроизведение и исходники визуализации

Использовать исходный пакет `ab39ffa8` в `research/multifactor_grid_20261029` с сохранённым каталогом output.
Ниже шесть файлов для соседнего `research/grid_cycle_review_20261029`. Зависимости исходного пакета, `plotly==6.6.0`, Matplotlib;
для проверки логики интерфейса — Node.js.

```sh
python research/grid_cycle_review_20261029/audit.py --html /path/to/metrics_20261029_0802.html
python research/grid_cycle_review_20261029/factor_explanations.py
python research/grid_cycle_review_20261029/build_dashboard.py --html /path/to/metrics_20261029_0802.html
node research/grid_cycle_review_20261029/check_ui_logic.cjs
python research/grid_cycle_review_20261029/plot_overview.py
```

Результаты audit.json/explanations.json содержат детальные подтверждения; HTML включает только необходимые данные и Plotly.
Сырого приватного учёта, ключей, балансов пользователя и аккаунтных выгрузок в документе нет.
В Git публикуется один этот документ. Полная HTML-библиотека не дублируется в Markdown; генератор воспроизводит артефакт.

### FILE: audit.py
````python
"""Read-only diagnostic replay of the frozen offline prototype.

GridBook is subclassed only in this process. No source or trading settings change.
Synthetic OHLC point order is recorded without invented intrahour timestamps.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "multifactor_grid_20261029"
sys.path.insert(0, str(SOURCE))
import controller
import prototype
from features import FEATURES_METADATA


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def table(name):
    data = pd.read_csv(SOURCE / "output" / name, index_col=0)
    data.index = pd.to_datetime(data.index, utc=True)
    return data


def explain_analogs(features, labels, estimates, at, variant):
    """Reconstruct the exact already-frozen neighbor choice; no feature effects."""
    if at not in features.index or at not in estimates.index:
        return None
    estimate = estimates.loc[at].to_dict()
    if not pd.notna(estimate.get("mean")):
        return {"source_hour_start": at, "known_after_close": at + pd.Timedelta(hours=1), "estimate": None}
    columns = [k for k in features if variant != "price_cycles" or FEATURES_METADATA[k]["family"] == "price"]
    if variant == "multifactor_without_correlations":
        columns = [k for k in columns if FEATURES_METADATA[k]["family"] != "relations"]
    i = features.index.get_loc(at)
    pool = labels.iloc[:max(0, i - prototype.EXECUTION_DELAY - prototype.HORIZON + 1)].dropna()
    train, current = features.loc[pool.index, columns], features.loc[at, columns]
    scale = train.quantile(.75) - train.quantile(.25)
    usable = current.notna() & scale.gt(1e-12) & train.notna().mean().ge(.5)
    names = usable.index[usable].tolist()
    delta = ((train[names] - current[names]) / scale[names]).clip(-10, 10).pow(2)
    scores = []
    for family in sorted({FEATURES_METADATA[k]["family"] for k in names}):
        members = [k for k in names if FEATURES_METADATA[k]["family"] == family]
        part = delta[members]
        scores.append(part.mean(axis=1).where(part.notna().sum(axis=1) >= max(1, int(np.ceil(len(members) / 2)))))
    distances = pd.concat(scores, axis=1)
    nearest = distances.mean(axis=1).where(distances.notna().sum(axis=1) == len(scores)).dropna().sort_values(kind="mergesort").head(prototype.NEIGHBORS)
    outcomes = pool.loc[nearest.index]
    assert len(outcomes) == prototype.NEIGHBORS
    assert abs(float(outcomes.mean()) - estimate["mean"]) < 1e-8
    assert abs(float(outcomes.quantile(.2)) - estimate["q20"]) < 1e-8
    return {"source_hour_start": at, "known_after_close": at + pd.Timedelta(hours=1),
            "estimate": estimate, "positive_neighbors": int(outcomes.gt(0).sum()),
            "negative_neighbors": int(outcomes.lt(0).sum()), "zero_neighbors": int(outcomes.eq(0).sum()),
            "worst_neighbor": float(outcomes.min()), "best_neighbor": float(outcomes.max()),
            "used_feature_names": names,
            "features": features.loc[at].to_dict(),
            "neighbors": [{"source_hour_start": stamp, "fixed_cycle_net": float(outcomes.loc[stamp]),
                           "distance": float(distance)} for stamp, distance in nearest.items()],
            "interpretation": "Similarity and historical outcomes, not causal attribution; overlapping outcomes are dependent"}


def traced_replay(bars, decisions, config, policy):
    original_book, original_validate = controller.GridBook, controller._validate
    events, context = [], {"cycle_id": 0}

    def add(kind, book, **values):
        events.append({"kind": kind, "cycle_id": book.audit_cycle_id,
                       "bar_start": context["at"], "bar_end": context["at"] + pd.Timedelta(hours=1),
                       **values})

    class TraceFrame(pd.DataFrame):
        def iterrows(self):
            for at, row in super().iterrows():
                context.update(at=at, point_index=0,
                               point_names=["open", "low", "high", "close"] if row.close >= row.open else ["open", "high", "low", "close"])
                yield at, row

    class TraceBook(original_book):
        def __init__(self, cfg):
            super().__init__(cfg)
            context["cycle_id"] += 1
            self.audit_cycle_id = context["cycle_id"]
            self.audit_drained = False
            add("cycle_start", self, time_resolution="bar_open", is_fill=False)

        def point(self, price, allow_new=True):
            context["point_index"] += 1
            point = context["point_names"][context["point_index"] - 1]
            if not allow_new and not self.audit_drained:
                self.audit_drained = True
                add("stop_new", self, time_resolution="bar_open", open_qty=self.qty,
                    valuation_price=price, net_at_open=self.net(price),
                    liquidation_net_at_open=self.liquidation_net(price),
                    valuation_timing="bar_open_after_funding_before_OHLC_path",
                    source_hour_start=context["at"] - pd.Timedelta(hours=2))
            before = {id(lot): lot for lot in self.lots}
            super().point(price, allow_new)
            after = {id(lot): lot for lot in self.lots}
            for key, lot in before.items():
                if key not in after:
                    add("take_profit", self, price=lot.tp, qty=lot.qty,
                        gross=lot.qty * (lot.tp - lot.entry), fee=lot.qty * lot.tp * config.maker_fee,
                        synthetic_point=point, point_index=context["point_index"], time_resolution="synthetic_point_within_hour")
            for key, lot in after.items():
                if key not in before:
                    add("entry_fill", self, price=lot.entry, qty=lot.qty, gross=0.0,
                        fee=lot.qty * lot.entry * config.maker_fee, target_price=lot.tp,
                        synthetic_point=point, point_index=context["point_index"], time_resolution="synthetic_point_within_hour")

        def settle_funding(self, price, rate):
            amount = self.qty * price * rate
            super().settle_funding(price, rate)
            if amount:
                add("funding", self, amount=amount, rate=rate, qty=self.qty,
                    mark_price=price, time_resolution="bar_open")

        def flatten(self, price):
            qty, cost = self.qty, self.cost
            px = price * (1 - config.slippage)
            super().flatten(price)
            add("cycle_close", self, price=px, open_price=price, qty=qty,
                gross=qty * px - cost, fee=qty * px * config.taker_fee,
                slippage_cost=qty * price * config.slippage,
                is_market_fill=qty > 0, time_resolution="bar_open")

    def validate(*args):
        frame, dec = original_validate(*args)
        return TraceFrame(frame), dec

    try:
        controller._validate, controller.GridBook = validate, TraceBook
        result = controller.replay(bars, decisions, config, policy)
    finally:
        controller._validate, controller.GridBook = original_validate, original_book
    return result, events


def run(html):
    baseline = json.loads((SOURCE / "output/results.json").read_text(encoding="utf-8"))
    for name, expected in baseline["source_code_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected, name
    frames, provenance = prototype.load_html(html)
    assert provenance["source_sha256"] == baseline["provenance"]["source_sha256"]
    result = {"status": "READ_ONLY_TRACE_OF_FROZEN_HOURLY_PROTOTYPE", "source_sha256": provenance["source_sha256"],
              "source_code_sha256": baseline["source_code_sha256"],
              "time_rule": "UTC; starts/exits at bar open; fills only assigned to synthetic OHLC point, not an invented intrahour minute",
              "parity_tolerance": 1e-8, "symbols": {}}
    cfg = controller.Config(**baseline["config"])
    for symbol, source in frames.items():
        expected_symbol = baseline["symbols"][symbol]
        bars = source.loc[pd.Timestamp(expected_symbol["evaluation_start"]):]
        features = table(f"{symbol}_features.csv")
        labels = table(f"{symbol}_retrospective_cycle_labels.csv").iloc[:, 0]
        variants = {}
        for variant in expected_symbol["policies"]:
            decisions = table(f"{symbol}_{variant}_decisions.csv").loc[bars.index]
            estimates = table(f"{symbol}_{variant}_historical_estimates.csv")
            policy = "continuous" if variant == "continuous" else "gated" if variant == "sma100_daily" else "cycles"
            replay, events = traced_replay(bars, decisions, cfg, policy)
            expected = expected_symbol["policies"][variant]
            for field in ("net_pnl", "estimated_liquidation_net", "max_drawdown", "fees", "funding", "turnover", "open_qty"):
                assert abs(replay["summary"][field] - expected[field]) < 1e-8, (symbol, variant, field)
            frozen_cycles = pd.read_csv(SOURCE / "output" / f"{symbol}_{variant}_cycles.csv")
            assert len(replay["cycles"]) == len(frozen_cycles)
            frozen_curve = pd.read_csv(SOURCE / "output" / f"{symbol}_{variant}_equity.csv")
            for field in ("equity", "estimated_liquidation_equity", "drawdown", "open_qty"):
                assert np.max(np.abs(np.array([row[field] for row in replay["equity_curve"]]) - frozen_curve[field].to_numpy())) < 1e-8
            cycles = []
            for index, cycle in enumerate(replay["cycles"]):
                for field in ("net_pnl", "estimated_liquidation_net", "realized_gross", "fees", "funding", "open_qty", "open_cost", "turnover", "entries", "takes"):
                    assert abs(cycle[field] - frozen_cycles.iloc[index][field]) < 1e-8
                cycle_events = [event for event in events if event["cycle_id"] == cycle["cycle_id"]]
                takes = sum(event["gross"] for event in cycle_events if event["kind"] == "take_profit")
                flatten = sum(event["gross"] for event in cycle_events if event["kind"] == "cycle_close")
                assert abs(takes + flatten - cycle["realized_gross"]) < 1e-8
                assert abs(sum(event.get("fee", 0) for event in cycle_events) - cycle["fees"]) < 1e-8
                assert abs(sum(event["amount"] for event in cycle_events if event["kind"] == "funding") - cycle["funding"]) < 1e-8
                residual = cycle["net_pnl"] - (cycle["realized_gross"] - cycle["fees"] - cycle["funding"])
                cost = cycle["net_pnl"] - cycle["estimated_liquidation_net"]
                start, end = pd.Timestamp(cycle["start"]), pd.Timestamp(cycle["end"])
                context_at = start - pd.Timedelta(hours=prototype.EXECUTION_DELAY)
                start_context = explain_analogs(features, labels, estimates, context_at, variant) if policy == "cycles" else None
                drain = next((event for event in cycle_events if event["kind"] == "stop_new"), None)
                drain_context = explain_analogs(features, labels, estimates, drain["source_hour_start"], variant) if drain and policy == "cycles" else None
                active_decisions = decisions.loc[start:end]
                if cycle["status"] == "open":
                    end_available = end + pd.Timedelta(hours=1)
                else:
                    end_available = end
                cycles.append({**cycle, "end_available_at": end_available, "has_fills": cycle["entries"] > 0,
                               "first_fill": next((event for event in cycle_events if event["kind"] == "entry_fill"), None),
                               "start_context": start_context, "first_stop_new": drain,
                               "stop_new_context": drain_context,
                               "decomposition": {"take_profit_gross": takes, "forced_close_gross": flatten,
                                                  "residual_mtm": residual, "fees": cycle["fees"], "funding": cycle["funding"],
                                                  "estimated_residual_exit_cost": cost,
                                                  "net_mtm": cycle["net_pnl"], "net_with_estimated_exit": cycle["estimated_liquidation_net"]},
                               "signals_during_interval": {name: int(active_decisions[name].sum()) for name in ("start", "stop_new", "exit")},
                               "events": cycle_events})
            totals = {key: sum(c["decomposition"][key] for c in cycles) for key in cycles[0]["decomposition"]}
            assert abs(totals["net_with_estimated_exit"] - expected["estimated_liquidation_net"]) < 1e-8
            variants[variant] = {"summary": replay["summary"], "parity_verified": True,
                                 "totals": totals, "cycles": cycles,
                                 "filled_cycles": sum(c["has_fills"] for c in cycles),
                                 "empty_cycles": sum(not c["has_fills"] for c in cycles),
                                 "exit_reasons": dict(Counter(c["exit_reason"] or "open" for c in cycles)),
                                 "all_start_q20_negative": all(c["start_context"]["estimate"]["q20"] < 0 for c in cycles) if policy == "cycles" else None}
        result["symbols"][symbol] = variants
    result = clean(result)
    (HERE / "audit.json").write_bytes((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    print(json.dumps({s: {v: {"totals": x["totals"], "filled_cycles": x["filled_cycles"], "empty_cycles": x["empty_cycles"], "exit_reasons": x["exit_reasons"]} for v, x in e.items() if "multifactor" in v} for s, e in result["symbols"].items()}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    args = parser.parse_args()
    run(args.html)
````

### FILE: factor_explanations.py
````python
"""Reconstruct explanations of saved decisions without fitting a new model.

Analog distances describe similarity, not causal factor importance. The actual
source publication times are unknown; available_at below is bar-close time.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "multifactor_grid_20261029"
sys.path.insert(0, str(SOURCE))
import prototype as model
from features import FEATURES_METADATA

SELECTED = ["price_ret_6h", "price_move_6h_atr", "atr14_pct", "er24", "range_position24",
            "oi_change_6h", "funding_level", "funding_oiw_level", "funding_change_6h",
            "flow_net_6h", "flow_net6_z72", "flow_imbalance_6h", "book_mean6_z72",
            "liq_all_long_sum6", "liq_all_short_sum6", "liq_long_share6",
            "ls_accounts_level", "ls_accounts_change_6h", "ls_top_level", "wi2_level",
            "corr_return_net_flow_24h", "corr_return_oi_change_24h",
            "corr_cross_flow_oi_24h", "corr_cross_flow_book_24h",
            "corr_cross_flow_liquidations_24h", "corr_cross_funding_oi_24h",
            "corr_cross_positioning_funding_24h"]


def read_timeseries(path):
    frame = pd.read_csv(path, index_col=0, float_precision="round_trip")
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def detailed_analogs(features, labels, i, saved):
    """Exact expansion of prototype.neighbors_at, preserving its stable order."""
    columns = list(features.columns)
    original = model.neighbors_at(features, labels, i, columns)
    if original is None:
        assert pd.isna(saved.get("mean", np.nan))
        return {"status": "no_mature_analog_estimate", "mean": None, "q20": None,
                "neighbors": [], "features_used": [], "families": []}
    for key in ("mean", "q20", "neighbors", "training_cases", "features_used", "families_used"):
        assert np.isclose(float(original[key]), float(saved[key]), rtol=1e-11, atol=1e-9), (i, key, original[key], saved[key])
    last_mature = i - model.EXECUTION_DELAY - model.HORIZON
    pool = labels.iloc[:max(0, last_mature + 1)].dropna()
    train = features.loc[pool.index, columns]
    current = features.iloc[i][columns]
    scale = train.quantile(.75) - train.quantile(.25)
    usable = current.notna() & scale.gt(1e-12) & train.notna().mean().ge(.5)
    names = usable.index[usable].tolist()
    delta = ((train[names] - current[names]) / scale[names]).clip(-10, 10).pow(2)
    scores = {}
    members_by_family = {}
    for family in sorted({FEATURES_METADATA[k]["family"] for k in names}):
        members = [k for k in names if FEATURES_METADATA[k]["family"] == family]
        members_by_family[family] = members
        part = delta[members]
        scores[family] = part.mean(axis=1).where(part.notna().sum(axis=1) >= max(1, int(np.ceil(len(members) / 2))))
    distances = pd.DataFrame(scores)
    score = distances.mean(axis=1).where(distances.notna().sum(axis=1) == len(scores))
    nearest = score.dropna().sort_values(kind="mergesort").head(model.NEIGHBORS)
    outcomes = pool.loc[nearest.index]
    assert len(nearest) == model.NEIGHBORS
    assert np.isclose(outcomes.mean(), original["mean"], atol=1e-10)
    assert np.isclose(outcomes.quantile(.2), original["q20"], atol=1e-10)
    available_at = features.index[i] + pd.Timedelta(hours=1)
    analogs = []
    for at, distance in nearest.items():
        mature_at = at + pd.Timedelta(hours=model.EXECUTION_DELAY + model.HORIZON + 1)
        assert mature_at <= available_at, (at, mature_at, available_at)
        analogs.append({"source_hour": at, "mature_at": mature_at,
                        "fixed_cycle_net": float(outcomes.loc[at]), "distance": float(distance)})
    return {"status": "reconstructed_and_verified", "mean": float(outcomes.mean()),
            "q20": float(outcomes.quantile(.2)), "negative_analog_count": int(outcomes.lt(0).sum()),
            "negative_analog_fraction": float(outcomes.lt(0).mean()),
            "negative_fraction_is_probability": False,
            "analog_count": len(nearest), "training_cases": len(pool),
            "features_used_count": len(names), "features_available_count": int(current.notna().sum()),
            "features_total": len(current), "features_used": names,
            "neighbors": analogs,
            "families": [{"family": family, "used_count": len(members_by_family[family]),
                          "mean_squared_scaled_distance": float(distances.loc[nearest.index, family].mean())}
                         for family in distances],
            "family_distance_interpretation": "Similarity geometry only, not causal importance, a sign or an outcome contribution"}


def explain_event(event_type, execution_at, cycle, features, labels, estimates, decisions):
    execution_at = pd.Timestamp(execution_at)
    source_at = execution_at - pd.Timedelta(hours=model.EXECUTION_DELAY)
    i = features.index.get_loc(source_at)
    current = features.loc[source_at]
    estimate = detailed_analogs(features, labels, i, estimates.loc[source_at])
    previous = estimates.iloc[i - 1].get("mean", np.nan) if i else np.nan
    saved_decision = decisions.loc[execution_at]
    decision_flags = {name: bool(saved_decision[name]) for name in ("start", "stop_new", "exit")}
    mean = estimates.loc[source_at].get("mean", np.nan)
    is_model_action = event_type in ("start", "first_stop_new") or (
        event_type == "exit" and cycle.get("exit_reason") == "historical fixed-cycle net estimate; heuristic environment gate")
    if event_type == "start":
        assert mean > 0 and (pd.isna(previous) or previous <= 0), (execution_at, mean, previous)
        assert decision_flags["start"] and not decision_flags["stop_new"] and not decision_flags["exit"]
        trigger = "Новый переход среднего исхода 20 зрелых аналогов из <=0 (или неизвестно) в >0; разрешён запуск пустой сетки. Запуск не означает исполненную покупку."
    elif event_type == "first_stop_new":
        assert pd.isna(mean) or mean <= 0
        assert decision_flags["stop_new"]
        trigger = "Среднее стало <=0 или неизвестным: новые покупки прекращаются до конца цикла. Уже купленные лоты остаются и могут закрыться по тейкам."
    elif event_type == "exit":
        reason = cycle.get("exit_reason")
        trigger = {"max_cycle_bars": "Истёк фиксированный срок 24 часа. Закрытие вызвано таймером, не прогнозом разворота и не знаком текущих факторов.",
                   "drain_complete": "Добор ранее остановлен и лотов больше нет; цикл завершён на следующем open. Это может быть пустой цикл без сделок.",
                   "net_profit_target": "Полный net с оценкой закрытия остатка достиг цели +5 на предыдущем close; исполнение выхода на следующем open.",
                   "loss_limit": "Полный net с оценкой закрытия остатка достиг лимита потерь -30 на предыдущем close; исполнение выхода на следующем open."}.get(reason, "Два последовательных прогноза ниже -5 дают сигнал выхода; это эвристика для текущей позиции.")
    else:
        trigger = "Конец доступной истории. Цикл не закрыт; остаток сохранён и переоценён."
    return {"event": event_type, "execution_at": execution_at, "feature_source_hour": source_at,
            "is_executed_action": event_type != "open_at_end",
            "valuation_at": execution_at + pd.Timedelta(hours=1) if event_type == "open_at_end" else None,
            "feature_bar_closed_at": source_at + pd.Timedelta(hours=1),
            "historical_source_publication_verified": False,
            "model_context_caused_this_action": is_model_action,
            "trigger": trigger, "previous_estimate_mean": previous, "decision_flags": decision_flags,
            "estimate": estimate,
            "selected_features": [{"name": name, "value": current[name],
                                   "used_in_distance": name in estimate["features_used"],
                                   "known": bool(pd.notna(current[name])), **FEATURES_METADATA[name]} for name in SELECTED],
            "all_features": {name: {"value": value, "used_in_distance": name in estimate["features_used"]}
                             for name, value in current.items()},
            "missing_selected_features": [name for name in SELECTED if pd.isna(current[name])],
            "ledger_trigger_observed_at": execution_at if event_type == "exit" and not is_model_action else None}


def run():
    result = {"method": "Exact expansion of saved multifactor nearest-neighbor decisions; no new fit, tuning or counterfactual strategy",
              "timing": "Action at t uses features indexed t-2h, bar closed t-1h; archived publication times remain unknown",
              "source_hashes": {}, "symbols": {}, "verified_start_count": 0, "verified_event_count": 0}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        paths = {"features": SOURCE / "output" / f"{symbol}_features.csv",
                 "labels": SOURCE / "output" / f"{symbol}_retrospective_cycle_labels.csv",
                 "estimates": SOURCE / "output" / f"{symbol}_multifactor_historical_estimates.csv",
                 "decisions": SOURCE / "output" / f"{symbol}_multifactor_decisions.csv",
                 "cycles": SOURCE / "output" / f"{symbol}_multifactor_cycles.csv"}
        result["source_hashes"].update({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()})
        features = read_timeseries(paths["features"])
        labels = read_timeseries(paths["labels"]).iloc[:, 0]
        estimates = read_timeseries(paths["estimates"])
        decisions = read_timeseries(paths["decisions"])
        cycles = pd.read_csv(paths["cycles"], float_precision="round_trip")
        explained = []
        for cycle in cycles.to_dict("records"):
            start, end = pd.Timestamp(cycle["start"]), pd.Timestamp(cycle["end"])
            events = [explain_event("start", start, cycle, features, labels, estimates, decisions)]
            result["verified_start_count"] += 1
            during = decisions.loc[(decisions.index >= start) & (
                (decisions.index < end) if cycle["status"] == "closed" else (decisions.index <= end))]
            stops = during.loc[during.stop_new.eq(True)]
            if not stops.empty:
                events.append(explain_event("first_stop_new", stops.index[0], cycle, features, labels, estimates, decisions))
            event = "exit" if cycle["status"] == "closed" else "open_at_end"
            events.append(explain_event(event, end, cycle, features, labels, estimates, decisions))
            result["verified_event_count"] += len(events)
            explained.append({"cycle_id": int(cycle["cycle_id"]), "status": cycle["status"],
                              "start": start, "end": end, "entries": int(cycle["entries"]),
                              "filled_cycle": bool(cycle["entries"] > 0), "actual_net_pnl": cycle["net_pnl"],
                              "actual_estimated_liquidation_net": cycle["estimated_liquidation_net"],
                              "exit_reason": cycle["exit_reason"], "events": events})
        result["symbols"][symbol] = {"cycles": explained}
    result = clean(result)
    path = HERE / "explanations.json"
    path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    print(json.dumps({"path": str(path), "verified_start_count": result["verified_start_count"],
                      "verified_event_count": result["verified_event_count"]}))
    for symbol, s in result["symbols"].items():
        for cycle in s["cycles"]:
            entry = cycle["events"][0]
            e = entry["estimate"]
            print(symbol, cycle["cycle_id"], cycle["start"], "mean", round(e["mean"], 4), "q20", round(e["q20"], 4),
                  "negative", e["negative_analog_count"], "actual", round(cycle["actual_estimated_liquidation_net"], 4),
                  "stop", next((x["execution_at"] for x in cycle["events"] if x["event"] == "first_stop_new"), None))


if __name__ == "__main__":
    run()
````

### FILE: build_dashboard.py
````python
"""Build a standalone offline Plotly review from verified diagnostic artifacts."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import pandas as pd
from plotly.offline import get_plotlyjs

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parent / "multifactor_grid_20261029"
sys.path.insert(0, str(SOURCE))
from prototype import load_html

LABELS = {
    "price_ret_6h": "Изменение цены за 6ч", "price_move_6h_atr": "Ход цены за 6ч / ATR",
    "atr14_pct": "ATR14 / цена", "er24": "ER24: направленность движения",
    "range_position24": "Положение цены в диапазоне 24ч",
    "oi_change_6h": "Изменение OI за 6ч", "funding_level": "Funding",
    "funding_oiw_level": "Funding, взвешенный по OI", "funding_change_6h": "Изменение funding за 6ч",
    "flow_net_6h": "Net taker поток за 6ч", "flow_net6_z72": "Net поток относительно 72ч",
    "flow_imbalance_6h": "Относительный дисбаланс buy/sell за 6ч",
    "book_mean6_z72": "Стакан относительно 72ч", "liq_all_long_sum6": "Ликвидации лонгов за 6ч",
    "liq_all_short_sum6": "Ликвидации шортов за 6ч", "liq_long_share6": "Доля ликвидаций лонгов",
    "ls_accounts_level": "L/S по аккаунтам", "ls_accounts_change_6h": "Изменение L/S за 6ч",
    "ls_top_level": "L/S крупных позиций", "wi2_level": "WI2",
    "corr_return_net_flow_24h": "Корреляция: доходность ↔ поток, 24ч",
    "corr_return_oi_change_24h": "Корреляция: доходность ↔ изменение OI, 24ч",
    "corr_cross_flow_oi_24h": "Корреляция: поток ↔ изменение OI, 24ч",
    "corr_cross_flow_book_24h": "Корреляция: поток ↔ изменение стакана, 24ч",
    "corr_cross_flow_liquidations_24h": "Корреляция: поток ↔ изменение ликвидаций, 24ч",
    "corr_cross_funding_oi_24h": "Корреляция: изменение funding ↔ OI, 24ч",
    "corr_cross_positioning_funding_24h": "Корреляция: изменение L/S ↔ funding, 24ч",
}
REASONS = {"max_cycle_bars": "Истекли 24 часа", "drain_complete": "После запрета добора лотов не осталось",
           "loss_limit": "Лимит потери", "net_profit_target": "Цель полного net", "open": "Остаток ещё открыт"}
EVENTS = {"start": "Запуск сетки", "first_stop_new": "Первый запрет добора", "exit": "Завершение цикла",
          "open_at_end": "Последний час: остаток не закрыт"}
TRACE = {"cycle_start": "Запуск сетки, ещё не покупка", "entry_fill": "Покупка лимиткой",
         "take_profit": "Тейк лота", "stop_new": "Запрет добора", "funding": "Расчёт funding",
         "cycle_close": "Завершение цикла", "market_flatten": "Рыночное закрытие остатка"}


def display_feature(key, value, symbol):
    if value is None:
        return "нет данных"
    if key in {"price_ret_6h", "oi_change_6h", "ls_accounts_change_6h"}:
        return f"{100 * math.expm1(value):+.3f}%"
    if key in {"range_position24", "liq_long_share6", "flow_imbalance_6h"}:
        return f"{100 * value:.2f}%"
    if key in {"funding_level", "funding_oiw_level"}:
        return f"{value:.6f}%"
    if key == "funding_change_6h":
        return f"{value:+.6f} п.п."
    if key == "atr14_pct":
        return f"{value:.3f}%"
    if key in {"liq_all_long_sum6", "liq_all_short_sum6"}:
        return f"{value:,.0f} USD".replace(",", " ")
    if key == "flow_net_6h":
        return f"{value:+,.2f} {symbol.removesuffix('USDT')}".replace(",", " ")
    return f"{value:+.3f}" if key.startswith("corr_") or "z72" in key else f"{value:.3f}"


def explanation(cycle):
    p = cycle["decomposition"]
    if not cycle["entries"]:
        return "Сетка была разрешена, но ни одна покупка не исполнилась. После запрета добора пустой цикл завершился. Его нулевой результат не является прибыльной сделкой."
    stop = cycle.get("first_stop_new")
    parts = []
    if stop:
        parts.append(f"Добор остановлен {stop['bar_start'][5:16].replace('T', ' ')} UTC. Оценка полного закрытия тогда: {stop['liquidation_net_at_open']:+.3f} USDT. Это оценка портфеля, а не выполненная сделка.")
    if cycle["status"] == "open":
        parts.append(f"К концу истории остаток сохраняется. Тейки дали {p['take_profit_gross']:+.3f}, переоценка открытых лотов {p['residual_mtm']:+.3f} USDT до расходов.")
    elif cycle.get("exit_reason") == "max_cycle_bars":
        parts.append(f"По истечении 24 часов остаток закрыт по рынку: {p['forced_close_gross']:+.3f} USDT до комиссий/funding. Решение вызвал таймер, а не распознанный разворот.")
    else:
        parts.append("После запрета новых покупок оставшиеся лоты закрылись; цикл завершён без повторного запуска по старому сигналу.")
    parts.append(f"Тейки {p['take_profit_gross']:+.3f}; комиссии {p['fees']:.3f}; funding {p['funding']:+.3f} USDT. В отрицательном результате нельзя автоматически винить отдельный фактор.")
    return " ".join(parts)


def run(html):
    audit = json.loads((BASE / "audit.json").read_text(encoding="utf-8"))
    explanations = json.loads((BASE / "explanations.json").read_text(encoding="utf-8"))
    results = json.loads((SOURCE / "output/results.json").read_text(encoding="utf-8"))
    for name, digest in results["source_code_sha256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest, name
    frames, provenance = load_html(html)
    assert provenance["source_sha256"] == results["provenance"]["source_sha256"]
    data = {"provenance": {"text": "Часовая исследовательская модель • 21–29 октября 2026 • время UTC • условные суммы USDT. Это разбор сохранённого прогона, не живая торговля."}, "symbols": {}}
    component_names = [("take_profit_gross", "Тейки до расходов", 1), ("forced_close_gross", "Рыночные закрытия до расходов", 1),
                       ("residual_mtm", "Переоценка открытых лотов", 1), ("fees", "Комиссии", -1),
                       ("funding", "Funding: выплата − / получение +", -1),
                       ("estimated_residual_exit_cost", "Оценка расходов на закрытие остатка", -1)]
    for symbol, variants in audit["symbols"].items():
        record = variants["multifactor"]
        start = pd.Timestamp(results["symbols"][symbol]["evaluation_start"])
        bars = frames[symbol].loc[start:]
        item = {"summary": {"net": record["totals"]["net_with_estimated_exit"],
                            "filled_cycles": record["filled_cycles"], "empty_cycles": record["empty_cycles"]},
                "bars": [{"t": at.isoformat(), "o": float(row.open), "h": float(row.high), "l": float(row.low), "c": float(row.close)} for at, row in bars.iterrows()],
                "curves": {}, "estimates": [], "cycles": []}
        for variant in ("continuous", "multifactor_without_correlations", "multifactor"):
            curve = pd.read_csv(SOURCE / f"output/{symbol}_{variant}_equity.csv")
            item["curves"][variant] = [{"t": row.observed_at, "v": float(row.estimated_liquidation_equity)} for row in curve.itertuples()]
        est = pd.read_csv(SOURCE / f"output/{symbol}_multifactor_historical_estimates.csv", index_col=0)
        est.index = pd.to_datetime(est.index, utc=True) + pd.Timedelta(hours=2)
        for at, row in est.loc[start:bars.index[-1]].iterrows():
            item["estimates"].append({"t": at.isoformat(), "mean": None if pd.isna(row["mean"]) else float(row["mean"]),
                                      "q20": None if pd.isna(row["q20"]) else float(row["q20"])})
        contexts = {c["cycle_id"]: c for c in explanations["symbols"][symbol]["cycles"]}
        for cycle in record["cycles"]:
            cid = cycle["cycle_id"]
            components = [{"label": label, "value": sign * cycle["decomposition"][key]} for key, label, sign in component_names]
            assert abs(sum(x["value"] for x in components) - cycle["estimated_liquidation_net"]) < 1e-8
            c = {"id": cid, "start": cycle["start"], "end": cycle["end"],
                 "observed_end": (pd.Timestamp(cycle["end"]) + (pd.Timedelta(hours=1) if cycle["status"] == "open" else pd.Timedelta(0))).isoformat(),
                 "status": cycle["status"], "entries": cycle["entries"], "takes": cycle["takes"],
                 "net": cycle["estimated_liquidation_net"], "net_mtm": cycle["net_pnl"],
                 "reason": REASONS.get(cycle.get("exit_reason") or "open", cycle.get("exit_reason") or "open"),
                 "explanation": explanation(cycle), "components": components, "events": [], "trace": []}
            for event in contexts[cid]["events"]:
                estimate = event["estimate"]
                if event["event"] != "open_at_end":
                    assert pd.Timestamp(event["execution_at"]) - pd.Timestamp(event["feature_source_hour"]) == pd.Timedelta(hours=2)
                c["events"].append({"label": EVENTS.get(event["event"], event["event"]), "time": event["execution_at"],
                    "source_time": event["feature_source_hour"], "known_at": event["feature_bar_closed_at"],
                    "caused_by_model": event["model_context_caused_this_action"], "executed": event["is_executed_action"], "mean": estimate.get("mean"),
                    "q20": estimate.get("q20"), "negative_count": estimate.get("negative_analog_count"),
                    "neighbors_count": estimate.get("analog_count", 0), "rule": event["trigger"],
                    "features_used": estimate.get("features_used_count", 0),
                    "features": [{"label": LABELS.get(f["name"], f["name"]), "value": display_feature(f["name"], f["value"], symbol),
                                  "used": f["used_in_distance"]} for f in event["selected_features"]],
                    "analogs": [{"time": n["source_hour"], "net": n["fixed_cycle_net"]} for n in estimate.get("neighbors", [])]})
            for event in cycle["events"]:
                phase = event.get("synthetic_point")
                timing = f" · условная точка {phase} внутри часа" if phase else " · open часа"
                label = TRACE.get(event["kind"], event["kind"]) + timing
                if event["kind"] == "funding":
                    label += f"; выплата {event['amount']:+.6f} USDT"
                c["trace"].append({"time": event["bar_start"], "label": label,
                                   "price": event.get("price", event.get("mark_price")), "qty": event.get("qty", event.get("open_qty"))})
            item["cycles"].append(c)
        data["symbols"][symbol] = item
    packed = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    (BASE / "dashboard_data.json").write_bytes(packed.encode("utf-8"))
    template = (BASE / "dashboard_template.html").read_text(encoding="utf-8")
    assert template.count("@@PAYLOAD@@") == template.count("@@PLOTLY_JS@@") == 1
    html_output = template.replace("@@PAYLOAD@@", packed).replace("@@PLOTLY_JS@@", get_plotlyjs().replace("</script", "<\\/script"))
    (BASE / "grid_cycle_review.html").write_bytes(html_output.encode("utf-8"))
    checks = {"source_code_unchanged": True, "source_html_sha256": provenance["source_sha256"],
              "cycles": sum(len(s["cycles"]) for s in data["symbols"].values()),
              "explanations_verified": explanations["verified_event_count"],
              "html_sha256": hashlib.sha256(html_output.encode("utf-8")).hexdigest(), "html_bytes": len(html_output.encode("utf-8"))}
    (BASE / "dashboard_checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    run(parser.parse_args().html)
````

### FILE: dashboard_template.html
````html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сетка по сигналам — разбор циклов</title>
<style>
:root{color-scheme:light;--bg:#f5f6f8;--surface:#fff;--text:#172331;--muted:#526172;--line:#dce2e9;--accent:#176755;--blue:#3767a4;--purple:#7255a0;--orange:#ad5b19;--red:#ab3340;--green:#18745a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1280px;margin:auto;padding:32px 28px 56px}header{margin-bottom:24px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--accent);font-weight:700}h1{font-size:clamp(25px,3vw,36px);line-height:1.2;margin:8px 0 10px;letter-spacing:-.025em}h2{font-size:20px;line-height:1.3;margin:0 0 8px}h3{font-size:16px;margin:0 0 8px}p{margin:8px 0}.subtle{color:var(--muted)}.lede{max-width:960px}.notice{padding:12px 16px;border-left:3px solid #9a7b2e;background:#fcf9ef;margin:18px 0 0;font-size:14px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}.stat{background:var(--surface);padding:16px 20px;border:1px solid var(--line);border-radius:10px}.stat .label{font-size:13px;color:var(--muted)}.stat strong{display:block;font-size:27px;font-weight:650;margin:3px 0}.stat small{color:var(--muted)}.controls{display:flex;align-items:end;gap:14px;flex-wrap:wrap;padding:16px 0 22px}.field{display:grid;gap:5px}.field label{font-size:13px;font-weight:600}.field.asset{min-width:120px}.field.cycle{flex:1;min-width:260px}.field.event{max-width:720px;margin:16px 0}select,button{font:inherit;color:inherit;border:1px solid #bec9d4;background:#fff;border-radius:6px;padding:9px 12px;min-height:42px}select{max-width:100%;width:100%}button{cursor:pointer;white-space:nowrap}button:hover{background:#edf3f2;border-color:var(--accent)}button:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #aacbc3;outline-offset:2px}.buttonrow{display:flex;gap:8px;flex-wrap:wrap}.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:22px;margin-bottom:18px}.panel-title{display:flex;justify-content:space-between;gap:14px;align-items:baseline;flex-wrap:wrap}.tag{font-size:12px;font-weight:600;padding:3px 9px;border-radius:20px;background:#edf1f5;color:#34475b}.plot{width:100%;min-width:0}.plot.price{height:390px}.plot.equity{height:265px}.plot.estimate{height:265px}.chart-note{font-size:13px;color:var(--muted);margin-top:4px}.cycle-head{display:flex;justify-content:space-between;align-items:start;gap:20px;flex-wrap:wrap}.cycle-value{font-size:30px;font-weight:650;white-space:nowrap}.negative{color:var(--red)}.positive{color:var(--green)}.cycle-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:18px 0}.metric span{font-size:12px;color:var(--muted);display:block}.metric strong{font-size:17px;font-weight:600}.explain{padding:13px 16px;background:#f2f5f8;border-radius:7px;margin:14px 0}.components{display:flex;gap:12px;flex-wrap:wrap;padding:12px 0}.component{flex:1;min-width:130px;padding-right:16px;border-right:1px solid var(--line)}.component:last-child{border:0}.component span{display:block;font-size:12px;color:var(--muted)}.component strong{display:block;font-size:18px;margin-top:3px}.timing{font-size:13px;display:grid;gap:4px;margin:12px 0}.event-rule{font-weight:600}.snapshot-stats{display:flex;gap:24px;flex-wrap:wrap;margin:14px 0}.snapshot-stats strong{display:block;font-size:20px}.snapshot-stats span{font-size:12px;color:var(--muted)}details{border-top:1px solid var(--line);padding:12px 0}summary{cursor:pointer;font-weight:600;list-style-position:outside;margin-left:17px}details p{font-size:13px;color:var(--muted)}.table-wrap{overflow:auto;max-width:100%;margin-top:10px}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;font-weight:600;color:var(--muted);background:#f7f9fb}td,th{padding:9px 11px;border-bottom:1px solid #e5eaf0;vertical-align:top}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td.time{white-space:nowrap}td.yes{color:var(--accent)}.muted-row{color:var(--muted)}.empty{padding:14px 0;color:var(--muted);font-size:14px}footer{font-size:12px;color:var(--muted);margin-top:26px;border-top:1px solid var(--line);padding-top:18px;overflow-wrap:anywhere}.noscript{padding:20px;background:#fff2db;border:1px solid #dfc58b}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:760px){main{padding:20px 14px 36px}.panel{padding:16px 10px}.stats{gap:8px}.stat{padding:12px}.stat strong{font-size:22px}.stat small{font-size:11px}.cycle-metrics{grid-template-columns:repeat(2,1fr)}.field.cycle{min-width:220px}.plot.price{height:340px}.plot.equity,.plot.estimate{height:245px}.cycle-value{font-size:25px}.component{min-width:110px}.controls{gap:10px}.notice{font-size:13px}}
@media(max-width:440px){.stats{grid-template-columns:1fr}.stat{display:grid;grid-template-columns:1fr auto;gap:4px}.stat small{grid-column:1 / -1}.stat strong{margin:0}.field.asset,.field.cycle{width:100%;flex:1}.plot.price{height:320px}h1{font-size:26px}}
</style>
</head>
<body>
<main>
<header>
  <div class="eyebrow">Исследование · 29 октября 2026</div>
  <h1>Сетка по сигналам: разбор каждого цикла</h1>
  <p class="lede subtle">Где модель разрешила запуск, когда прекратила добор и как сформировался итог. Выберите цикл: графики, учёт и снимок факторов покажут один и тот же эпизод.</p>
  <div class="notice">Условный прогон по часовым свечам. Это не журнал живой торговли и не точная симуляция исполнения WEEX. Все суммы — результаты модели в USDT; время — UTC.</div>
</header>
<noscript><div class="noscript">Для выбора циклов и отображения графиков нужен JavaScript. Полный численный разбор сохранён рядом в отчёте.</div></noscript>
<section class="stats" aria-label="Итог выбранного актива">
  <div class="stat"><span class="label">Итог с оценкой закрытия остатка</span><strong id="totalNet">—</strong><small>У открытого цикла остаток сохраняется</small></div>
  <div class="stat"><span class="label">Циклы с исполненными входами</span><strong id="filledCycles">—</strong><small>Запуск сетки ещё не означает покупку</small></div>
  <div class="stat"><span class="label">Запуски без исполнений</span><strong id="emptyCycles">—</strong><small>Не считаются прибыльными сделками</small></div>
</section>
<div class="controls">
  <div class="field asset"><label for="asset">Актив</label><select id="asset"></select></div>
  <div class="field cycle"><label for="cycle">Цикл многофакторной модели</label><select id="cycle"></select></div>
  <div class="buttonrow"><button id="zoomCycle" type="button">Приблизить цикл</button><button id="showAll" type="button">Весь период</button></div>
</div>
<section class="panel" aria-label="Графики цены и решений">
  <div class="panel-title"><h2>Цена и работа сетки</h2><span class="tag">Нажмите на маркер запуска</span></div>
  <div id="priceChart" class="plot price" role="img" aria-label="Часовые свечи, запуски и завершения циклов"></div>
  <p class="chart-note">▲ запуск · × закрытый цикл · ○ открытый остаток на конце истории. Пустой треугольник — запуск без покупок. Выделена длительность выбранного цикла; точное время исполнения внутри свечи неизвестно.</p>
  <h3 style="margin-top:22px">Полный результат по времени</h3>
  <div id="equityChart" class="plot equity" role="img" aria-label="Полный net с оценкой закрытия остатка для трёх вариантов"></div>
  <p class="chart-note">Включены комиссии, funding и оценка расходов на закрытие остатка. Точки кривой известны после закрытия часа. Постоянная сетка и SMA здесь совпадают: переключений SMA не было.</p>
  <h3 style="margin-top:22px">Что говорили исторические аналоги</h3>
  <div id="forecastChart" class="plot estimate" role="img" aria-label="Средний net и двадцатый перцентиль зрелых исторических аналогов"></div>
  <p class="chart-note">Оценки сдвинуты к часу исполнения решения. Пунктир — 20-й перцентиль исходов аналогов, не доверительный интервал и не вероятность будущего убытка.</p>
</section>
<section class="panel" id="cyclePanel" aria-live="polite">
  <div class="cycle-head"><div><h2 id="cycleTitle">Цикл</h2><div id="cyclePeriod" class="subtle"></div></div><div><div id="cycleNet" class="cycle-value">—</div><div id="netLabel" class="subtle" style="font-size:12px"></div></div></div>
  <div class="cycle-metrics"><div class="metric"><span>Состояние</span><strong id="cycleStatus">—</strong></div><div class="metric"><span>Исполнено входов / тейков</span><strong id="fillCounts">—</strong></div><div class="metric"><span>Причина завершения</span><strong id="exitReason">—</strong></div><div class="metric"><span>Net по последней цене</span><strong id="mtmNet">—</strong></div></div>
  <p id="cycleExplanation" class="explain"></p>
  <h3>Из чего сложился результат</h3>
  <div id="components" class="components"></div>
  <p class="chart-note">Знаки компонентов указаны по влиянию на net. Для открытого цикла расчётное закрытие остатка показано отдельно от уже уплаченных расходов.</p>
  <div class="field event"><label for="event">Решение / момент внутри цикла</label><select id="event"></select></div>
  <div id="eventRule" class="event-rule"></div>
  <div id="timing" class="timing"></div>
  <div class="snapshot-stats"><div><span>Средний net аналогов</span><strong id="estimateMean">—</strong></div><div><span>20-й перцентиль</span><strong id="estimateQ20">—</strong></div><div><span>Отрицательных исходов</span><strong id="negativeAnalogs">—</strong></div><div><span>Признаков участвовало</span><strong id="usedFeatures">—</strong></div></div>
  <p id="contextNote" class="chart-note"></p>
  <details open><summary>Факторы, доступные в этот момент</summary><p>Показаны 27 ключевых признаков; все 93 сохранены в explanations.json. Значения относятся к указанному исходному часу. «Участвовал» означает использование в поиске похожих состояний, а не доказанное влияние на прибыль. Отсутствующие данные не заменены нулём.</p><div class="table-wrap"><table><thead><tr><th>Фактор</th><th class="num">Значение</th><th>Участвовал</th></tr></thead><tbody id="factorsBody"></tbody></table></div></details>
  <details><summary>Исторические аналоги решения</summary><p>Только исходы, успевшие завершиться к моменту решения. Окна могут пересекаться: доля отрицательных исходов не является оценкой вероятности убытка. Совпадение факторов не доказывает причинность.</p><div class="table-wrap"><table><thead><tr><th>Исходный час аналога, UTC</th><th class="num">Net фиксированного цикла, USDT</th></tr></thead><tbody id="analogsBody"></tbody></table></div></details>
  <details><summary>Исполнения и события учёта</summary><p>Порядок OHLC-точек условный. Время относится к свече или известной границе часа, а не к восстановленной биржевой сделке.</p><div class="table-wrap"><table><thead><tr><th>Время / свеча, UTC</th><th>Событие</th><th class="num">Цена</th><th class="num">Количество</th></tr></thead><tbody id="traceBody"></tbody></table></div></details>
</section>
<footer id="provenance"></footer>
</main>
<script>@@PLOTLY_JS@@</script>
<script type="application/json" id="payload">@@PAYLOAD@@</script>
<script>
'use strict';
const D=JSON.parse(document.getElementById('payload').textContent);
const $=id=>document.getElementById(id);
const nf=new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2});
const finite=v=>v!==null&&v!==undefined&&Number.isFinite(Number(v));
const num=(v,d=2)=>finite(v)?Number(v).toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d}):'нет данных';
const money=v=>finite(v)?`${Number(v)>0?'+':''}${nf.format(Number(v))}`:'нет данных';
const axis=s=>s?new Date(s).toISOString().slice(0,19):null;
const dt=s=>s?new Date(s).toISOString().slice(0,16).replace('T',' ')+' UTC':'нет данных';
const short=s=>s?new Date(s).toISOString().slice(5,16).replace('T',' '):'—';
const COLORS={model:'#7255a0',without:'#377bb4',baseline:'#7d8794',green:'#18745a',red:'#ab3340',event:'#6f7b86',band:'rgba(55,103,164,.08)'};
let selectedSymbol=Object.keys(D.symbols)[0],selectedId=null,eventIndex=0,zoomed=false,plotReady=false,viewRevision=0;
const S=()=>D.symbols[selectedSymbol];
const C=()=>S().cycles.find(c=>String(c.id)===String(selectedId))||S().cycles[0];
const E=()=>C()?.events?.[eventIndex];
function option(value,label){const el=document.createElement('option');el.value=value;el.textContent=label;return el;}
function cell(row,text,cls=''){const td=document.createElement('td');td.textContent=text;td.className=cls;row.appendChild(td);return td;}
function setSigned(id,value,suffix=''){const el=$(id);el.textContent=money(value)+suffix;el.classList.toggle('negative',finite(value)&&value<0);el.classList.toggle('positive',finite(value)&&value>0);}
function priceAt(time,terminal=false){const bars=S().bars;const target=new Date(time).getTime();const row=bars.find(b=>new Date(b.t).getTime()===target);return row?row.o:terminal?bars[bars.length-1].c:bars.reduce((a,b)=>Math.abs(new Date(b.t)-target)<Math.abs(new Date(a.t)-target)?b:a,bars[0]).c;}
function shapes(){const c=C();if(!c)return[];const a=[{type:'rect',xref:'x',yref:'paper',x0:axis(c.start),x1:axis(c.status==='open'?c.observed_end:c.end),y0:0,y1:1,fillcolor:COLORS.band,line:{width:0},layer:'below'}];const event=E();if(event?.time)a.push({type:'line',xref:'x',yref:'paper',x0:axis(event.time),x1:axis(event.time),y0:0,y1:1,line:{color:COLORS.event,width:1,dash:'dot'}});return a;}
function range(){if(!zoomed)return null;const c=C();const pad=3*3600000;return[axis(new Date(new Date(c.start).getTime()-pad)),axis(new Date(new Date(c.status==='open'?c.observed_end:c.end).getTime()+pad))];}
function layout(yTitle){return{font:{family:'Segoe UI, Arial, sans-serif',color:'#25364a',size:12},paper_bgcolor:'#fff',plot_bgcolor:'#fff',margin:{l:65,r:20,t:35,b:42},hovermode:'x unified',showlegend:true,legend:{orientation:'h',x:0,y:1.16,font:{size:11}},xaxis:{type:'date',title:{text:'Время, UTC',font:{size:11},standoff:10},tickformat:'%d.%m %H:%M',gridcolor:'#edf1f5',rangeslider:{visible:false},autorange:!zoomed,...(zoomed?{range:range()}:{}),showspikes:true,spikecolor:'#98a5b2',spikethickness:1},yaxis:{title:{text:yTitle,font:{size:11}},gridcolor:'#edf1f5',zerolinecolor:'#aab4c1',automargin:true},shapes:shapes(),uirevision:selectedSymbol+(zoomed?'-'+selectedId:'-full')+'-'+viewRevision};}
const config={responsive:true,displaylogo:false,scrollZoom:false,modeBarButtonsToRemove:['lasso2d','select2d','autoScale2d'],toImageButtonOptions:{format:'png',filename:'grid-cycle-review',scale:2}};
function markerTrace(cycles,kind){const isStart=kind==='start',closed=kind==='closed';const list=cycles.filter(c=>isStart||(closed?c.status==='closed':c.status==='open'));return{type:'scatter',mode:'markers',name:isStart?'Запуск':closed?'Закрытие':'Открытый остаток',x:list.map(c=>axis(isStart?c.start:closed?c.end:c.observed_end)),y:list.map(c=>priceAt(isStart?c.start:closed?c.end:c.observed_end,!isStart&&!closed)),customdata:list.map(c=>c.id),text:list.map(c=>`Цикл ${c.id} · ${c.entries===0?'без покупок':c.entries+' входов'} · net ${money(c.net)}`),hovertemplate:'%{text}<br>%{x}<br>Цена %{y:,.2f}<extra></extra>',marker:{size:12,symbol:list.map(c=>isStart?(c.entries===0?'triangle-up-open':'triangle-up'):closed?'x':'circle-open'),color:isStart?COLORS.green:closed?COLORS.red:COLORS.model,line:{width:2}}};}
function drawCharts(){const s=S(),bars=s.bars;const prices=[{type:'candlestick',name:'Цена',x:bars.map(b=>axis(b.t)),open:bars.map(b=>b.o),high:bars.map(b=>b.h),low:bars.map(b=>b.l),close:bars.map(b=>b.c),increasing:{line:{color:'#438c78',width:1},fillcolor:'#dcece7'},decreasing:{line:{color:'#b66c75',width:1},fillcolor:'#f1dfe2'},showlegend:false},markerTrace(s.cycles,'start'),markerTrace(s.cycles,'closed'),markerTrace(s.cycles,'open')];
const descriptors=[['multifactor','Много факторов + корреляции',COLORS.model,'solid'],['multifactor_without_correlations','Без блока корреляций',COLORS.without,'dash'],['continuous','Постоянная / SMA',COLORS.baseline,'dot']];
const curves=descriptors.map(([key,name,color,dash])=>({type:'scatter',mode:'lines',name,x:(s.curves[key]||[]).map(p=>axis(p.t)),y:(s.curves[key]||[]).map(p=>p.v),line:{color,dash,width:key==='multifactor'?2.5:1.7},hovertemplate:'%{x}<br>%{y:.3f} USDT<extra>%{fullData.name}</extra>'}));
const estimates=[['mean','Средний net аналогов',COLORS.model,'solid'],['q20','20-й перцентиль',COLORS.without,'dot']].map(([key,name,color,dash])=>({type:'scatter',mode:'lines',name,x:s.estimates.map(p=>axis(p.t)),y:s.estimates.map(p=>p[key]),connectgaps:false,line:{color,dash,width:1.8},hovertemplate:'%{x}<br>%{y:.3f} USDT<extra>%{fullData.name}</extra>'}));
const estimateLayout=layout('USDT');estimateLayout.yaxis.zeroline=true;const curveLayout=layout('Net, USDT');curveLayout.yaxis.zeroline=true;
Promise.all([Plotly.react('priceChart',prices,layout('Цена, USDT'),config),Plotly.react('equityChart',curves,curveLayout,config),Plotly.react('forecastChart',estimates,estimateLayout,config)]).then(()=>{if(!plotReady){$('priceChart').on('plotly_click',data=>{const point=data.points.find(p=>p.customdata!==undefined);if(point){selectedId=point.customdata;$('cycle').value=String(selectedId);eventIndex=0;renderCycle();drawCharts();}});plotReady=true;}});
}
function renderEvents(){const c=C();$('event').replaceChildren(...(c.events||[]).map((e,i)=>option(i,`${e.label} · ${short(e.time)}`)));if(eventIndex>=(c.events||[]).length)eventIndex=0;$('event').value=String(eventIndex);renderEvent();}
function renderEvent(){const e=E();const body=$('factorsBody'),analogs=$('analogsBody');body.replaceChildren();analogs.replaceChildren();if(!e){$('eventRule').textContent='Снимок решения отсутствует';$('timing').replaceChildren();for(const id of ['estimateMean','estimateQ20','negativeAnalogs','usedFeatures'])$(id).textContent='нет данных';$('contextNote').textContent='';return;}
$('eventRule').textContent=e.rule||'Правило не указано';$('timing').replaceChildren();for(const [label,value]of[[e.executed===false?'Контекст, не выход':'Действие',e.time],['Исходный час факторов',e.source_time],['Час завершён к',e.known_at]]){const div=document.createElement('div');div.textContent=label+': '+dt(value);$('timing').appendChild(div);}
setSigned('estimateMean',e.mean);setSigned('estimateQ20',e.q20);$('negativeAnalogs').textContent=finite(e.negative_count)&&finite(e.neighbors_count)?`${e.negative_count} из ${e.neighbors_count}`:'нет данных';$('usedFeatures').textContent=finite(e.features_used)?String(e.features_used):'нет данных';$('contextNote').textContent=e.caused_by_model?'Прогноз участвует в этом условии решения. Отрицательные исходы аналогов приведены для разбора риска; в исходном допуске q20 не служил запретом входа.':'Это контекст модели, а не причина данного действия. Завершение по сроку или правилу учёта не следует приписывать этим факторам.';
for(const f of e.features||[]){const row=document.createElement('tr');cell(row,f.label);cell(row,f.value??'нет данных','num');cell(row,f.used?'да':'нет',f.used?'yes':'muted-row');body.appendChild(row);}
for(const a of e.analogs||[]){const row=document.createElement('tr');cell(row,dt(a.time),'time');cell(row,money(a.net),'num');analogs.appendChild(row);}
if(!(e.analogs||[]).length){const row=document.createElement('tr');const td=cell(row,'Аналоги отсутствуют');td.colSpan=2;analogs.appendChild(row);}
}
function renderCycle(){const c=C();if(!c)return;$('cycleTitle').textContent='Цикл '+c.id+(c.entries===0?' · без покупок':'');$('cyclePeriod').textContent=dt(c.start)+' → '+dt(c.status==='open'?c.observed_end:c.end);setSigned('cycleNet',c.net,' USDT');$('netLabel').textContent=c.status==='open'?'С оценкой закрытия открытого остатка':'Закрытый net';$('cycleStatus').textContent=c.status==='open'?'Остаток открыт':'Завершён';$('fillCounts').textContent=c.entries+' / '+c.takes;$('exitReason').textContent=c.reason||'Не завершён';$('mtmNet').textContent=money(c.net_mtm)+' USDT';$('cycleExplanation').textContent=c.explanation||'';
$('components').replaceChildren();for(const part of c.components||[]){const div=document.createElement('div');div.className='component';const name=document.createElement('span');name.textContent=part.label;const value=document.createElement('strong');value.textContent=money(part.value);value.className=part.value<0?'negative':part.value>0?'positive':'';div.append(name,value);$('components').appendChild(div);}
$('traceBody').replaceChildren();for(const t of c.trace||[]){const row=document.createElement('tr');cell(row,dt(t.time),'time');cell(row,t.label);cell(row,finite(t.price)?num(t.price,2):'—','num');cell(row,finite(t.qty)?num(t.qty,8):'—','num');$('traceBody').appendChild(row);}if(!(c.trace||[]).length){const row=document.createElement('tr');const td=cell(row,'Исполнений не было или подробный след не сохранён.');td.colSpan=4;$('traceBody').appendChild(row);}renderEvents();}
function renderAsset(){const s=S();selectedId=s.cycles[0]?.id;eventIndex=0;zoomed=false;setSigned('totalNet',s.summary.net,' USDT');$('filledCycles').textContent=s.summary.filled_cycles;$('emptyCycles').textContent=s.summary.empty_cycles;$('cycle').replaceChildren(...s.cycles.map(c=>option(c.id,`№ ${c.id} · ${short(c.start)} · ${money(c.net)} USDT${c.status==='open'?' · открыт':c.entries===0?' · без покупок':''}`)));$('cycle').value=String(selectedId);renderCycle();drawCharts();}
$('asset').replaceChildren(...Object.keys(D.symbols).map(s=>option(s,s)));$('asset').value=selectedSymbol;$('asset').addEventListener('change',()=>{selectedSymbol=$('asset').value;renderAsset();});$('cycle').addEventListener('change',()=>{selectedId=$('cycle').value;eventIndex=0;renderCycle();drawCharts();});$('event').addEventListener('change',()=>{eventIndex=Number($('event').value);renderEvent();for(const id of ['priceChart','equityChart','forecastChart'])Plotly.relayout(id,{shapes:shapes()});});$('zoomCycle').addEventListener('click',()=>{zoomed=true;viewRevision++;drawCharts();});$('showAll').addEventListener('click',()=>{zoomed=false;viewRevision++;drawCharts();});$('provenance').textContent=D.provenance?.text||'Исходные данные и параметры приведены в сопровождающем отчёте.';renderAsset();
</script>
</body>
</html>
````

### FILE: check_ui_logic.cjs
````javascript
// Pure in-memory UI logic checks. No browser, navigation, rendering, or network.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict'), path=require('node:path');
const root=__dirname;
const template=fs.readFileSync(path.join(root,'dashboard_template.html'),'utf8');
const data=JSON.parse(fs.readFileSync(path.join(root,'dashboard_data.json'),'utf8'));
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.value='';this.events={};this.classList={toggle(){}};}
 appendChild(x){this.children.push(x);return x;}
 append(...x){this.children.push(...x);}
 replaceChildren(...x){this.children=[...x];}
 addEventListener(name,fn){this.events[name]=fn;}
 on(name,fn){this.events[name]=fn;}
}
const elements=Object.fromEntries([...template.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element(m[1])]));
elements.payload.textContent=JSON.stringify(data);
const plots={};
const document={getElementById(id){assert.ok(elements[id],`Unknown DOM id ${id}`);return elements[id];},createElement(tag){return new Element(tag);}};
const Plotly={react(id,traces,layout){plots[id]={traces,layout};return Promise.resolve();},relayout(id,change){Object.assign(plots[id].layout,change);}};
const script=[...template.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].at(-1)[1];
vm.runInNewContext(script,{document,Plotly,Intl,Date,console,Promise,Number,String,Object,Math}, {timeout:5000});
const money=v=>`${v>0?'+':''}${new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2}).format(v)}`;
(async()=>{
 await Promise.resolve();await Promise.resolve();
 let contexts=0,cycles=0;
 for(const [symbol,s] of Object.entries(data.symbols)){
  elements.asset.value=symbol;elements.asset.events.change();
  assert.equal(elements.totalNet.textContent,money(s.summary.net)+' USDT');
  assert.equal(plots.priceChart.traces[0].x.length,s.bars.length);
  assert.equal(plots.equityChart.traces.length,3);
  for(const c of s.cycles){
   elements.cycle.value=String(c.id);elements.cycle.events.change();cycles++;
   assert.equal(elements.cycleNet.textContent,money(c.net)+' USDT');
   assert.equal(elements.traceBody.children.length,c.trace.length);
   for(let j=0;j<c.events.length;j++){
    elements.event.value=String(j);elements.event.events.change();contexts++;
    const e=c.events[j];
    assert.equal(elements.estimateMean.textContent,money(e.mean));
    assert.equal(elements.factorsBody.children.length,e.features.length);
    assert.equal(elements.analogsBody.children.length,e.analogs.length||1);
    assert.equal(elements.eventRule.textContent,e.rule);
   }
  }
  elements.zoomCycle.events.click();assert.equal(plots.priceChart.layout.xaxis.autorange,false);
  elements.showAll.events.click();assert.equal(plots.priceChart.layout.xaxis.autorange,true);
 }
 await Promise.resolve();await Promise.resolve();
 elements.priceChart.events.plotly_click({points:[{customdata:3}]});
 assert.ok(elements.cycleTitle.textContent.startsWith('Цикл 3'));
 const result={status:'passed',cycles,contexts,charts:3,asset_switch:true,cycle_switch:true,event_switch:true,marker_click:true,zoom_reset:true,
  browser_render_verified:false,render_limit:'Browser URL policy rejected file://; no workaround attempted. Logic checked in memory only.'};
 fs.writeFileSync(path.join(root,'ui_checks.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
````

### FILE: plot_overview.py
````python
"""Static scientific overview, separate from the unrendered HTML dashboard."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

BASE=Path(__file__).resolve().parent
D=json.loads((BASE/'dashboard_data.json').read_text(encoding='utf-8'))
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(2,2,figsize=(15,8),gridspec_kw={'height_ratios':[1.6,1]},sharex='col')
for col,(symbol,s) in enumerate(D['symbols'].items()):
 ax,eq=axes[0,col],axes[1,col]
 bars=pd.DataFrame(s['bars']);bars.t=pd.to_datetime(bars.t,utc=True)
 # Price closes are observed at the end of each hour.
 ax.plot(bars.t+pd.Timedelta(hours=1),bars.c,color='#334c69',lw=1.2,label='Цена на закрытии часа')
 for c in s['cycles']:
  start,end=pd.Timestamp(c['start']),pd.Timestamp(c['observed_end'])
  price=float(bars.loc[bars.t.eq(start),'o'].iloc[0])
  endprice=float(bars.loc[bars.t.eq(end),'o'].iloc[0]) if c['status']=='closed' else bars.c.iloc[-1]
  ax.axvspan(start,end,color='#5967a4',alpha=.08)
  ax.scatter([start],[price],marker='^',s=65,facecolors='#167b62' if c['entries'] else 'none',edgecolors='#167b62',zorder=4)
  ax.annotate(str(c['id']),(start,price),xytext=(0,10),textcoords='offset points',ha='center',fontsize=10)
  if c['status']=='closed':
   ax.scatter([end],[endprice],marker='x',s=45,color='#bd4d5b',zorder=4)
  else:
   ax.scatter([end],[endprice],marker='o',s=45,facecolors='none',edgecolors='#bd4d5b',zorder=4)
 ax.set_title(f'{symbol} · 6 запусков / {s["summary"]["filled_cycles"]} с покупками',loc='left',fontweight='bold',pad=15)
 ax.set_ylabel('Цена, USDT');ax.grid(alpha=.15)
 for key,label,color,style in [('multifactor','Все факторы + корреляции','#7255a0','-'),('multifactor_without_correlations','Без блока корреляций','#377bb4','--'),('continuous','Постоянная / SMA','#77808b',':')]:
  p=s['curves'][key];eq.plot(pd.to_datetime([x['t'] for x in p],utc=True),[x['v'] for x in p],label=label,color=color,ls=style,lw=1.7)
 eq.axhline(0,color='#aab4c1',lw=.8);eq.grid(alpha=.15);eq.set_ylabel('Полный net, USDT')
 eq.xaxis.set_major_locator(mdates.DayLocator(interval=2));eq.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m',tz='UTC'))
 eq.set_xlabel('Октябрь 2026, UTC');eq.legend(loc='lower left',fontsize=8,frameon=False)
 eq.annotate(f'{s["summary"]["net"]:.2f}',(pd.Timestamp(s['curves']['multifactor'][-1]['t']),s['summary']['net']),xytext=(-5,8),textcoords='offset points',ha='right',color='#7255a0',fontweight='bold')
fig.suptitle('Где запускались сетки и откуда взялся итоговый минус',x=.055,y=.98,ha='left',fontsize=18,fontweight='bold')
fig.text(.055,.925,'△ / ▲ — запуск; × — завершение; ○ — остаток открыт. Линия: закрытия часов, запуск/выход: open. Номера — циклы.',fontsize=10,color='#526070')
fig.text(.055,.02,'Условный часовой прогон. Net учитывает комиссии, funding, остаток и оценку его закрытия. Это не реальные сделки WEEX.',fontsize=10,color='#526070')
fig.subplots_adjust(left=.075,right=.97,bottom=.10,top=.86,hspace=.15,wspace=.24)
fig.savefig(BASE/'cycle_overview.png',dpi=140,facecolor='white')
print(BASE/'cycle_overview.png')
````

<!-- SOURCE_SHA256
{
  "audit.py": "43e7a3ac08aea69693b7c5e420f8305dd192527bf6a120ceeb4e18e10867c6b5",
  "factor_explanations.py": "405ae3056ff292de6ea3502c8ad3875801e43d5890ac596ac02ec176dbc44a07",
  "build_dashboard.py": "59fb8cb9be95f83a94e85e04fb67ec2f84e8703f0a04f162e99332f8fca9f490",
  "dashboard_template.html": "49680f69a81a3a904d9d40ad57d3e0c17418ac979aa9b9ea48d49ce8c6c97da1",
  "check_ui_logic.cjs": "520574a7cbf1cf5f9e81929513e2934db2a18e075f7c791fe77f0f70e57ad18e",
  "plot_overview.py": "cd2c402144da78c66d45db1ccb6c36e8f58f906024d642eb2f0a82a9c5433a4c"
}
SOURCE_SHA256 -->
