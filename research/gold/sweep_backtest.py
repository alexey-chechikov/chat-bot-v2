"""Золото: ложный пробой минимума предыдущего UTC-дня на 15m (LONG) + VWAP / LVN / footprint.

Правила — docs/GOLD_LIQUIDITY_SWEEP_PROTOCOL_2026-10-13.md (опубликован ДО прогона, коммит d983d5b); ТЗ —
docs/GOLD_LIQUIDITY_SWEEP_SPEC_2026-10-13.md. Здесь только реализация; ни один параметр не подбирался по результату.

Поправки реализации и учёта после разбора GPT 13.10 (docs/WEEX_GPT_GOLD_AND_BOTS_REVIEW_2026-10-13.md §4–6) —
параметры протокола не менялись, каждая поправка названа отклонением в отчёте:
  П1 профиль LVN — только выбранные полные дни строго до дня сигнала (без хвоста до конца файла и без пропущенных
     неполных дней между ними);
  П2 полнота дня XAU — покрытие минутами (≥ 720 строк = 12 ч) и хотя бы одна сделка; минута без объёма — это данные;
  П3 фандинг XAU: −qty × mark × rate в каждый момент начисления Binance, пока позиция открыта (вход < T ≤ выход);
  П4 выход на конце данных — рыночный (тейкер + проскальзывание); конец периода не отрезает последние 4 свечи — сигнал
     пропускается (и считается) только если его подтверждение/вход не помещаются в данные;
  П5 шаг цены PAXG по дате (1.00 до 2025-05-16 05:06 UTC, 0.01 после): стоп = low − 2 тика, цель округляется вверх;
  П6 отмена по ТЗ «до входа» — чувствительность (`Market.cancel_rule = "spec"`), основной прогон — по протоколу;
     выходы по времени позже 4 ч + 5 мин из-за дыр в данных помечаются;
  П7 обе нормировки R на одном ledger: бюджетный R = PnL / R$, ценовой R = ход / (вход − стоп); «до расходов» — тот же
     ledger без комиссий, проскальзывания и фандинга (отдельной симуляции с другим qty больше нет);
  П9 разница B−A с 95% ДИ парным бутстрапом по общим ISO-неделям.

    .venv/bin/python3 research/gold/sweep_backtest.py PAXG|XAU [--s1] [--out=путь.json]
        [--data-root=/Users/alexeychechikov/code/bot7] [--funding=путь.csv]

PAXG — PAXGUSDT спот Binance (backtests/frozen/PAXGUSDT_1m_2y.csv), XAU — XAUUSDT TradFi-перпетуал Binance
(backtests/frozen/XAUUSDT_PERP_1m.csv, research/gold/fetch_xau_perp_1m.py) + история фандинга
(backtests/frozen/XAUUSDT_PERP_funding.csv, research/gold/fetch_xau_funding.py). --s1 — чувствительность «только пн–пт».

ATLAS 14.10 (docs/ATLAS_DELTA_PROTOCOL_2026-10-14.md, тест 2): инструменты BTCUSDT_UM / ETHUSDT_UM (Binance USDⓈ-M
1m с taker_buy, research/atlas_data/fetch_binance_um_1m.py; комиссии WEEX; день полный при 1440 минутах) и версия
Cn = B + nd сигнальной свечи ≤ P10 nd всех 15m-свечей 20 предыдущих полных UTC-дней (nd = (2·taker_buy − объём) /
объём свечи). Поведение PAXG/XAU и версий A/B/E не меняется. Прогон — research/atlas_data/delta_test2.py.
"""
from __future__ import annotations

import bisect
import hashlib
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")                # корень данных по умолчанию (--data-root)
MIN, BAR, HOUR, DAY = 60_000, 900_000, 3_600_000, 86_400_000
PAXG_TICK_CUT = int(datetime(2025, 5, 16, 5, 6, tzinfo=timezone.utc).timestamp() * 1000)

INST = {
    "PAXG": dict(file="backtests/frozen/PAXGUSDT_1m_2y.csv", tick=0.01, tick_before=(PAXG_TICK_CUT, 1.0),
                 step=0.0001, min_qty=0.0001, min_notional=5.0, taker=0.0010, maker=0.0010, lev=1.0,
                 min_rows=1, funding_file=None),
    "XAU": dict(file="backtests/frozen/XAUUSDT_PERP_1m.csv", tick=0.01, tick_before=None,
                step=0.001, min_qty=0.001, min_notional=5.0, taker=0.0005, maker=0.0002, lev=20.0,
                min_rows=720, funding_file="backtests/frozen/XAUUSDT_PERP_funding.csv"),
    # ATLAS 14.10: Binance UM как прокси цен WEEX, комиссии WEEX (тейкер 0.048%, мейкер 0.016%), плечо ≤ 20×
    "BTCUSDT_UM": dict(file="backtests/frozen/BTCUSDT_UM_1m.csv", tick=0.1, tick_before=None,
                       step=0.001, min_qty=0.001, min_notional=5.0, taker=0.00048, maker=0.00016, lev=20.0,
                       min_rows=1440, funding_file=None),
    "ETHUSDT_UM": dict(file="backtests/frozen/ETHUSDT_UM_1m.csv", tick=0.01, tick_before=None,
                       step=0.01, min_qty=0.01, min_notional=5.0, taker=0.00048, maker=0.00016, lev=20.0,
                       min_rows=1440, funding_file=None),
}
SLIP = 0.0002
RISK, DAY_LIMIT, RR, MAX_HOLD = 0.0025, 0.0075, 2.0, 4 * HOUR
LATE_EXIT = MAX_HOLD + 5 * MIN
CAPITALS = (1000.0, 3000.0, 5000.0)
COSTS = {"net": (True, SLIP), "net_2slip": (True, 2 * SLIP)}
N_BOOT = 9999
EXITS = ("цель", "стоп", "время", "конец данных")
# LVN (протокол п.4)
LVN_WINDOW, BIN_PCT, VA_LO, VA_HI, LVN_FRAC, LVN_DIST = 2, 0.0005, 0.05, 0.95, 0.25, 0.0015
# дельта агрессора (протокол ATLAS 14.10): порог — квантиль nd свечей ND_DAYS предыдущих полных UTC-дней
ND_DAYS, ND_Q_LO = 20, 0.10


def bar_nd(volume, taker_buy):
    """Нормированная дельта агрессора свечи: (2·taker_buy − объём) / объём; NaN при нулевом объёме."""
    v = np.asarray(volume, dtype=float)
    tb = np.asarray(taker_buy, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(v > 0, (2.0 * tb - v) / np.where(v > 0, v, 1.0), np.nan)


def prior_days_quantile(bar_day, values, complete_days, q: float, n_days: int = ND_DAYS):
    """q-квантиль `values` по всем свечам `n_days` последних ПОЛНЫХ дней строго до дня свечи — только прошлое.
    Свечи отсортированы по времени. NaN — полных дней раньше меньше `n_days` или нет конечных значений.
    Квантиль — numpy, линейная интерполяция."""
    bar_day = np.asarray(bar_day, dtype=np.int64)
    values = np.asarray(values, dtype=float)
    out = np.full(len(bar_day), np.nan)
    if not len(bar_day):
        return out
    if np.any(np.diff(bar_day) < 0):
        raise ValueError("свечи должны идти по времени")
    cd = np.array(sorted(int(d) for d in complete_days), dtype=np.int64)
    udays, first = np.unique(bar_day, return_index=True)
    last = np.r_[first[1:], len(bar_day)]
    span = {int(d): (int(s), int(e)) for d, s, e in zip(udays, first, last)}
    for d, s, e in zip(udays.tolist(), first.tolist(), last.tolist()):
        k = int(np.searchsorted(cd, d, side="left"))                   # полные дни строго до d: cd[:k]
        if k < n_days:
            continue
        parts = [values[span[x][0]:span[x][1]] for x in cd[k - n_days:k].tolist() if x in span]
        vals = np.concatenate(parts) if parts else np.array([])
        vals = vals[np.isfinite(vals)]
        if len(vals):
            out[s:e] = np.quantile(vals, q)
    return out


def load(inst: str, root: Path | str | None = None):
    p = Path(root if root is not None else ROOT) / INST[inst]["file"]
    raw = p.read_bytes()
    d = pd.read_csv(io.BytesIO(raw))
    info = {"file": INST[inst]["file"], "rows": len(d), "first": int(d.ts.iloc[0]), "last": int(d.ts.iloc[-1]),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "missing_minutes": int((d.ts.iloc[-1] - d.ts.iloc[0]) // MIN + 1 - len(d))}
    a = {k: d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume")}
    a["ts"] = d.ts.to_numpy(dtype=np.int64)
    if "taker_buy" in d.columns:                                    # ATLAS: дельта агрессора (версия Cn)
        a["taker_buy"] = d.taker_buy.to_numpy(dtype=float)
    return a, info


def load_funding(path: Path | str):
    """История фандинга (fetch_xau_funding.py): fundingTime (мс), fundingRate, markPrice (может быть пустым)."""
    raw = Path(path).read_bytes()
    d = pd.read_csv(io.BytesIO(raw))
    t = d.fundingTime.to_numpy(dtype=np.int64)
    gaps = np.diff(t) if len(t) > 1 else np.array([], dtype=np.int64)
    info = {"file": str(path), "rows": len(d), "sha256": hashlib.sha256(raw).hexdigest(),
            "first": int(t[0]), "last": int(t[-1]), "intervals_h": {f"{k:g}": int(v) for k, v in
                                                                 pd.Series(np.round(gaps / HOUR, 2)).value_counts().items()},
            "mark_missing": int(pd.to_numeric(d.markPrice, errors="coerce").isna().sum())}
    return {"t": t, "rate": d.fundingRate.to_numpy(dtype=float),
            "mark": pd.to_numeric(d.markPrice, errors="coerce").to_numpy(dtype=float)}, info


class Market:
    def __init__(self, a: dict, inst: str, s1: bool, funding: dict | None = None):
        self.a, self.inst, self.cfg, self.s1 = a, inst, INST[inst], s1
        self.funding = funding                                    # {"t", "rate", "mark"} или None (спот)
        self.cancel_rule = "protocol"                             # "spec" — чувствительность: отмена до ВХОДА
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
        self.bar_day = (self.b_id * BAR) // DAY
        # ATLAS: объём и дельта агрессора свечи (только если в данных есть taker_buy)
        self.b_v = np.add.reduceat(a["volume"], starts)[full]
        tb = a.get("taker_buy")
        self.nd = bar_nd(self.b_v, np.add.reduceat(tb, starts)[full]) if tb is not None else None
        self._nd_q: dict = {}
        # дни: покрытие минутами (данные) отдельно от сделок (активность) — П2
        did = ts // DAY
        dstarts = np.flatnonzero(np.r_[True, did[1:] != did[:-1]])
        dends = np.r_[dstarts[1:], len(ts)]
        self.days = did[dstarts]
        days = self.days.tolist()
        dlow = np.minimum.reduceat(a["low"], dstarts)
        rows = dends - dstarts
        traded = np.add.reduceat((a["volume"] > 0).astype(int), dstarts)
        self.day_first_min = dict(zip(days, dstarts.tolist()))
        self.day_bounds = dict(zip(days, zip(dstarts.tolist(), dends.tolist())))
        self.day_close = dict(zip(days, a["close"][dends - 1].tolist()))
        complete = (rows >= self.cfg["min_rows"]) & (traded >= 1)
        self.level = {}
        prev = None
        for d, lo, ok in zip(days, dlow.tolist(), complete.tolist()):
            wd = (d + 3) % 7                                         # 0 = понедельник
            if prev is not None:
                self.level[d] = prev
            if ok and (not s1 or wd < 5):
                prev = lo
        self.complete_days = [d for d, ok in zip(days, complete.tolist()) if ok]
        # VWAP: накопленные Σ typ·v и Σ v
        typ = (a["high"] + a["low"] + a["close"]) / 3
        self.cum_tv = np.cumsum(typ * a["volume"])
        self.cum_v = np.cumsum(a["volume"])
        self._lvn_cache: dict = {}
        # кандидаты в сигнальные свечи: low < L < close (петля прыгает между ними — то же, что шаг по 1 свече)
        lv = np.array([self.level.get(int(d), np.nan) for d in self.bar_day], dtype=float)
        cond = (self.b_l < lv) & (lv < self.b_c)
        if s1:
            cond &= ((self.bar_day + 3) % 7) < 5
        self.cand = np.flatnonzero(cond)
        self._fund_src, self._fund = None, None

    def nd_quantile(self, q: float):
        """Порог nd по каждой свече: q-квантиль nd всех 15m-свечей ND_DAYS предыдущих полных UTC-дней (только прошлое)."""
        if self.nd is None:
            raise ValueError(f"{self.inst}: в данных нет taker_buy — дельта агрессора не считается")
        key = float(q)
        if key not in self._nd_q:
            self._nd_q[key] = prior_days_quantile(self.bar_day, self.nd, self.complete_days, key, ND_DAYS)
        return self._nd_q[key]

    def tick_at(self, t_ms: int) -> float:
        tb = self.cfg.get("tick_before")
        return tb[1] if tb and t_ms < tb[0] else self.cfg["tick"]

    def funding_arrays(self):
        """(моменты начисления, округлённые до минуты; ставки; mark — из истории, иначе close последней минуты до T)."""
        f = self.funding
        if f is None:
            return None
        if self._fund_src is not f:
            t = (np.asarray(f["t"], dtype=np.int64) + MIN // 2) // MIN * MIN
            mark = np.asarray(f["mark"], dtype=float).copy()
            miss = ~np.isfinite(mark)
            if miss.any():
                idx = np.searchsorted(self.a["ts"], t[miss], side="left") - 1
                mark[miss] = np.where(idx >= 0, self.a["close"][np.clip(idx, 0, None)], np.nan)
            self._fund = (t, np.asarray(f["rate"], dtype=float), mark)
            self._fund_src = f
        return self._fund

    def vwap_at(self, min_idx_incl: int) -> float | None:
        d = int(self.a["ts"][min_idx_incl] // DAY)
        s = self.day_first_min[d]
        tv = self.cum_tv[min_idx_incl] - (self.cum_tv[s - 1] if s else 0.0)
        v = self.cum_v[min_idx_incl] - (self.cum_v[s - 1] if s else 0.0)
        return tv / v if v > 0 else None

    # ---------- LVN (протокол п.4) ----------
    def lvn(self, day: int, window: int = LVN_WINDOW):
        """Зоны LVN и корзины зоны стоимости по профилю `window` выбранных полных дней СТРОГО до дня сигнала — только их
        минуты (П1). Возвращает (edges, lvn_mask, va_mask) — границы корзин и маски; None — данных нет."""
        key = (int(day), int(window))
        if key in self._lvn_cache:
            return self._lvn_cache[key]
        pos = bisect.bisect_left(self.complete_days, int(day))
        prev = self.complete_days[max(0, pos - window):pos]
        if len(prev) < window:
            self._lvn_cache[key] = None
            return None
        sl = [self.day_bounds[d] for d in prev]
        lo = np.concatenate([self.a["low"][s:e] for s, e in sl])
        hi = np.concatenate([self.a["high"][s:e] for s, e in sl])
        v = np.concatenate([self.a["volume"][s:e] for s, e in sl])
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


def simulate(m, version: str, capital: float, costs: str, lvn_window: int = LVN_WINDOW, funding: bool = True):
    """Событийная петля версии A/B/E. `m` — Market или обёртка с тем же интерфейсом (контроли LVN).
    funding=False — учёт без фандинга (только для сравнения с прежней публикацией)."""
    a, cfg = m.a, m.cfg
    use_fee, slip = COSTS[costs]
    taker, maker = (cfg["taker"], cfg["maker"]) if use_fee else (0.0, 0.0)
    fund = m.funding_arrays() if funding else None
    if funding and fund is None and cfg.get("funding_file"):
        raise ValueError(f"{m.inst}: нет истории фандинга — перпетуал без фандинга не считается (funding=False явно)")
    spec_cancel = getattr(m, "cancel_rule", "protocol") == "spec"
    eq = capital
    trades, skipped_min, capped, censored, spec_cancelled = [], 0, 0, 0, 0
    day_pnl: dict = {}
    day_start_eq: dict = {}
    nb = len(m.b_id)
    cand = m.cand
    ts = a["ts"]
    n_min = len(ts)
    b = 0
    while True:
        ci = int(np.searchsorted(cand, b))
        if ci >= len(cand):
            break
        b = int(cand[ci])
        day = int(m.bar_day[b])
        L = m.level[day]
        sig_low, sig_high = m.b_l[b], m.b_h[b]
        conf, k_end, cut = None, b, False
        for k in range(1, 4):
            j = b + k
            if j >= nb:                                              # данные кончились до решения — П4
                cut = True
                break
            if m.b_id[j] != m.b_id[b] + k:                           # дыра в свечах — отмена
                k_end = j
                break
            k_end = j
            if m.b_l[j] < sig_low:                                   # отмена в приоритете
                break
            if m.b_c[j] > sig_high:
                conf = j
                break
        if cut:
            censored += 1                                            # дальше сделок быть не может (см. отчёт)
            break
        if conf is None:
            b = k_end + 1
            continue
        if conf + 1 >= nb:                                           # вход не помещается в данные — П4
            censored += 1
            break
        if m.b_id[conf + 1] != m.b_id[conf] + 1:
            b = k_end + 1
            continue
        # фильтры версий
        ok = True
        if version in ("B", "E", "Cn"):
            vw = m.vwap_at(m.b_end[conf] - 1)
            ok = vw is not None and m.b_c[conf] > vw
        if ok and version == "E":
            z = m.lvn(day, lvn_window)
            ok = z is not None and Market.near_zone(L, z[0], z[1])
        if ok and version == "Cn":                                   # ATLAS: nd сигнальной свечи ≤ P10 прошлого
            p10 = m.nd_quantile(ND_Q_LO)
            ok = bool(np.isfinite(m.nd[b]) and np.isfinite(p10[b]) and m.nd[b] <= p10[b])
        if not ok:
            b = conf + 1
            continue
        # вход
        mi = int(m.b_start[conf + 1])
        entry_day = int(ts[mi] // DAY)
        day_start_eq.setdefault(entry_day, eq)
        if day_pnl.get(entry_day, 0.0) <= -DAY_LIMIT * day_start_eq[entry_day]:
            b = conf + 1
            continue
        raw_entry = float(a["open"][mi])
        below = bool(raw_entry < sig_low)                            # ТЗ отменило бы: минимум обновлён до входа — П6
        if spec_cancel and below:
            spec_cancelled += 1
            b = conf + 2                                             # свеча, отменившая сигнал, сама им не становится
            continue
        tick = m.tick_at(int(ts[mi]))                                # шаг цены по дате — П5
        stop = round(sig_low - 2 * tick, 8)
        plan_entry = raw_entry * (1 + slip)
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
        target = round(math.ceil(round((entry + RR * (entry - stop)) / tick, 9)) * tick, 8)   # вверх до шага — П5
        fee = entry * qty * taker
        slip_cost = raw_entry * slip * qty
        exit_px = exit_raw = why = None
        same_min, j = False, mi
        deadline = ts[mi] + MAX_HOLD
        while j < n_min:
            if ts[j] >= deadline:
                exit_raw, why = float(a["open"][j]), "время"
                exit_px = exit_raw * (1 - slip)
                fee += exit_px * qty * taker
                slip_cost += exit_raw * slip * qty
                break
            hit_stop = a["low"][j] <= stop
            hit_tp = a["high"][j] >= target + m.tick_at(int(ts[j]))
            if hit_stop:
                exit_raw, why, same_min = float(min(stop, a["open"][j])), "стоп", bool(hit_tp)
                exit_px = exit_raw * (1 - slip)
                fee += exit_px * qty * taker
                slip_cost += exit_raw * slip * qty
                break
            if hit_tp:
                exit_raw = exit_px = target
                why = "цель"
                fee += exit_px * qty * maker
                break
            j += 1
        if exit_px is None:                                          # конец данных: рыночная ликвидация — П4
            j = n_min - 1
            exit_raw, why = float(a["close"][j]), "конец данных"
            exit_px = exit_raw * (1 - slip)
            fee += exit_px * qty * taker
            slip_cost += exit_raw * slip * qty
            exit_t = int(ts[j]) + MIN - 1                            # по close последней минуты
        else:
            exit_t = int(ts[j])                                      # внутри минуты выхода, не раньше её open
        fund_usd, n_f = 0.0, 0                                       # фандинг: вход < T ≤ выход — П3
        if fund is not None:
            ft, fr, fm = fund
            i0 = int(np.searchsorted(ft, int(ts[mi]), side="right"))
            i1 = int(np.searchsorted(ft, exit_t, side="right"))
            if i1 > i0:
                fund_usd = float(-qty * np.sum(fm[i0:i1] * fr[i0:i1]))
                n_f = i1 - i0
                if not math.isfinite(fund_usd):
                    raise ValueError(f"нет mark price для фандинга у {pd.Timestamp(int(ft[i0]), unit='ms')}")
        pnl = (exit_px - entry) * qty - fee + fund_usd
        eq += pnl
        xd = int(ts[j] // DAY)
        day_start_eq.setdefault(xd, eq - pnl)
        day_pnl[xd] = day_pnl.get(xd, 0.0) + pnl
        d_px = entry - stop                                          # ≤ 0 — вход ниже стопа: ценовой R не определён
        trades.append({"sig_ts": int(m.b_id[b] * BAR), "entry_ts": int(ts[mi]), "exit_ts": int(ts[j]), "level": L,
                       "sig_low": sig_low, "sig_high": sig_high, "entry": entry, "entry_raw": raw_entry, "stop": stop,
                       "target": target, "tick": tick, "exit": exit_px, "exit_raw": exit_raw, "why": why,
                       "same_minute": same_min, "qty": qty, "r_usd": r_usd, "pnl": pnl, "R": pnl / r_usd,
                       "R_gross": (exit_raw - raw_entry) * qty / r_usd,
                       "pR": pnl / (qty * d_px) if d_px > 0 else float("nan"),
                       "pR_gross": (exit_raw - raw_entry) / d_px if d_px > 0 else float("nan"), "fee": fee, "slip": slip_cost,
                       "funding": fund_usd, "n_funding": n_f, "eq": eq, "notional": (entry + exit_px) * qty,
                       "capped": bool(was_capped), "entry_below_sig_low": below,
                       "late_time_exit": bool(why == "время" and int(ts[j]) - int(ts[mi]) > LATE_EXIT)})
        # новые сигналы — со свечи, начавшейся не раньше выхода
        nxt = np.searchsorted(m.b_id, -(-int(ts[j]) // BAR))
        b = max(int(nxt), conf + 1)
    return {"trades": trades, "skipped_min": skipped_min, "capped": capped, "end_eq": eq, "censored": censored,
            "spec_cancelled": spec_cancelled}


def _iso_week(t_ms: int) -> tuple:
    return tuple(pd.Timestamp(t_ms, unit="ms").isocalendar()[:2])


def week_ci(tr: list, key: str = "R", n_boot: int | None = None, seed: int = 7) -> list:
    """95% ДИ среднего по сделкам: бутстрап блоками ISO-недель (среднее склейки = Σсумм / Σчисел)."""
    wk = [_iso_week(t["entry_ts"]) for t in tr]
    keys = sorted(set(wk))
    pos = {k: i for i, k in enumerate(keys)}
    sums, cnt = np.zeros(len(keys)), np.zeros(len(keys))
    for w, t in zip(wk, tr):
        sums[pos[w]] += t[key]
        cnt[pos[w]] += 1
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(keys), size=(n_boot or N_BOOT, len(keys)))
    means = sums[pick].sum(1) / cnt[pick].sum(1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [float(lo), float(hi)]


def paired_week_diff(tr_a: list, tr_b: list, key: str = "R", n_boot: int | None = None, seed: int = 13) -> dict:
    """B−A: разница средних по сделкам; 95% ДИ — парный бутстрап по ОБЩИМ календарным ISO-неделям (П9)."""
    wa, wb = [_iso_week(t["entry_ts"]) for t in tr_a], [_iso_week(t["entry_ts"]) for t in tr_b]
    keys = sorted(set(wa) | set(wb))
    if not tr_a or not tr_b:
        return {"diff": None, "ci": [None, None], "weeks": len(keys), "n_a": len(tr_a), "n_b": len(tr_b)}
    pos = {k: i for i, k in enumerate(keys)}
    sa, na, sb_, nb_ = (np.zeros(len(keys)) for _ in range(4))
    for w, t in zip(wa, tr_a):
        sa[pos[w]] += t[key]
        na[pos[w]] += 1
    for w, t in zip(wb, tr_b):
        sb_[pos[w]] += t[key]
        nb_[pos[w]] += 1
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(keys), size=(n_boot or N_BOOT, len(keys)))
    SA, NA, SB, NB = sa[pick].sum(1), na[pick].sum(1), sb_[pick].sum(1), nb_[pick].sum(1)
    ok = (NA > 0) & (NB > 0)
    diffs = SB[ok] / NB[ok] - SA[ok] / NA[ok]
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"diff": float(sb_.sum() / nb_.sum() - sa.sum() / na.sum()), "ci": [float(lo), float(hi)],
            "weeks": len(keys), "n_a": len(tr_a), "n_b": len(tr_b), "boot_used": int(ok.sum())}


def _part(tr: list) -> dict:
    if not tr:
        return {"n": 0, "exp_R": None, "exp_pR_gross": None, "funding_crossings": 0, "funding_usd": 0.0,
                "funding_R": 0.0}
    priced = [t["pR_gross"] for t in tr if math.isfinite(t["pR_gross"])]
    return {"n": len(tr), "exp_R": float(np.mean([t["R"] for t in tr])),
            "exp_pR_gross": float(np.mean(priced)) if priced else None,
            "sum_R": float(np.sum([t["R"] for t in tr])),
            "funding_crossings": int(sum(t["n_funding"] for t in tr)),
            "funding_usd": float(sum(t["funding"] for t in tr)),
            "funding_R": float(sum(t["funding"] / t["r_usd"] for t in tr))}


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
    hold = [t for t in tr if t["entry_ts"] >= split_ts]
    dev = [t for t in tr if t["entry_ts"] < split_ts]
    q = {}
    for t in tr:
        k = pd.Timestamp(t["entry_ts"], unit="ms")
        q.setdefault(f"{k.year}Q{(k.month - 1) // 3 + 1}", []).append(t["R"])
    late = [t for t in tr if t["late_time_exit"]]
    priced = [t for t in tr if math.isfinite(t["pR_gross"])]
    return {
        "n": len(tr), "turnover": float(sum(t["notional"] for t in tr)), "wr": float((pnl > 0).mean()),
        "avg_win_R": float(R[pnl > 0].mean()) if (pnl > 0).any() else 0.0,
        "avg_loss_R": float(R[pnl <= 0].mean()) if (pnl <= 0).any() else 0.0,
        "exp_R": float(R.mean()), "exp_usd": float(pnl.mean()), "ci_R": week_ci(tr, "R", seed=rng_seed),
        "exp_R_gross": float(np.mean([t["R_gross"] for t in tr])),
        "exp_pR": float(np.mean([t["pR"] for t in priced])) if priced else None,
        "exp_pR_gross": float(np.mean([t["pR_gross"] for t in priced])) if priced else None,
        "ci_pR_gross": week_ci(priced, "pR_gross", seed=rng_seed) if priced else [None, None],
        "entry_below_stop": len(tr) - len(priced),
        "n_weeks": len({_iso_week(t["entry_ts"]) for t in tr}),
        "fees": float(sum(t["fee"] for t in tr)), "slip": float(sum(t["slip"] for t in tr)),
        "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "max_dd": dd, "max_loss_streak": best, "end_eq": float(eq[-1]),
        "dev": _part(dev), "holdout": _part(hold), "all": _part(tr),
        "funding": {"crossings": int(sum(t["n_funding"] for t in tr)),
                    "trades": int(sum(1 for t in tr if t["n_funding"])),
                    "usd": float(sum(t["funding"] for t in tr)),
                    "R": float(sum(t["funding"] / t["r_usd"] for t in tr))},
        "by_quarter": {k: {"n": len(v), "sum_R": round(float(np.sum(v)), 2)} for k, v in sorted(q.items())},
        "exits": {w: sum(1 for t in tr if t["why"] == w) for w in EXITS},
        "same_minute": sum(1 for t in tr if t["same_minute"]),
        "late_time_exits": len(late), "late_time_exits_R": float(sum(t["R"] for t in late)),
        "entry_below_sig_low": sum(1 for t in tr if t["entry_below_sig_low"]),
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


def _short(st: dict, extra: dict | None = None) -> dict:
    if not st.get("n"):
        return {"n": 0, **(extra or {})}
    return {"n": st["n"], "exp_R": st["exp_R"], "ci_R": st["ci_R"], "holdout_exp_R": st["holdout"]["exp_R"],
            "holdout_n": st["holdout"]["n"], "end_eq": st["end_eq"], **(extra or {})}


def _arg(name: str, default=None):
    return next((x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith(f"--{name}=")), default)


def main() -> None:
    inst = next((x for x in sys.argv[1:] if x in INST), "PAXG")
    s1 = "--s1" in sys.argv
    out = _arg("out")
    root = Path(_arg("data-root", str(ROOT)))
    a, info = load(inst, root)
    funding, finfo = None, None
    if INST[inst]["funding_file"]:
        fpath = Path(_arg("funding", str(root / INST[inst]["funding_file"])))
        if not fpath.exists():
            sys.exit(f"{inst}: нет истории фандинга {fpath} — research/gold/fetch_xau_funding.py")
        funding, finfo = load_funding(fpath)
        if finfo["first"] > info["first"] + 8 * HOUR or finfo["last"] < info["last"] - 8 * HOUR:
            sys.exit(f"{inst}: история фандинга {finfo['first']}…{finfo['last']} не покрывает минутки")
    m = Market(a, inst, s1, funding=funding)
    split_ts = int(info["first"] + 0.7 * (info["last"] - info["first"]))
    print(f"{inst}{' S1 пн–пт' if s1 else ''}: {info['file']} строк {info['rows']}, "
          f"{pd.Timestamp(info['first'], unit='ms')} … {pd.Timestamp(info['last'], unit='ms')} UTC, "
          f"пропусков минут {info['missing_minutes']}, sha256 {info['sha256'][:16]}…; "
          f"контрольная часть с {pd.Timestamp(split_ts, unit='ms'):%Y-%m-%d}")
    if finfo:
        print(f"фандинг: {finfo['rows']} начислений, интервалы ч {finfo['intervals_h']}, sha256 {finfo['sha256'][:16]}…")
    res = {"info": info, "funding_info": finfo, "split_ts": split_ts, "s1": s1, "versions": {}}
    for ver in ("A", "B", "E"):
        vv = res["versions"][ver] = {}
        for cap in CAPITALS:
            for cost in COSTS:
                r = simulate(m, ver, cap, cost)
                vv[f"{int(cap)}_{cost}"] = {"stats": stats(r["trades"], cap, split_ts), "skipped_min": r["skipped_min"],
                                            "capped": r["capped"], "censored": r["censored"], "trades": r["trades"]}
        net, net2 = vv["3000_net"]["stats"], vv["3000_net_2slip"]["stats"]
        vv["status"] = status(net, net2)
        sens = {}
        m.cancel_rule = "spec"
        try:
            r = simulate(m, ver, 3000.0, "net")
            r2 = simulate(m, ver, 3000.0, "net_2slip")
        finally:
            m.cancel_rule = "protocol"
        st, st2 = stats(r["trades"], 3000.0, split_ts), stats(r2["trades"], 3000.0, split_ts)
        sens["spec_cancel"] = _short(st, {"cancelled": r["spec_cancelled"], "status": status(st, st2)})
        if funding is not None:
            r = simulate(m, ver, 3000.0, "net", funding=False)
            r2 = simulate(m, ver, 3000.0, "net_2slip", funding=False)
            st, st2 = stats(r["trades"], 3000.0, split_ts), stats(r2["trades"], 3000.0, split_ts)
            sens["no_funding"] = _short(st, {"status": status(st, st2)})
        vv["sens"] = sens
        if net.get("n"):
            f = net["funding"]
            print(f"{ver}: n {net['n']}, WR {net['wr']:.0%}, бюджетный R: после {net['exp_R']:+.3f} "
                  f"[ДИ {net['ci_R'][0]:+.3f}…{net['ci_R'][1]:+.3f}], до расходов (тот же ledger) {net['exp_R_gross']:+.3f}, "
                  f"×2 проск. {net2['exp_R']:+.3f}; ценовой R: до {net['exp_pR_gross']:+.3f} "
                  f"[ДИ {net['ci_pR_gross'][0]:+.3f}…{net['ci_pR_gross'][1]:+.3f}], после {net['exp_pR']:+.3f}; "
                  f"разработка {net['dev']['exp_R']:+.3f} (n {net['dev']['n']}), контроль "
                  f"{(net['holdout']['exp_R'] if net['holdout']['n'] else float('nan')):+.3f} (n {net['holdout']['n']}); "
                  f"недель {net['n_weeks']}; выходы {net['exits']}; фандинг: пересечений {f['crossings']}, "
                  f"${f['usd']:+.2f} ({f['R']:+.2f}R); вход ниже low сигнальной {net['entry_below_sig_low']}, "
                  f"по ТЗ: n {sens['spec_cancel']['n']}, отменено {sens['spec_cancel']['cancelled']}; поздних выходов "
                  f"{net['late_time_exits']}; обрезано концом {vv['3000_net']['censored']} → {vv['status']}")
        else:
            print(f"{ver}: сделок нет → {vv['status']}")
    ta, tb = res["versions"]["A"]["3000_net"]["trades"], res["versions"]["B"]["3000_net"]["trades"]
    pa, pb = ([t for t in x if math.isfinite(t["pR_gross"])] for x in (ta, tb))
    res["b_minus_a"] = {"net_R": paired_week_diff(ta, tb, "R"), "gross_pR": paired_week_diff(pa, pb, "pR_gross")}
    d = res["b_minus_a"]["net_R"]
    if d["diff"] is not None:
        g = res["b_minus_a"]["gross_pR"]
        print(f"B−A (общие ISO-недели {d['weeks']}): бюджетный R после {d['diff']:+.3f} "
              f"[ДИ {d['ci'][0]:+.3f}…{d['ci'][1]:+.3f}], ценовой R до {g['diff']:+.3f} [ДИ {g['ci'][0]:+.3f}…{g['ci'][1]:+.3f}]")
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
