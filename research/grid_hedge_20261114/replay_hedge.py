"""Связка «движок → исполнитель → биржа» в режиме страховки (14.11): история последних 2 лет через services/sigexec
(sizing="hedge", имитатор биржи, рыночные вход и выход, аварийный стоп 12%) против расчёта исследования
(overlay2.py: «страховка от всего», k=1) на тех же событиях системы.

Позиция сеток в $ — из grid_hourly2.npz (grid_sim2.py: BTC + ETH, общий потолок $15 000): на момент сигнала берётся
час, закончившийся к этому моменту. Расчёт «как в исследовании» по каждой сделке: вход k·0.5·E/цена входа по цене
события, добор k·0.5·E/уровень добора по цене события добора, выход по цене события выхода, издержка 0.068%/сторону;
E — позиция сеток на входе (у исполнителя размер фиксируется на входе; в overlay2 добор брал позицию на часе добора).

    .venv/bin/python3 research/grid_hedge_20261114/replay_hedge.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from services.btc_signals import engine as en  # noqa: E402
from services.sigexec import lines  # noqa: E402
from services.sigexec.replay import replay  # noqa: E402

FROZEN = Path("/Users/alexeychechikov/code/bot7/backtests/frozen/BTCUSDT_1m_2y.csv")
NPZ = next(p for p in (HERE / "grid_hourly2.npz", Path("/Users/alexeychechikov/code/bot7/research/grid_hedge_20261114/grid_hourly2.npz"))
           if p.exists())
K = 1.0
SC = 0.00068

z = np.load(NPZ)
TZ, EXPO = z["t"], z["qb"] * z["cb"] + z["qe"] * z["ce"]


def exposure_at(ts: float) -> float:
    i = int(np.searchsorted(TZ, ts - 3600, side="right")) - 1      # час [TZ[i], TZ[i]+3600) закончился к ts
    return float(EXPO[max(i, 0)])


def main():
    d = pd.read_csv(FROZEN, usecols=["ts", "open", "high", "low", "close"])
    d = d.iloc[: len(d) // 60 * 60]
    t, o, h, l, c = lines.hours_from_minutes(d["ts"].to_numpy() // 1000, d["open"], d["high"], d["low"], d["close"])
    t_end = min(int(t[-1]), int(TZ[-1]) + 3600)
    keep = t <= t_end
    t, o, h, l, c = (np.asarray(x)[keep] for x in (t, o, h, l, c))
    t_from = int(t[-1]) - 730 * 86400
    with tempfile.TemporaryDirectory() as tmp:
        R = replay(t, o, h, l, c, t_from, Path(tmp) / "rp", slots=("system",), exposure_at=exposure_at, hedge_k=K)
    trades = {x["entry_t"]: x for x in R["trades"]}
    a, lay = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    ev, _ = en.simulate(a, lay)
    rows, cur = [], None
    for e in ev:
        if e["side"] != -1:
            continue
        if e["kind"] == "вход":
            cur = {"entry_t": int(e["pos"]["entry_t"]), "tag": e["tag"], "px": e["px"], "add": None, "add_lv": e["pos"].get("add_lv")}
        elif e["kind"] == "добор" and cur:
            cur["add"] = e["px"]
        elif e["kind"] == "выход" and cur:
            cur["exit"] = e["px"]
            if cur["entry_t"] >= t_from and e["t"] < a["t"][-1]:
                rows.append(cur)
            cur = None
    print(f"окно {pd.to_datetime(t_from, unit='s'):%Y-%m-%d} … {pd.to_datetime(int(t[-1]), unit='s'):%Y-%m-%d}; шортов системы {len(rows)}, "
          f"сделок исполнителя {len(trades)}; позиция сеток из {NPZ.name}")
    out = []
    for r in rows:
        E = exposure_at(r["entry_t"])
        legs = [(K * 0.5 * E / r["px"], r["px"])]
        if r["add"] is not None:
            legs.append((K * 0.5 * E / r["add_lv"], r["add"]))
        ref = sum(q * (p - r["exit"]) - q * (p + r["exit"]) * SC for q, p in legs)
        x = trades.get(r["entry_t"])
        out.append({"вход": pd.to_datetime(r["entry_t"], unit="s").strftime("%Y-%m-%d %H:%M"), "тег": r["tag"], "позиция сеток $": round(E),
                    "добор": r["add"] is not None, "исследование $": round(ref, 2), "исполнитель $": round(x["pnl_usd"], 2) if x else None,
                    "почему вышел": (x or {}).get("why", "нет сделки")[:40]})
    df = pd.DataFrame(out)
    pd.set_option("display.width", 220)
    print(df.to_string(index=False))
    m = df.dropna(subset=["исполнитель $"])
    diff = m["исполнитель $"] - m["исследование $"]
    print(f"\nсовпало сделок {len(m)} из {len(df)}; сумма: исполнитель {m['исполнитель $'].sum():+,.0f}$, исследование "
          f"{m['исследование $'].sum():+,.0f}$; разница по сделке: медиана {diff.median():+.2f}$, худшая {diff.abs().max():.2f}$; "
          f"корреляция {np.corrcoef(m['исполнитель $'], m['исследование $'])[0, 1]:.3f}")
    big = m[diff.abs() > 25]
    if len(big):
        print("расхождения > $25:\n" + big.to_string(index=False))


if __name__ == "__main__":
    main()
