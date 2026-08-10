#!/usr/bin/env python3
"""Здоровье грид-ботов: то, чего не видно в интерфейсе GinArea.

Три проверки по каждому живому боту:

1. ЗАКЛИНИВАНИЕ — позиция упёрлась в потолок книги и не двигается, оборот
   не растёт. Замер 10.08.2026: у заклинивших конфигов просадка была в 27 раз
   больше, чем у работающих, при вдвое меньшем обороте. В интерфейсе видна
   позиция «сейчас», но не видно, что она не меняется третьи сутки.

2. МАРЖА НИЖЕ ЗАКОНА — реальная прибыль с оборота против формулы
   маржа% = 0.435 x таргет - 0.0335 (14 бэктестов, 2 окна, ошибка 2.3%;
   для DYNAMIC GRID: 0.513 x таргет - 0.0442). Отставание означает, что
   ордера закрываются НЕ по таргету: проскальзывание, принудительные
   закрытия, харвестер в минус.

3. ЗАПОЛНЕНИЕ КНИГИ — сколько процентов ёмкости занято прямо сейчас.

Запуск:  .venv/bin/python3 tools/grid_health.py [--days 14] [--json]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "ginarea_live" / "snapshots.csv"
PAR = ROOT / "ginarea_live" / "params.csv"
ALIASES = ROOT / "ginarea_tracker" / "bot_aliases.json"

STATUS_ACTIVE = 2
# закон маржи, замер 2026-08-10
LAW_SLOPE, LAW_CONST = 0.4348, 0.0335              # INDICATOR GRID
LAW_SLOPE_DYN, LAW_CONST_DYN = 0.5130, 0.0442      # DYNAMIC GRID

JAM_FILL_PCT = 85.0     # книга считается упёртой при заполнении выше
JAM_HOURS = 24.0        # ...и неподвижности дольше
MARGIN_TOLERANCE = 0.70  # маржа ниже 70% от закона = флаг


def tail_csv(path: Path, mb: int = 120) -> pd.DataFrame:
    """Читает хвост большого CSV, не поднимая весь файл в память."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        header = fh.readline().decode("utf-8", "replace")
        start = max(fh.tell(), size - mb * 1024 * 1024)
        fh.seek(start)
        if start > 0:
            fh.readline()          # выбрасываем обрезанную строку
        body = fh.read().decode("utf-8", "replace")
    return pd.read_csv(io.StringIO(header + body), on_bad_lines="skip",
                       low_memory=False)


def load_params() -> dict:
    p = pd.read_csv(PAR, usecols=["ts_utc", "bot_id", "bot_name", "strategy_id",
                                  "raw_params_json"],
                    on_bad_lines="skip", low_memory=False)
    p["ts"] = pd.to_datetime(p["ts_utc"], utc=True, errors="coerce")
    p = p.dropna(subset=["ts", "raw_params_json"]).sort_values("ts")
    out = {}
    for bid, g in p.groupby("bot_id"):
        try:
            d = json.loads(g["raw_params_json"].iloc[-1])
        except (ValueError, TypeError):
            continue
        gap, q = d.get("gap") or {}, d.get("q") or {}
        # strategy_id в params.csv пустой на всю историю. Различаем по сырым
        # полям: у DYNAMIC GRID есть смещение границ (so/ioo) и border.from/to,
        # у INDICATOR GRID — блок условия входа in.start.cnds.
        strategy = ("DYNAMIC" if (d.get("so") is not None
                                  or d.get("ioo") is not None)
                    else "INDICATOR")
        out[bid] = {
            "name": (str(g["bot_name"].dropna().iloc[-1])
                     if g["bot_name"].notna().any() else str(int(bid))),
            "strategy": strategy,
            "target": gap.get("tog"),
            "gs": d.get("gs"),
            "max_orders": d.get("maxOp"),
            "max_q": q.get("maxQ"),
            "obap": bool(d.get("obap")),
            "otc": bool(((d.get("in") or {}).get("otc"))),
        }
    return out


def law_margin(target: float, dynamic: bool) -> float:
    if target is None:
        return float("nan")
    if dynamic:
        return LAW_SLOPE_DYN * float(target) - LAW_CONST_DYN
    return LAW_SLOPE * float(target) - LAW_CONST


def analyse(days: int) -> list[dict]:
    meta = load_params()
    s = tail_csv(SNAP)
    s["ts"] = pd.to_datetime(s["ts_utc"], utc=True, errors="coerce")
    for c in ("status", "position", "average_price", "profit", "trade_volume"):
        s[c] = pd.to_numeric(s[c], errors="coerce")
    s = s.dropna(subset=["ts", "bot_id", "trade_volume", "profit"])
    cutoff = s["ts"].max() - pd.Timedelta(days=days)
    s = s[s["ts"] >= cutoff]
    now = s["ts"].max()

    rows = []
    for bid, g in s.groupby("bot_id"):
        g = g.sort_values("ts")
        last = g.iloc[-1]
        m = meta.get(bid, {})
        notional = g["position"].abs() * g["average_price"].fillna(0)
        cur = float(notional.iloc[-1])
        peak = float(notional.max())

        # часы с последнего роста оборота
        grew = g.loc[g["trade_volume"].diff().fillna(0) > 0, "ts"]
        idle_h = ((now - grew.iloc[-1]).total_seconds() / 3600
                  if len(grew) else float("inf"))

        # часы, в течение которых позиция стоит у потолка
        fill = (notional / peak * 100) if peak > 0 else notional * 0
        at_top = fill >= JAM_FILL_PCT
        stuck_h = 0.0
        if bool(at_top.iloc[-1]):
            block = (~at_top).iloc[::-1].idxmax() if (~at_top).any() else None
            since = g.loc[block, "ts"] if block is not None else g["ts"].iloc[0]
            stuck_h = (now - since).total_seconds() / 3600

        dv = float(g["trade_volume"].iloc[-1] - g["trade_volume"].iloc[0])
        dp = float(g["profit"].iloc[-1] - g["profit"].iloc[0])
        marg = dp / dv * 100 if dv > 1000 else float("nan")
        is_dyn = str(m.get("strategy") or "").upper().startswith("DYN")
        law = law_margin(m.get("target"), is_dyn)
        ratio = marg / law if law and law == law and marg == marg else float("nan")

        flags = []
        if stuck_h >= JAM_HOURS and idle_h >= JAM_HOURS:
            flags.append(f"ЗАКЛИНИЛА {stuck_h:.0f}ч")
        if ratio == ratio and ratio < MARGIN_TOLERANCE:
            flags.append(f"маржа {ratio*100:.0f}% от закона")
        # остановленный бот — новость только если он в этом окне ещё торговал;
        # архив BitMEX после переезда на OKX стоит навсегда и флага не требует
        if int(last["status"]) != STATUS_ACTIVE and dv > 1000:
            flags.append(f"остановлен, но торговал в окне "
                         f"(статус {int(last['status'])})")

        rows.append({
            "bot_id": str(int(bid)),
            "name": m.get("name", str(int(bid)))[:22],
            "status": int(last["status"]),
            "target": m.get("target"),
            "gs": m.get("gs"),
            "max_orders": m.get("max_orders"),
            "obap": m.get("obap"),
            "otc": m.get("otc"),
            "position_usd": cur,
            "peak_usd": peak,
            "fill_pct": (cur / peak * 100) if peak > 0 else 0.0,
            "stuck_hours": stuck_h,
            "idle_hours": idle_h,
            "volume": dv,
            "profit": dp,
            "margin_pct": marg,
            "law_pct": law,
            "margin_ratio": ratio,
            "flags": flags,
        })
    rows.sort(key=lambda r: (-len(r["flags"]), -r["volume"]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = analyse(a.days)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        return 0

    print(f"ЗДОРОВЬЕ ГРИД-БОТОВ — окно {a.days} дней\n")
    print(f"{'бот':24s} {'ст':>3s} {'тгт':>5s} {'позиция$':>10s} "
          f"{'книга$':>10s} {'запол':>6s} {'простой':>8s} {'оборот$':>11s} "
          f"{'маржа':>8s} {'закон':>8s} {'откл':>6s}")
    print("-" * 118)
    for r in rows:
        idle = ("—" if r["idle_hours"] == float("inf")
                else f"{r['idle_hours']:.0f}ч")
        tg = f"{r['target']:.2f}" if r["target"] else "—"
        mg = f"{r['margin_pct']:.4f}%" if r["margin_pct"] == r["margin_pct"] else "—"
        lw = f"{r['law_pct']:.4f}%" if r["law_pct"] == r["law_pct"] else "—"
        rt = (f"{r['margin_ratio']*100:.0f}%"
              if r["margin_ratio"] == r["margin_ratio"] else "—")
        print(f"{r['name']:24s} {r['status']:3d} {tg:>5s} "
              f"{r['position_usd']:10,.0f} {r['peak_usd']:10,.0f} "
              f"{r['fill_pct']:5.0f}% {idle:>8s} {r['volume']:11,.0f} "
              f"{mg:>8s} {lw:>8s} {rt:>6s}")

    bad = [r for r in rows if r["flags"]]
    print("\n" + ("ФЛАГИ" if bad else "флагов нет"))
    for r in bad:
        print(f"  {r['name']:24s} " + "; ".join(r["flags"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
