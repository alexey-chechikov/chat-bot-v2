"""Шаг 4 (14.11): пауза ВХОДОВ сеток, пока система в шорте (оператор 14.11 снял входы всем лонг-сеткам руками —
«новые лонги не открывай пока»). Тейки работают всегда; пауза только не даёт ставить новые входы.

ПРАВИЛА (до прогона):
- Сетки, данные, механика, общий потолок — как grid_sim2.py (BTC 4 сетки + ETH, $15 000, мейкер, фандинг).
- «Пауза по системе»: входы всех сеток запрещены с закрытия часа входа системы в шорт (под синей / под жёлтой) до
  закрытия часа её выхода. Пока сетка пуста, опорная цена тянется за максимумом и в паузе (как живой движок).
- Контроль: та же маска пауз, круговой сдвиг на случайное число часов (≥30 сут), 100 сдвигов (две части по 50,
  --part=0/1, seed 20261114+part): то же время в паузе и та же длина пауз, случайные даты. Ранг (k+1)/(n+1).
- Метрики: итог, просадка, 2-я половина, 3 года, 2 года; шанс ликвидации за год при $3 200 (сетки ×1, без страховки и
  со страховкой «от всего» k=1 — база от позиции сеток этого прогона), валовый номинал, MM 0.5%.

    .venv/bin/python3 research/grid_hedge_20261114/grid_pause.py --real          # без паузы (сверка с grid_sim2) и пауза
    .venv/bin/python3 research/grid_hedge_20261114/grid_pause.py --part=0        # 50 сдвигов
    .venv/bin/python3 research/grid_hedge_20261114/grid_pause.py --report
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import grid_sim2 as gs2  # noqa: E402

MAKER, SHARED, SC, MM, H = 0.00016, 15000.0, 0.00068, 0.005, 365 * 24
N_PER_PART = 50


def load():
    b, e = gs2.load("BTCUSDT"), gs2.load("ETHUSDT")
    d = b.join(e, how="inner", lsuffix="_b", rsuffix="_e")
    last_full = (int(d.index[-1]) + 60) // 3600 * 3600
    d = d[d.index < last_full]
    t = d.index.to_numpy(np.int64)
    px = {s: [d[f"{k}_{s}"].to_numpy(float).tolist() for k in ("open", "high", "low", "close")] for s in ("b", "e")}
    F = {"b": gs2.funding("BTCUSDT", t), "e": gs2.funding("ETHUSDT", t)}
    hr = (t // 3600).tolist()
    return t, px, F, hr, float(d["close_e"].iloc[-1])


def simulate(data, pause_h: np.ndarray | None):
    """pause_h — по часам (индекс от первого часа) True = входы запрещены. → почасовые eq (BTC+ETH), qb, qe, cb, ce."""
    t, px, F, hr, eth_px = data
    n = len(t)
    h0 = hr[0]
    specs = [("b", 0.6, 1.4, 82.0, 12000.0, 50), ("b", 0.1, 0.34, 41.0, 4462.0, 61), ("b", 0.1, 0.49, 41.0, 4361.0, 59),
             ("b", 0.1, 0.89, 41.0, 3709.0, 56), ("e", 0.6, 1.4, gs2.ETH_USD, 2500.0, 50)]
    G = [{"s": s, "g": st / 100, "tp": tg / 100, "usd": u, "cap": cap, "mx": mx, "lots": [], "Q": 0.0, "QE": 0.0, "real": 0.0,
          "fee": 0.0, "ref": None} for s, st, tg, u, cap, mx in specs]
    by = {s: [g for g in G if g["s"] == s] for s in ("b", "e")}
    fund = {"b": 0.0, "e": 0.0}
    out = {k: [] for k in ("eq", "qb", "qe", "cb", "ce")}
    tot_qe = 0.0
    prev = {"b": None, "e": None}
    for i in range(n):
        allow = pause_h is None or not pause_h[hr[i] - h0]
        for s in ("b", "e"):
            o, h, l, c = (px[s][k][i] for k in range(4))
            if i in F[s]:
                fund[s] += sum(g["Q"] for g in by[s]) * o * F[s][i]
            up = c >= o
            for p in (o, l if up else h, h if up else l, c):
                pp, prev[s] = prev[s], p
                for g in by[s]:
                    lots = g["lots"]
                    while lots and p >= lots[-1][1]:
                        en, tp, q = lots.pop()
                        g["real"] += q * (tp - en)
                        g["fee"] += q * tp * MAKER
                        g["Q"] -= q
                        g["QE"] -= q * en
                        tot_qe -= q * en
                    if not lots:
                        tot_qe -= g["QE"]
                        g["Q"] = g["QE"] = 0.0
                    if lots:
                        g["ref"] = lots[-1][0]
                    elif g["ref"] is None:
                        g["ref"] = p
                    else:
                        g["ref"] = max(g["ref"], p)
                    if not allow:
                        continue
                    lvl = g["ref"] * (1 - g["g"])
                    if p <= lvl and len(lots) < g["mx"]:
                        px_in = lvl if (pp is not None and pp > lvl) else p  # разбор ead2ca4: лимитка входа исполняется по своему уровню, если цена прошла его сверху; ниже уже — по цене точки
                        usd = g["usd"]
                        if max(g["QE"], g["Q"] * p) + usd <= g["cap"] and tot_qe + usd <= SHARED:
                            q = usd / px_in
                            lots.append([px_in, px_in * (1 + g["tp"]), q])
                            g["fee"] += usd * MAKER
                            g["Q"] += q
                            g["QE"] += usd
                            tot_qe += usd
        if i + 1 == n or hr[i + 1] != hr[i]:
            eq = 0.0
            for s in ("b", "e"):
                c = px[s][3][i]
                eq += sum(g["real"] - g["fee"] + g["Q"] * c - g["QE"] for g in by[s]) - fund[s]
            out["eq"].append(eq)
            out["qb"].append(sum(g["Q"] for g in by["b"]))
            out["qe"].append(sum(g["Q"] for g in by["e"]))
            out["cb"].append(px["b"][3][i])
            out["ce"].append(px["e"][3][i])
    return {k: np.array(v) for k, v in out.items()}


def hours_index(data):
    t, _, _, hr, _ = data
    hrs = np.array(sorted(set(hr)), dtype=np.int64)
    return hrs * 3600 + 3600, hrs[-1] - hrs[0] + 1, int(hrs[0])     # метка — конец часа (разбор ead2ca4)


class _Rows:
    """Событие с меткой t (закрытие часа) → строка часа, закончившегося не позже t; пропуск ряда > 3 ч — None
    (разбор ead2ca4: точное равенство меток теряло события на пропусках, метка начала часа брала будущий час)."""

    def __init__(self, T):
        self.T = T

    def get(self, t, default=None):
        i = int(np.searchsorted(self.T, int(t), side="right")) - 1
        return i if i >= 0 and int(t) - int(self.T[i]) <= 3 * 3600 else default


def short_trades(T):
    pos = _Rows(T)
    ev = json.load(open(HERE / "ev.json", encoding="utf-8"))
    out, cur = [], None
    for e in ev:
        if e.get("side") != -1 or e.get("tag") not in ("под синей", "под жёлтой"):
            continue
        i = pos.get(int(e["t"]))
        if i is None:
            continue
        if e["kind"] == "вход":
            cur = [i, None, None]
        elif e["kind"] == "добор" and cur:
            cur[1] = i
        elif e["kind"] == "выход" and cur:
            cur[2] = i
            out.append(tuple(cur))
            cur = None
    if cur:
        out.append((cur[0], cur[1], len(T) - 1))
    return out


def pause_mask(T, h0, span, trades):
    m = np.zeros(span, bool)
    hidx = (T // 3600 - h0).astype(int)
    for a, _, x in trades:
        m[hidx[a]:hidx[x]] = True
    return m


def metrics(r, T, trades, dep=3200.0):
    n = len(T)
    EQ, CB = r["eq"], r["cb"]
    base = r["qb"] * CB + r["qe"] * r["ce"]
    hq = np.zeros(n)
    cost = np.zeros(n)
    for a, b, x in trades:
        for i0 in (a, b):
            if i0 is None:
                continue
            q = 0.5 * base[a] / CB[i0]
            hq[i0:x] += q
            cost[i0] += q * CB[i0] * SC
            cost[x] += q * CB[x] * SC
    step = np.zeros(n)
    step[1:] = -hq[:-1] * (CB[1:] - CB[:-1])
    hedged = EQ + np.cumsum(step - cost)
    mid, y3, y2 = n // 2, int(np.searchsorted(T, T[-1] - 3 * 365 * 86400)), int(np.searchsorted(T, T[-1] - 2 * 365 * 86400))

    def dd(x):
        return float(np.min(x - np.maximum.accumulate(x)))

    def liq(tot, gross, lo=0):
        hits = cnt = 0
        for st in range(lo, n - H, 24):
            cnt += 1
            w = tot[st:st + H] - tot[st] + dep
            hits += bool(np.any(w <= MM * gross[st:st + H]))
        return hits / max(cnt, 1)
    g0 = r["qb"] * CB + r["qe"] * r["ce"]
    lo3 = int(np.searchsorted(T, T[-1] - 4 * 365 * 86400))
    return {"итог": EQ[-1], "просадка": dd(EQ), "2-я половина": EQ[-1] - EQ[mid], "3 года": EQ[-1] - EQ[y3], "2 года": EQ[-1] - EQ[y2],
            "просадка 3 года": dd(EQ[y3:]), "ликв. $3 200": liq(EQ, g0), "ликв. $3 200 с 11.2022": liq(EQ, g0, lo3),
            "со страх.: итог": hedged[-1], "со страх.: просадка": dd(hedged), "со страх.: 2 года": hedged[-1] - hedged[y2],
            "со страх.: ликв. $3 200": liq(hedged, g0 + hq * CB), "со страх.: ликв. с 11.2022": liq(hedged, g0 + hq * CB, lo3)}


def main():
    arg = {a.split("=")[0]: (a.split("=")[1] if "=" in a else True) for a in sys.argv[1:]}
    if "--report" in arg:
        return report()
    data = load()
    T, span, h0 = hours_index(data)
    tr = short_trades(T)
    mask = pause_mask(T, h0, span, tr)
    print(f"часов {len(T)}, шортов системы {len(tr)}, в паузе {mask.mean():.1%} часов", flush=True)
    res = {}
    t0 = time.time()
    if "--real" in arg:
        for name, m in (("без паузы", None), ("пауза по системе", mask)):
            r = simulate(data, m)
            res[name] = metrics(r, T, tr)
            print(name, {k: round(v, 3) for k, v in res[name].items()}, f"{time.time() - t0:.0f} с", flush=True)
        out = HERE / "grid_pause_real.json"
    else:
        part = int(arg.get("--part", 0))
        rng = np.random.default_rng(20261114 + part)
        shifts = rng.integers(30 * 24, span - 30 * 24, N_PER_PART)
        for j, sh in enumerate(shifts):
            r = simulate(data, np.roll(mask, int(sh)))
            res[f"сдвиг {int(sh)}"] = metrics(r, T, tr)
            if j % 5 == 0:
                print(f"часть {part}: {j + 1}/{N_PER_PART}, {time.time() - t0:.0f} с", flush=True)
        out = HERE / f"grid_pause_ctrl{part}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("записано", out.name)


def report():
    real = json.loads((HERE / "grid_pause_real.json").read_text())
    ctrl = []
    for p in sorted(HERE.glob("grid_pause_ctrl*.json")):
        ctrl += list(json.loads(p.read_text()).values())
    base, pz = real["без паузы"], real["пауза по системе"]
    print(f"случайных пауз (та же маска, сдвиг): {len(ctrl)}")
    print("метрика | без паузы | пауза по системе | случайные: медиана | ранг (доля случайных не хуже)")
    lower_better = {"ликв. $3 200", "ликв. $3 200 с 11.2022", "со страх.: ликв. $3 200", "со страх.: ликв. с 11.2022"}
    for k in base:
        arr = np.array([c[k] for c in ctrl])
        v = pz[k]
        better = (arr <= v) if k in lower_better else (arr >= v)
        rank = (better.sum() + 1) / (len(arr) + 1)
        f = (lambda x: f"{x * 100:.0f}%") if "ликв" in k else (lambda x: f"{x:+,.0f}")
        print(f"{k:28s} | {f(base[k]):>9s} | {f(v):>9s} | {f(float(np.median(arr))):>9s} | {rank:.3f}")


if __name__ == "__main__":
    main()
