"""Золото: ложный пробой минимума предыдущего UTC-дня на 15m (LONG) + VWAP / LVN / footprint.

Правила — docs/GOLD_LIQUIDITY_SWEEP_PROTOCOL_2026-10-13.md (опубликован ДО прогона, коммит d983d5b); ТЗ —
docs/GOLD_LIQUIDITY_SWEEP_SPEC_2026-10-13.md. Здесь только реализация; ни один параметр не подбирался по результату.

    .venv/bin/python3 research/gold/sweep_backtest.py PAXG|XAU [--s1] [--out=путь.json]

PAXG — PAXGUSDT спот Binance (backtests/frozen/PAXGUSDT_1m_2y.csv), XAU — XAUUSDT TradFi-перпетуал Binance
(backtests/frozen/XAUUSDT_PERP_1m.csv, research/gold/fetch_xau_perp_1m.py). --s1 — чувствительность «только пн–пт».
Печатает сводку по версиям A/B/E, расходным режимам и капиталам; --out — полный список сделок и метрики в JSON.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MIN, BAR, DAY = 60_000, 900_000, 86_400_000

INST = {
    "PAXG": dict(file="backtests/frozen/PAXGUSDT_1m_2y.csv", tick=0.01, step=0.0001, min_qty=0.0001, min_notional=5.0,
                 taker=0.0010, maker=0.0010, lev=1.0, full_day_minutes=1),
    "XAU": dict(file="backtests/frozen/XAUUSDT_PERP_1m.csv", tick=0.01, step=0.001, min_qty=0.001, min_notional=5.0,
                taker=0.0005, maker=0.0002, lev=20.0, full_day_minutes=720),
}
SLIP = 0.0002
RISK, DAY_LIMIT, RR, MAX_HOLD = 0.0025, 0.0075, 2.0, 4 * 3_600_000
CAPITALS = (1000.0, 3000.0, 5000.0)
COSTS = {"gross": (False, 0.0), "net": (True, SLIP), "net_2slip": (True, 2 * SLIP)}
# LVN (протокол п.4)
LVN_WINDOW, BIN_PCT, VA_LO, VA_HI, LVN_FRAC, LVN_DIST = 2, 0.0005, 0.05, 0.95, 0.25, 0.0015


def load(inst: str):
    p = ROOT / INST[inst]["file"]
    raw = p.read_bytes()
    d = pd.read_csv(io.BytesIO(raw))
    info = {"file": INST[inst]["file"], "rows": len(d), "first": int(d.ts.iloc[0]), "last": int(d.ts.iloc[-1]),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "missing_minutes": int((d.ts.iloc[-1] - d.ts.iloc[0]) // MIN + 1 - len(d))}
    a = {k: d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume")}
    a["ts"] = d.ts.to_numpy(dtype=np.int64)
    return a, info


class Market:
    def __init__(self, a: dict, inst: str, s1: bool):
        self.a, self.cfg, self.s1 = a, INST[inst], s1
        ts = a["ts"]
        # 15m свечи: только полные (15 минут)
        bid = ts // BAR
        starts = np.flatnonzero(np.r_[True, bid[1:] != bid[:-1]])
        ends = np.r_[starts[1:], len(ts)]
        full = (ends - starts) == 15
        self.b_start, self.b_end = starts[full], ends[full]          # индексы минут [start, end)
        self.b_id = bid[self.b_start]
        self.b_o = a["open"][self.b_start]
        self.b_c = a["close"][self.b_end - 1]
        self.b_h = np.maximum.reduceat(a["high"], starts)[full]
        self.b_l = np.minimum.reduceat(a["low"], starts)[full]
        # дни: минимум, «торговые минуты», полнота
        did = ts // DAY
        dstarts = np.flatnonzero(np.r_[True, did[1:] != did[:-1]])
        self.days = did[dstarts]
        dlow = np.minimum.reduceat(a["low"], dstarts)
        traded = np.add.reduceat((a["volume"] > 0).astype(int), dstarts)
        self.day_first_min = dict(zip(self.days.tolist(), dstarts.tolist()))
        self.day_close = dict(zip(self.days.tolist(), a["close"][np.r_[dstarts[1:], len(ts)] - 1].tolist()))
        complete = traded >= self.cfg["full_day_minutes"]
        self.level = {}
        prev = None
        for d, lo, ok in zip(self.days.tolist(), dlow.tolist(), complete.tolist()):
            wd = (d + 3) % 7                                         # 0 = понедельник
            if prev is not None:
                self.level[d] = prev
            if ok and (not s1 or wd < 5):
                prev = lo
        self.complete_days = [d for d, ok in zip(self.days.tolist(), complete.tolist()) if ok]
        # VWAP: накопленные Σ typ·v и Σ v
        typ = (a["high"] + a["low"] + a["close"]) / 3
        self.cum_tv = np.cumsum(typ * a["volume"])
        self.cum_v = np.cumsum(a["volume"])
        self._lvn_cache: dict = {}

    def vwap_at(self, min_idx_incl: int) -> float | None:
        d = int(self.a["ts"][min_idx_incl] // DAY)
        s = self.day_first_min[d]
        tv = self.cum_tv[min_idx_incl] - (self.cum_tv[s - 1] if s else 0.0)
        v = self.cum_v[min_idx_incl] - (self.cum_v[s - 1] if s else 0.0)
        return tv / v if v > 0 else None

    # ---------- LVN (протокол п.4) ----------
    def lvn(self, day: int, window: int = LVN_WINDOW):
        """Зоны LVN и корзины зоны стоимости по профилю предыдущих `window` полных дней. Возвращает
        (edges, lvn_mask, va_mask) — границы корзин и маски; None — данных нет."""
        key = (day, window)
        if key in self._lvn_cache:
            return self._lvn_cache[key]
        prev = [d for d in self.complete_days if d < day][-window:]
        if len(prev) < window:
            self._lvn_cache[key] = None
            return None
        s = self.day_first_min[prev[0]]
        e = self.day_first_min.get(prev[-1] + 1)
        e = e if e is not None else len(self.a["ts"])
        lo, hi, v = self.a["low"][s:e], self.a["high"][s:e], self.a["volume"][s:e]
        width = self.day_close[prev[-1]] * BIN_PCT
        base = math.floor(lo.min() / width) * width
        nb = int(math.ceil((hi.max() - base) / width)) + 1
        i0 = np.clip(((lo - base) // width).astype(int), 0, nb - 1)
        i1 = np.clip(((hi - base) // width).astype(int), 0, nb - 1)
        per = v / (i1 - i0 + 1)
        diff = np.zeros(nb + 1)
        np.add.at(diff, i0, per)
        np.add.at(diff, i1 + 1, -per)
        prof = np.cumsum(diff)[:nb]
        cdf = np.cumsum(prof) / prof.sum() if prof.sum() > 0 else np.zeros(nb)
        va = (cdf >= VA_LO) & (cdf <= VA_HI)
        med = np.median(prof[va]) if va.any() else 0.0
        lvn_mask = va & (prof < LVN_FRAC * med)
        edges = base + width * np.arange(nb + 1)
        out = (edges, lvn_mask, va)
        self._lvn_cache[key] = out
        return out

    @staticmethod
    def near_zone(level: float, edges, mask) -> bool:
        """level внутри зоны (непрерывный ряд корзин mask) или не дальше LVN_DIST цены от её края."""
        if not mask.any():
            return False
        dist = LVN_DIST * level
        idx = np.flatnonzero(mask)
        lo_e, hi_e = edges[idx], edges[idx + 1]
        return bool(np.any((level >= lo_e - dist) & (level <= hi_e + dist)))


def simulate(m: Market, version: str, capital: float, costs: str, lvn_window: int = LVN_WINDOW):
    a, cfg = m.a, m.cfg
    use_fee, slip = COSTS[costs]
    taker, maker = (cfg["taker"], cfg["maker"]) if use_fee else (0.0, 0.0)
    tick = cfg["tick"]
    eq = capital
    trades, skipped_min, capped = [], 0, 0
    day_pnl: dict = {}
    day_start_eq: dict = {}
    nb = len(m.b_id)
    b = 0
    ts = a["ts"]
    while b < nb - 4:
        day = int(m.b_id[b] * BAR // DAY)
        L = m.level.get(day)
        wd = (day + 3) % 7
        if L is None or (m.s1 and wd >= 5) or not (m.b_l[b] < L < m.b_c[b]):
            b += 1
            continue
        sig_low, sig_high = m.b_l[b], m.b_h[b]
        conf = None
        k_end = b
        for k in range(1, 4):
            j = b + k
            if m.b_id[j] != m.b_id[b] + k:                         # дыра в свечах — отмена
                k_end = j
                break
            k_end = j
            if m.b_l[j] < sig_low:                                   # отмена в приоритете
                break
            if m.b_c[j] > sig_high:
                conf = j
                break
        if conf is None or conf + 1 >= nb or m.b_id[conf + 1] != m.b_id[conf] + 1:
            b = k_end + 1
            continue
        # фильтры версий
        ok = True
        if version in ("B", "E"):
            vw = m.vwap_at(m.b_end[conf] - 1)
            ok = vw is not None and m.b_c[conf] > vw
        if ok and version == "E":
            z = m.lvn(day, lvn_window)
            ok = z is not None and Market.near_zone(L, z[0], z[1])
        if not ok:
            b = conf + 1
            continue
        # вход
        mi = m.b_start[conf + 1]
        entry_day = int(ts[mi] // DAY)
        day_start_eq.setdefault(entry_day, eq)
        if day_pnl.get(entry_day, 0.0) <= -DAY_LIMIT * day_start_eq[entry_day]:
            b = conf + 1
            continue
        stop = sig_low - 2 * tick
        plan_entry = a["open"][mi] * (1 + slip)
        r_usd = RISK * eq
        unit = (plan_entry - stop) + plan_entry * taker + stop * (taker + slip)
        if unit <= 0:
            b = conf + 1
            continue
        qty = math.floor(r_usd / unit / cfg["step"]) * cfg["step"]
        max_qty = math.floor(cfg["lev"] * eq / plan_entry / cfg["step"]) * cfg["step"]
        was_capped = qty > max_qty
        qty = min(qty, max_qty)
        if qty < cfg["min_qty"] - 1e-12 or qty * plan_entry < cfg["min_notional"]:
            skipped_min += 1
            b = conf + 1
            continue
        capped += was_capped
        entry = plan_entry
        target = entry + RR * (entry - stop)
        fee = entry * qty * taker
        slip_cost = a["open"][mi] * slip * qty
        exit_px, why, same_min, j = None, None, False, mi
        while j < len(ts):
            if ts[j] >= ts[mi] + MAX_HOLD:
                exit_px, why = a["open"][j] * (1 - slip), "время"
                fee += exit_px * qty * taker
                slip_cost += a["open"][j] * slip * qty
                break
            hit_stop = a["low"][j] <= stop
            hit_tp = a["high"][j] >= target + tick
            if hit_stop:
                raw = min(stop, a["open"][j])
                exit_px, why, same_min = raw * (1 - slip), "стоп", hit_tp
                fee += exit_px * qty * taker
                slip_cost += raw * slip * qty
                break
            if hit_tp:
                exit_px, why = target, "цель"
                fee += exit_px * qty * maker
                break
            j += 1
        if exit_px is None:                                          # конец данных
            j = len(ts) - 1
            exit_px, why = a["close"][j], "конец данных"
        pnl = (exit_px - entry) * qty - fee
        eq += pnl
        xd = int(ts[j] // DAY)
        day_start_eq.setdefault(xd, eq - pnl)
        day_pnl[xd] = day_pnl.get(xd, 0.0) + pnl
        trades.append({"sig_ts": int(m.b_id[b] * BAR), "entry_ts": int(ts[mi]), "exit_ts": int(ts[j]), "level": L,
                       "sig_low": sig_low, "sig_high": sig_high, "entry": entry, "stop": stop, "target": target,
                       "exit": exit_px, "why": why, "same_minute": same_min, "qty": qty, "r_usd": r_usd,
                       "pnl": pnl, "R": pnl / r_usd, "fee": fee, "slip": slip_cost, "eq": eq,
                       "notional": (entry + exit_px) * qty, "capped": bool(was_capped)})
        # новые сигналы — со свечи, начавшейся не раньше выхода
        nxt = np.searchsorted(m.b_id, -(-int(ts[j]) // BAR))
        b = max(int(nxt), conf + 1)
    return {"trades": trades, "skipped_min": skipped_min, "capped": capped, "end_eq": eq}


def stats(tr: list, capital: float, split_ts: int, rng_seed: int = 7) -> dict:
    if not tr:
        return {"n": 0}
    R = np.array([t["R"] for t in tr])
    pnl = np.array([t["pnl"] for t in tr])
    eq = np.r_[capital, [t["eq"] for t in tr]]
    peak = np.maximum.accumulate(eq)
    dd = float(((eq - peak) / peak).min())
    streak = best = 0
    for x in pnl:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    # ДИ ожидания R: бутстрап блоками по ISO-неделям
    wk = np.array([pd.Timestamp(t["entry_ts"], unit="ms").isocalendar()[:2] for t in tr], dtype=object)
    keys = sorted(set(map(tuple, wk)))
    groups = [R[[tuple(w) == k for w in wk]] for k in keys]
    rng = np.random.default_rng(rng_seed)
    boots = []
    for _ in range(9999):
        pick = rng.integers(0, len(groups), len(groups))
        allr = np.concatenate([groups[i] for i in pick])
        boots.append(allr.mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    hold = [t for t in tr if t["entry_ts"] >= split_ts]
    dev = [t for t in tr if t["entry_ts"] < split_ts]
    q = {}
    for t in tr:
        k = pd.Timestamp(t["entry_ts"], unit="ms")
        key = f"{k.year}Q{(k.month - 1) // 3 + 1}"
        q.setdefault(key, []).append(t["R"])
    return {
        "n": len(tr), "turnover": float(sum(t["notional"] for t in tr)), "wr": float((pnl > 0).mean()),
        "avg_win_R": float(R[pnl > 0].mean()) if (pnl > 0).any() else 0.0,
        "avg_loss_R": float(R[pnl <= 0].mean()) if (pnl <= 0).any() else 0.0,
        "exp_R": float(R.mean()), "exp_usd": float(pnl.mean()), "ci_R": [float(lo), float(hi)],
        "fees": float(sum(t["fee"] for t in tr)), "slip": float(sum(t["slip"] for t in tr)),
        "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "max_dd": dd, "max_loss_streak": best, "end_eq": float(eq[-1]),
        "dev": {"n": len(dev), "exp_R": float(np.mean([t["R"] for t in dev])) if dev else None},
        "holdout": {"n": len(hold), "exp_R": float(np.mean([t["R"] for t in hold])) if hold else None,
                    "sum_R": float(np.sum([t["R"] for t in hold])) if hold else 0.0},
        "by_quarter": {k: {"n": len(v), "sum_R": round(float(np.sum(v)), 2)} for k, v in sorted(q.items())},
        "exits": {w: sum(1 for t in tr if t["why"] == w) for w in ("цель", "стоп", "время", "конец данных")},
        "same_minute": sum(1 for t in tr if t["same_minute"]),
        "median_stop_pct": float(np.median([(t["entry"] - t["stop"]) / t["entry"] for t in tr])),
    }


def status(net: dict, net2: dict) -> str:
    if not net.get("n"):
        return "Недостаточно данных"
    if net["exp_R"] <= 0 or (net["holdout"]["exp_R"] is not None and net["holdout"]["exp_R"] <= 0):
        return "Отвергнута"
    if net["n"] < 100 or net["ci_R"][0] <= 0:
        return "Недостаточно данных"
    if net2.get("exp_R", -1) <= 0:
        return "Недостаточно данных"
    return "Кандидат на малый тест исполнения"


def main() -> None:
    inst = next((x for x in sys.argv[1:] if x in INST), "PAXG")
    s1 = "--s1" in sys.argv
    out = next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("--out=")), None)
    a, info = load(inst)
    m = Market(a, inst, s1)
    split_ts = int(info["first"] + 0.7 * (info["last"] - info["first"]))
    print(f"{inst}{' S1 пн–пт' if s1 else ''}: {info['file']} строк {info['rows']}, "
          f"{pd.Timestamp(info['first'], unit='ms')} … {pd.Timestamp(info['last'], unit='ms')} UTC, "
          f"пропусков минут {info['missing_minutes']}, sha256 {info['sha256'][:16]}…; "
          f"контрольная часть с {pd.Timestamp(split_ts, unit='ms'):%Y-%m-%d}")
    res = {"info": info, "split_ts": split_ts, "s1": s1, "versions": {}}
    for ver in ("A", "B", "E"):
        res["versions"][ver] = {}
        for cap in CAPITALS:
            for cost in COSTS:
                r = simulate(m, ver, cap, cost)
                st = stats(r["trades"], cap, split_ts)
                res["versions"][ver][f"{int(cap)}_{cost}"] = {"stats": st, "skipped_min": r["skipped_min"],
                                                             "capped": r["capped"], "trades": r["trades"]}
        n3 = res["versions"][ver]
        net, net2, gross = n3["3000_net"]["stats"], n3["3000_net_2slip"]["stats"], n3["3000_gross"]["stats"]
        st_ = status(net, net2)
        res["versions"][ver]["status"] = st_
        if net.get("n"):
            print(f"{ver}: n {net['n']}, WR {net['wr']:.0%}, ожидание R: до расходов {gross['exp_R']:+.3f}, "
                  f"после {net['exp_R']:+.3f} [ДИ {net['ci_R'][0]:+.3f}…{net['ci_R'][1]:+.3f}], ×2 проск. "
                  f"{net2['exp_R']:+.3f}; разработка {net['dev']['exp_R']:+.3f} (n {net['dev']['n']}), контроль "
                  f"{(net['holdout']['exp_R'] or 0):+.3f} (n {net['holdout']['n']}); PF {net['pf']:.2f}, "
                  f"DD {net['max_dd']:.1%}, серия {net['max_loss_streak']}, выходы {net['exits']}, "
                  f"стоп+цель в минуте {net['same_minute']}, медиана стопа {net['median_stop_pct']:.3%} → {st_}")
        else:
            print(f"{ver}: сделок нет → {st_}")
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
