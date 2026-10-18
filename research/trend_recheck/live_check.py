"""Живое против бэктеста — диагностика §6 протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (не ворота).

Живые входы state/trend_signals.jsonl (только чтение) сопоставляются со сделками P2 базового прогона: тот же символ,
та же сторона, |Δt| ≤ 4 ч, ближайшая, каждая сделка — один раз. Сигналы до 17.09.2026 (исправление
drop_forming_bar — фантомные входы по незакрытой свече) выделяются отдельно.

Для объяснений расхождений строится та же машина сигналов (только выход по закрытию — как
tools/trend_state.analyze на закрытых свечах) на двух рядах:
  • перп UM (ряд бэктеста);
  • спот Binance backtests/frozen/<SYM>_1m_2y.csv — именно его читает живой сервис; копия-снимок в scratchpad,
    sha256 в manifest.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

import replay as rp

JOURNAL = rp.ROOT / "state" / "trend_signals.jsonl"
FIX_TS = int(pd.Timestamp("2026-09-17", tz="UTC").value // 1_000_000)
WIN = 4 * rp.HOUR


def _ms(iso: str) -> int:
    return int(pd.Timestamp(iso).tz_convert("UTC").value // 1_000_000)


def read_journal(path: Path = JOURNAL) -> list[dict]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    return rows


def spot_series(sym: str, snap_dir: Path, end_ms: int) -> tuple[rp.Series, dict]:
    src = rp.FROZEN / f"{sym}_1m_2y.csv"
    snap_dir.mkdir(parents=True, exist_ok=True)
    dst = snap_dir / src.name
    shutil.copyfile(src, dst)
    d = pd.read_csv(dst, usecols=["ts", "open", "high", "low", "close", "volume"])
    d = d[d["ts"] % rp.MIN == 0].drop_duplicates("ts", keep="last").sort_values("ts")
    d = d[d["ts"] < end_ms]
    s = rp.Series(sym, d["ts"].to_numpy(np.int64), d["open"].to_numpy(float), d["high"].to_numpy(float),
                  d["low"].to_numpy(float), d["close"].to_numpy(float), d["volume"].to_numpy(float), end_ms=end_ms)
    return s, {"file": str(src.relative_to(rp.ROOT)), "snapshot": str(dst), "sha256": rp.sha256(dst),
               "rows_used": int(len(d)), "first_utc": rp.iso(int(d["ts"].iloc[0])), "last_utc": rp.iso(int(d["ts"].iloc[-1]))}


def episode_starts(s: rp.Series) -> list[tuple[int, int, int]]:
    """[(время входа = закрытие свечи сигнала, сторона, время выхода или −1)]"""
    out = []
    for i, d, x in rp.live_episodes(s, rp.BASE):
        out.append((int(s.bend[i]), d, int(s.bend[x]) if x >= 0 else -1))
    return out


def _near(eps, t: int, d: int, win: int = WIN):
    c = [e for e in eps if e[1] == d and abs(e[0] - t) <= win]
    return min(c, key=lambda e: abs(e[0] - t)) if c else None


def run(base: dict[str, rp.Series], trades: dict[str, list[dict]], snap_dir: Path) -> dict:
    journal = read_journal()
    entries = [r for r in journal if r.get("event") == "ENTRY" and r.get("symbol") in rp.DECISION]
    exits_by_entry = {(r.get("symbol"), r.get("entry_ts")): r for r in journal if r.get("event") == "EXIT"}
    data_end = min(base[s].data_end for s in rp.DECISION)
    spot, spot_meta, eps_perp, eps_spot = {}, {}, {}, {}
    for sym in rp.DECISION:
        spot[sym], spot_meta[sym] = spot_series(sym, snap_dir, base[sym].data_end)
        eps_perp[sym] = episode_starts(base[sym])
        eps_spot[sym] = episode_starts(spot[sym])
    first_live = min(_ms(r["ts"]) for r in entries) if entries else data_end
    used: set[tuple[str, int]] = set()
    live_rows = []
    for r in sorted(entries, key=lambda z: _ms(z["ts"])):
        sym, d, t = r["symbol"], 1 if r["side"] == "LONG" else -1, _ms(r["ts"])
        p2 = [x for x in trades[sym] if x["period"] == "P2" and x["d"] == d and abs(x["entry_ts"] - t) <= WIN
              and (sym, x["entry_ts"]) not in used]
        m = min(p2, key=lambda x: abs(x["entry_ts"] - t)) if p2 else None
        if m is not None:
            used.add((sym, m["entry_ts"]))
        ep_s, ep_p = _near(eps_spot[sym], t, d), _near(eps_perp[sym], t, d)
        holding = [x for x in trades[sym] if x["entry_ts"] <= t < x["exit_ts"]]
        ex = exits_by_entry.get((sym, r["ts"]))
        row = {"symbol": sym, "side": r["side"], "live_ts": rp.iso(t), "live_px": r.get("px"),
               "live_stop": r.get("stop"), "live_adx": r.get("adx"), "pre_fix_17_09": t < FIX_TS,
               "after_data_end": t >= data_end,
               "bt_entry_utc": rp.iso(m["entry_ts"]) if m else None,
               "dt_h": round((t - m["entry_ts"]) / rp.HOUR, 2) if m else None,
               "bt_E": m["E"] if m else None, "bt_ch0": m["ch0"] if m else None, "bt_R": m["R"] if m else None,
               "bt_exit_utc": rp.iso(m["exit_ts"]) if m else None, "bt_exit_kind": m["kind"] if m else None,
               "live_exit_ts": ex.get("ts") if ex else None, "live_pnl_pct": ex.get("pnl_pct") if ex else None,
               "spot_closed_bar_signal": rp.iso(ep_s[0]) if ep_s else None,
               "perp_closed_bar_signal": rp.iso(ep_p[0]) if ep_p else None,
               "bt_holding": (f"{holding[0]['side']} с {rp.iso(holding[0]['entry_ts'])}" if holding else None)}
        if row["after_data_end"]:
            why = "после конца данных бэктеста (2026-10-14 20:00) — не сопоставляется"
        elif m is not None:
            why = "совпало"
        elif row["pre_fix_17_09"] and not ep_s:
            why = "фантом незакрытой свечи (до 17.09): на закрытых 4h-свечах спота входа нет"
        elif ep_s and not ep_p:
            why = "на споте закрытая свеча дала пробой, на перпе — нет (разные ряды)"
            S = base[sym]
            j = int(np.searchsorted(S.bend, ep_s[0]))
            if j < S.nb and int(S.bend[j]) == ep_s[0]:
                hh, ll = S.channel(rp.BASE.lb)
                lvl = hh[j] if d > 0 else ll[j]
                brk = (S.bc[j] > lvl) if d > 0 else (S.bc[j] < lvl)
                row["perp_adx"], row["perp_close"], row["perp_level"] = float(S.adx[j]), float(S.bc[j]), float(lvl)
                why += (f": свеча {rp.iso(int(S.bstart[j]))} перп ADX {S.adx[j]:.2f}"
                        f"{' < 20' if S.adx[j] < 20 else ''}, close {S.bc[j]:g} "
                        f"{'за' if brk else 'не за'} каналом {lvl:g}")
        elif ep_p and holding:
            why = "перп дал сигнал, но бэктест уже в позиции (вошёл раньше)"
        elif ep_p:
            why = "перп дал сигнал, бэктест не вошёл (пропуск или повторный эпизод)"
        else:
            why = "нет сигнала на закрытых свечах ни спота, ни перпа в ±4 ч"
        row["explanation"] = why
        live_rows.append(row)
    bt_rows = []
    for sym in rp.DECISION:
        perp_starts = {e[0] for e in eps_perp[sym]}
        for x in trades[sym]:
            if x["period"] != "P2" or x["entry_ts"] < first_live - WIN or (sym, x["entry_ts"]) in used:
                continue
            t, d = x["entry_ts"], x["d"]
            ep_s = _near(eps_spot[sym], t, d)
            other = [r for r in entries if r["symbol"] == sym and (1 if r["side"] == "LONG" else -1) == d
                     and abs(_ms(r["ts"]) - t) <= 24 * rp.HOUR]
            if t not in perp_starts:
                why = ("повторный вход после аварийного стопа/пропуска внутри ещё живого эпизода — живой сервис "
                       "такой вход не даёт (R1)")
            elif not ep_s:
                why = "на закрытых свечах спота пробоя не было — сигнал только на перпе"
            elif other:
                why = f"живой вход той же стороны в другое время: {other[0]['ts']}"
            else:
                why = "спот и перп дали сигнал, в живом журнале входа нет"
            bt_rows.append({"symbol": sym, "side": x["side"], "bt_entry_utc": rp.iso(t), "bt_exit_utc": rp.iso(x["exit_ts"]),
                            "bt_exit_kind": x["kind"], "bt_R": x["R"],
                            "spot_closed_bar_signal": rp.iso(ep_s[0]) if ep_s else None, "explanation": why})
    pre = [r for r in live_rows if r["pre_fix_17_09"]]
    post = [r for r in live_rows if not r["pre_fix_17_09"] and not r["after_data_end"]]
    all_entries = [r for r in journal if r.get("event") == "ENTRY"]
    by_sym: dict[str, dict] = {}
    for r in all_entries:
        b = by_sym.setdefault(r.get("symbol"), {"entries": 0, "pre_fix": 0})
        b["entries"] += 1
        b["pre_fix"] += int(_ms(r["ts"]) < FIX_TS)
    return {"live": live_rows, "bt_unmatched": bt_rows, "spot_snapshot": spot_meta,
            "counts": {"live_entries": len(live_rows), "pre_fix": len(pre),
                       "pre_fix_matched": sum(r["explanation"] == "совпало" for r in pre),
                       "pre_fix_phantom": sum(r["explanation"].startswith("фантом") for r in pre),
                       "post_fix_in_data": len(post), "post_fix_matched": sum(r["explanation"] == "совпало" for r in post),
                       "after_data_end": sum(r["after_data_end"] for r in live_rows),
                       "bt_unmatched_in_window": len(bt_rows), "window_from_utc": rp.iso(first_live - WIN),
                       "window_to_utc": rp.iso(data_end), "journal_entries_all_symbols": len(all_entries),
                       "journal_by_symbol": by_sym}}
