"""Живая лонг-сетка BTC (шаг 0.6, цель 1.4, 0.0012 BTC, до 50 лотов, потолок $12k, мейкер 0.016%, без закрытия по режиму)
с запретом НОВЫХ входов по состоянию системы оператора. Записано до прогона (08.11.2026):
  всегда — как сейчас;
  G1 — новые лонги сетки только когда система не в шорте (ни под синей, ни под жёлтой);
  G2 — только когда система в лонге над синей.
Состояние системы — по последнему закрытому часу (services/btc_signals/engine.simulate), на минуты переносится без
заглядывания. Сетка — research/weex/fast_grid.run на frozen-минутках Binance (спот) 2018-01 … последняя закрытая минута.
Итог — полный капитал (закрыто − комиссии + мешок), фандинг не учитывается. Половины: граница 2022-06-01, вторая —
непрерывно (с мешком первой). Вывод «гейт лучше» — только если лучше в обеих половинах и просадка не глубже.
Это снятие входов без закрытия — по CLAUDE.md отдельная непроверенная стратегия; здесь первая оценка, не решение."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "weex"))
sys.path.insert(0, str(Path(__file__).parent))
import fast_grid as fg  # noqa: E402
import plus as pl  # noqa: E402
import state_card as sc  # noqa: E402
from services.btc_signals import engine as en  # noqa: E402

FROZEN = ROOT / "backtests" / "frozen"
CUT = int(pd.Timestamp("2022-06-01", tz="UTC").timestamp())


def minutes(t0):
    parts = [pd.read_csv(FROZEN / n) for n in ("BTCUSDT_1m_2017_2024.csv", "BTCUSDT_1m_2y.csv")]
    m = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
    m = m.iloc[:-1]
    ts = (m["ts"].to_numpy(np.int64) // 1000)
    k = ts >= t0
    return ts[k], *(m[c].to_numpy(float)[k] for c in ("open", "high", "low", "close"))


def system_side(a):
    ev, _ = en.simulate(a, pl.layer(a))
    S = np.zeros(len(a["t"]), np.int8)
    cur, last = 0, int(a["i0"])
    for e in ev:
        S[last:e["i"]] = cur
        cur = e["side"] if e["kind"] == "вход" else (0 if e["kind"] == "выход" else cur)
        last = e["i"]
    S[last:] = cur
    return S


def main():
    a, _, _ = sc.load_coin("BTC")
    S = system_side(a)
    t = a["t"]
    data = minutes(int(t[a["i0"]]))
    ts = data[0]
    k = np.searchsorted(t, ts, side="right") - 1
    side = np.where(k >= 0, S[np.clip(k, 0, None)], 0)
    print(f"минут {len(ts)}, {pd.Timestamp(ts[0], unit='s'):%Y-%m-%d} – {pd.Timestamp(ts[-1], unit='s'):%Y-%m-%d %H:%M}; доля времени: лонг {np.mean(side == 1):.2f}, шорт {np.mean(side == -1):.2f}, вне {np.mean(side == 0):.2f}", flush=True)
    V = {"всегда": None, "G1 не в шорте": {"LONG": side >= 0}, "G2 только в лонге": {"LONG": side == 1}}
    rows = []
    for lab, gate in V.items():
        t0 = time.time()
        r = fg.run(data, sides=("LONG",), step=0.6, target=1.4, order_qty=0.0012, cap_usd=12000.0, max_orders=50, cut_ts=CUT, gate=gate)
        mon = pd.Series(dict(r["по месяцам"]))
        yrs = mon.groupby(mon.index.str[:4]).sum().round(0).astype(int).to_dict()
        rows.append({"вариант": lab, "итог": round(r["итог"]), "закрыто": round(r["закрыто"] - r["комиссии"]), "мешок": round(r["мешок"]), "просадка": round(r["просадка капитала"]),
                     "худший мешок": round(r["худший мешок"]), "п1": round(r["1-я часть непрерывно"]), "п2 непрерывно": round(r["2-я часть непрерывно"]), "тейков": r["тейков"], "годы": yrs})
        print(rows[-1], f"{time.time() - t0:.0f} с", flush=True)
    print(pd.DataFrame(rows).drop(columns="годы").to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
