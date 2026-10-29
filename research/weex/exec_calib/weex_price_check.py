"""Лишние 17–19% тейков у B49/B89 — от разницы цен площадок? (29.10, после calib_1s.py: секунды Binance и задержка
цикла разрыв не объясняют; подсказка — лишние тейки у лотов, державшихся больше часа).

ПРАВИЛА (записаны ДО прогона 29.10):
- Движок — calib_1s.run(..., lat=None): правила week_reconcile.sim() точка в точку на секундах (проверено в calib_1s).
- Цена — сделки WEEX BTCUSDT из нашей записи state/weex_book/BTCUSDT_<день>_trades.csv (столбцы T мс, p), только чтение:
  секунда → O/H/L/C по сделкам этой секунды, секунды без сделок пропускаются. Записи 18.10 нет — участок
  W0 (18.10 16:16) … 19.10 00:00 UTC идёт на секундах Binance (как S1), дальше — WEEX («гибрид»).
- Окно, снимок старта и расписание — как в calib_1s (W0 … 28.10 14:40 UTC).
- Сравнение с биржей (week_reconcile.live) по тейкам, входам, закрыто $, лотам на конце; рядом — S1 (Binance на всём окне).
- Справка: базис WEEX − Binance по минутам (медиана, 5–95%), и сколько минут, где размах WEEX больше размаха Binance.
Ничего не подгоняется.

    .venv/bin/python3 research/weex/exec_calib/weex_price_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import calib_1s as C  # noqa: E402
import week_reconcile as wr  # noqa: E402

BOOK = Path("/Users/alexeychechikov/code/bot7/state/weex_book")
CUT = wr.ts("2026-10-19T00:00:00+00:00")
OUT = HERE / "weex_price_check_result.json"


def weex_seconds() -> pd.DataFrame:
    frames = []
    for d in range(19, 29):
        f = BOOK / f"BTCUSDT_202610{d:02d}_trades.csv"
        x = pd.read_csv(f, usecols=["T", "p"])
        frames.append(x)
    x = pd.concat(frames, ignore_index=True).sort_values("T", kind="stable")
    x["t"] = x["T"] // 1000
    g = x.groupby("t")["p"].agg(open="first", high="max", low="min", close="last").reset_index()
    return g[(g["t"] >= CUT) & (g["t"] < C.END)]


def main() -> None:
    files = [{"day": d, "file": f"BTCUSDT-1s-{d}.zip"} for d in C.DAYS]
    bn, _meta = C.load_1s(files)
    wx = weex_seconds()
    head = bn[(bn["t"] >= wr.W0) & (bn["t"] < CUT)]
    hyb = pd.concat([head, wx], ignore_index=True)
    tms_h, pts_h = C.rows_1s(hyb, wr.W0, C.END)
    tms_b, pts_b = C.rows_1s(bn, wr.W0, C.END)
    snap = json.load(open(wr.SNAP))
    pe = float(bn[bn["t"] < C.END]["close"].iloc[-1])
    res = {"weex_seconds": int(len(wx)), "binance_seconds_head": int(len(head)), "grids": {}}
    print(f"секунд WEEX {len(wx)}, секунд Binance до 19.10 {len(head)}")
    print(f"{'сетка':6s} | {'биржа':>14s} | {'S1 Binance':>14s} | {'гибрид WEEX':>14s}   (тейки / входы / закрыто $ / лотов)")
    for name in C.GRIDS:
        g = snap["grids"][name]
        cfg = g["config"]
        lv = wr.live(name, g, C.END, pe)
        s1 = C.run(name, g, cfg, tms_b, pts_b, None)
        hy = C.run(name, g, cfg, tms_h, pts_h, None)
        res["grids"][name] = {k: {"tk": x["tk"], "ent": x["ent"], "real": round(x["real"], 2), "lots": x["lots"]}
                              for k, x in (("live", lv), ("s1", s1), ("hybrid", hy))}
        f = lambda x: f"{x['tk']:4d}/{x['ent']:4d}/{x['real']:+7.2f}/{x['lots']:3d}"   # noqa: E731
        print(f"{name:6s} | {f(lv)} | {f(s1)} | {f(hy)}")
    # базис и размах по минутам на участке WEEX
    wm = wx.assign(m=wx["t"] // 60).groupby("m").agg(c=("close", "last"), h=("high", "max"), l=("low", "min"))
    b2 = bn[(bn["t"] >= CUT) & (bn["t"] < C.END)]
    bm = b2.assign(m=b2["t"] // 60).groupby("m").agg(c=("close", "last"), h=("high", "max"), l=("low", "min"))
    j = wm.join(bm, lsuffix="_w", rsuffix="_b", how="inner")
    basis = (j["c_w"] / j["c_b"] - 1) * 1e4
    wider = float(((j["h_w"] - j["l_w"]) > (j["h_b"] - j["l_b"])).mean())
    res["basis_bp"] = {"median": float(basis.median()), "p5": float(basis.quantile(0.05)), "p95": float(basis.quantile(0.95))}
    res["minutes"] = int(len(j))
    res["weex_range_wider_share"] = wider
    print(f"базис WEEX−Binance, б.п.: медиана {basis.median():+.1f}, 5–95% {basis.quantile(0.05):+.1f}…{basis.quantile(0.95):+.1f}; "
          f"минут {len(j)}, размах WEEX шире Binance в {wider:.0%} минут")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
