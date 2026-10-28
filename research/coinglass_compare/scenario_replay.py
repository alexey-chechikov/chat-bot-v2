"""Ретроспективный прогон теневых сценариев sc-1 (services/coinglass_web/scenarios.py) на 180 днях CoinGlass 1ч —
«быстрое отсечение» из разбора GPT e53a117 §6: даёт ли поток (тейкеры) что-то сверх одной цены.

ЭТО НЕ ПРОВЕРКА ВПЕРЁД: 01.05–27.10 уже просмотрены (на них искались эпизоды и проверялось чтение линий оператора).
Пороги sc-1 — кандидат GPT §4 без подбора; здесь они не меняются. Вывод отсюда — только «стоит ли тратить время на
интеграцию с сетками», а не допуск в торговлю.

Сравнение (заранее, до прогона):
- предупреждение о затухании: ценовое (12 ч без нового экстремума) против потокового (сильный поток в сторону
  движения при ходе < 0.5 ATR за 6 ч) — доля предупреждений, после которых в 24 ч наступил слом той же структуры;
  доля «ложных пауз» (слома нет, цена ушла дальше экстремума ≥ 1 ATR); сколько сломов предупреждено за 24 ч;
  медиана опережения;
- давление во флете: направление следующего подтверждённого выхода из той же коробки при BUY/SELL_PRESSURE против
  простого RANGE.
Признак засчитывается, только если потоковый вариант лучше ценового И по доле «слом после предупреждения», И по доле
ложных пауз, в обоих символах. BTC и ETH — не независимые подтверждения.

    .venv/bin/python3 research/coinglass_compare/scenario_replay.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.coinglass_web import scenarios  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sym}_1h.csv", parse_dates=["bar_utc"]).set_index("bar_utc").sort_index()
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[df.index >= "2026-05-01"]
    for k in ("open", "high", "low", "close"):
        df[f"px_{k}"] = df[k]
    return df


def main() -> None:
    res = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        df = load(sym)
        recs, _m = scenarios.replay(df, sym)
        ev = scenarios.evaluate(recs)
        res[sym] = ev
        print(f"\n=== {sym}: {df.index[0]:%d.%m} – {df.index[-1]:%d.%m}, часов {ev['hours']}, сломов структуры "
              f"{ev['breaks']}, выходов подтверждено {ev['breakouts']['confirmed']}, ложных {ev['breakouts']['false']}")
        for v in ("price", "flow"):
            s = ev[f"stall_{v}"]
            w = s["warnings"] or 1
            print(f"  затухание [{v}]: предупреждений {s['warnings']}, слом в 24 ч {s['break_within_24h']} "
                  f"({s['break_within_24h'] / w:.0%}), ложных пауз ≥1 ATR {s['false_pause_1atr']} "
                  f"({s['false_pause_1atr'] / w:.0%}), сломов с предупреждением {s['breaks_warned_24h']} из "
                  f"{ev['breaks']}, опережение (медиана) {s['lead_h_median']} ч")
            print(f"  состояния [{v}]: {ev[f'states_{v}']}")
        for s, k in ev["range_pressure_next_breakout"].items():
            print(f"  {s}: часов {k['hours']}, следующий выход вверх {k['up_next'] / k['hours']:.0%}")
        print("  по коробкам-флетам, без последних 6 ч перед выходом:",
              ", ".join(f"{g} {k['up_next']}/{k['boxes']} вверх" for g, k in ev["boxes_pressure_lead6h"].items()))
        a = ev["after_breakout_24h_atr"]
        print(f"  флет до выхода (медиана) {ev['flat_hours_to_breakout_median']} ч; после выхода 24 ч: по ходу "
              f"{a['with_median']:.2f} ATR, против {a['against_median']:.2f} ATR (n {a['n']})")
    out = ROOT / "research" / "coinglass_compare" / "scenario_replay_result.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("\n", out)


if __name__ == "__main__":
    main()
