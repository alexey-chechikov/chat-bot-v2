"""Первый откат после НОВОГО 4h тренда — офлайн-реплей строго по протоколу
docs/PULLBACK_4H_PROTOCOL_2026-10-15.md (коммит 17c970b, опубликован до расчётов).

Один цикл исполнения для стратегии и всех контролей: `simulate()` (размер → `exits()` → `settle()`).
Стратегия, C1 (прямой 4h-вход) и C2 (откат без ADX) идут через один портфельный `replay()`; C3 (случайное время)
вызывает тот же `simulate()` пачкой. Без ключей, без ордеров, без сети: читает только backtests/frozen/.

    .venv/bin/python3 research/manual_pullback/replay.py

Выход: research/manual_pullback/out/ (summary.json, ledger_*.csv, events_*.csv, manifest.json).
Формализации, которых нет в протоколе, перечислены в FORMALIZATIONS и попадают в отчёт.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
FROZEN = ROOT / "backtests" / "frozen"
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PROTOCOL = ROOT / "docs" / "PULLBACK_4H_PROTOCOL_2026-10-15.md"
PROTOCOL_COMMIT = "17c970b"

MIN = 60_000
M15 = 15 * MIN
H4 = 240 * MIN
H6 = 360 * MIN
DAY = 1440 * MIN
START = 1715731200000                     # 2024-05-15 00:00 UTC — начало выгрузки (протокол)

# тик цены и шаг количества (протокол §Исполнение)
SPEC = {"ETHUSDT": (0.01, 0.001), "XRPUSDT": (0.0001, 1.0), "BTCUSDT": (0.1, 0.001)}

# виды выхода
SL, SL_GAP, TP, TIME, CENS = 0, 1, 2, 3, 4
KIND = {SL: "SL", SL_GAP: "SL_GAP", TP: "TP", TIME: "TIME", CENS: "CENSORED"}


@dataclass(frozen=True)
class Costs:
    name: str
    taker: float = 0.00048
    maker: float = 0.00016
    slip: float = 0.0002


BASE = Costs("base")
SLIP2 = Costs("slip2", slip=0.0004)


@dataclass(frozen=True)
class Cfg:
    capital: float = 3000.0
    risk: float = 0.0025
    daily: float = 0.0075
    min_notional: float = 5.0
    adx_n: int = 14
    adx_min: float = 20.0
    lookback: int = 30
    ema_n: int = 20
    atr_n: int = 14
    touch_first: int = 4
    last_bar: int = 16
    confirm_bars: int = 3
    drift: float = 0.1
    stop_pad: float = 0.1
    wmin: float = 0.007
    wmax: float = 0.020
    rr: float = 2.0
    hold: int = 480                       # минут = 8 ч


CFG = Cfg()

FORMALIZATIONS = [
    "EMA20 касания — значение EMA на закрытии самой свечи касания (включая её close), как линия ema(close,20) в TradingView.",
    "ATR14(15m) и ATR/DM внутри ADX: TR и DM начинаются со 2-й свечи непрерывного отрезка (нужен предыдущий бар), "
    "seed = среднее первых 14, далее RMA 1/14; индикаторы пересчитываются заново после дыры в данных.",
    "Дыра (неполная 15m/4h свеча) в окне 31+1 4h-свечей, в свечах №1…подтверждения или пропущенная минута входа — "
    "событие отменяется; пропущенная минута внутри позиции до выхода — сделка цензурирована (в статистику не входит).",
    "Отмена по low < low_p проверяется и на самой свече подтверждения: если её low ниже low_p — отмена, даже при "
    "закрытии выше двух high (SHORT зеркально). Закрытие за экстремумом 4h-свечи пробоя проверяется первым.",
    "Касание на свече №16 — подтверждения быть не может, отмена (истёк срок).",
    "Дрейф |open − close подтверждения| ≤ 0.1A считается по сырой цене open; E = open × (1 ± slip); ширина стопа и цель "
    "2R — от E с проскальзыванием (как в §6: E уже содержит проскальзывание).",
    "Цель — лимит по цене TP (в т.ч. при гэпе open за цель); стоп — по S × (1 ∓ slip), гэп через стоп — open × (1 ∓ slip); "
    "8 ч — рыночный выход по open минуты entry+480 мин × (1 ∓ slip).",
    "Фандинг: начисление считается, если entry < fundingTime ≤ exit, fundingTime округлён вниз до минуты; выход внутри "
    "минуты датируется её концом (−1 мс). Вход ровно в минуту начисления — без начисления; выход по open этой минуты — с ним.",
    "R = net PnL / (q × (|E − S*| + fee_in×E + fee_out×S*)) — риск позиции после округления q; стоп без гэпа ≈ −1R. "
    "Gross R — тот же знаменатель, PnL по сырым ценам (open входа, уровень стопа/цели, open выхода) без комиссий, "
    "проскальзывания и фандинга.",
    "Дневной лимит: сумма net PnL сделок, закрытых с 00:00 UTC до момента входа, ≤ −0.75% equity на 00:00 UTC → "
    "входов до конца суток нет (реализованный, не плавающий).",
    "Портфель ETH+XRP: обе машины сигналов работают независимо; вход получает первый по времени входа; при одновременном "
    "входе — более раннее 4h-событие, затем ETH раньше XRP. Пока открыта позиция (на любом символе), новые 4h-события "
    "обоих символов игнорируются; уже ждущее событие другого символа может войти после выхода, если успеет до свечи №16.",
    "Порядок в момент t: свеча 15m, закрывшаяся в t → 4h-событие, закрывшееся в t → входы по open минуты t.",
    "Общий конец данных для всех символов — последняя закрытая минута самого короткого файла (+1 мин); сделки, не "
    "закрывшиеся до него, — цензурированы.",
    "Разрез 70/30 — по календарю периода [2024-05-15; конец), сделка относится к части по времени входа.",
    "Бутстрап по ISO-неделям: все календарные недели периода (пустые тоже), 9 999 повторов, seed 20261015, ДИ 95% "
    "перцентильный, среднее R = сумма R / число сделок в выборке недель.",
    "C3: терциль волатильности = ATR14(15m)/close последней закрытой 15m перед входом, пороги — по всему периоду символа; "
    "корзина — час входа UTC // 6; кандидат — вход по open первой минуты 15m-свечи, у которой есть все 481 минута окна; "
    "размер — B той же сделки; R и издержки — тем же simulate(). Ранг = (k+1)/(999+1), k — число повторов со средним ≥ "
    "среднего стратегии.",
    "C1: A = ATR14 последней закрытой 15m (кончается на закрытии 4h-пробоя); вход open первой минуты после пробоя; "
    "дрейф не проверяется (подтверждения нет).",
]


# ───────────────────────────── данные ─────────────────────────────

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def read_minutes(sym: str) -> dict:
    d = pd.read_csv(FROZEN / f"{sym}_UM_1m.csv", usecols=["ts", "open", "high", "low", "close"])
    ts = d.ts.to_numpy(np.int64)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    return {"ts": ts, "o": o, "h": h, "l": l, "c": c}


def check_minutes(m: dict) -> dict:
    ts = m["ts"]
    dt = np.diff(ts)
    bad = ~(np.isfinite(m["o"]) & np.isfinite(m["h"]) & np.isfinite(m["l"]) & np.isfinite(m["c"])
            & (m["l"] > 0) & (m["h"] >= np.maximum(m["o"], m["c"])) & (m["l"] <= np.minimum(m["o"], m["c"])))
    return {"rows": int(len(ts)), "first": iso(ts[0]), "last": iso(ts[-1]),
            "duplicates_or_unsorted": int((dt <= 0).sum()), "not_on_minute": int((ts % MIN != 0).sum()),
            "missing_minutes": int(((dt[dt > 0] // MIN) - 1).sum()), "gaps": int((dt > MIN).sum()),
            "ohlc_defects": int(bad.sum())}


def read_funding(sym: str) -> pd.DataFrame:
    return pd.read_csv(FROZEN / f"{sym}_funding.csv", dtype={"fundingTime": np.int64, "fundingRate": float,
                                                               "markPrice": float})


# ───────────────────────────── свечи и индикаторы ─────────────────────────────

def build_bars(m: dict, start: int, end: int, width: int) -> dict:
    """Регулярная UTC-сетка слотов [start, end) шириной width. Свеча полная, если в слоте ровно width/MIN минут
    (уникальные метки — проверены в check_minutes). Неполная — дыра (ok=False, цены NaN)."""
    per = width // MIN
    n = (end - start) // width
    ts = m["ts"]
    slot = (ts - start) // width
    keep = (slot >= 0) & (slot < n)
    cnt = np.bincount(slot[keep], minlength=n)[:n]
    first = np.searchsorted(ts, start + np.arange(n, dtype=np.int64) * width)
    ok = cnt == per
    O, Hh, L, C = (np.full(n, np.nan) for _ in range(4))
    idx = np.flatnonzero(ok)
    if len(idx):
        g = first[idx][:, None] + np.arange(per)[None, :]
        O[idx] = m["o"][first[idx]]
        C[idx] = m["c"][first[idx] + per - 1]
        Hh[idx] = m["h"][g].max(axis=1)
        L[idx] = m["l"][g].min(axis=1)
    return {"t": start + np.arange(n, dtype=np.int64) * width, "o": O, "h": Hh, "l": L, "c": C, "ok": ok}


def segments(ok: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], np.asarray(ok, bool).astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def rma_seeded(x: np.ndarray, n: int, first: int = 0) -> np.ndarray:
    """Wilder RMA: значение в first+n-1 = среднее x[first:first+n], далее v += (x − v)/n. До seed — NaN."""
    out = np.full(len(x), np.nan)
    if len(x) - first < n:
        return out
    v = float(np.mean(x[first:first + n]))
    out[first + n - 1] = v
    for i in range(first + n, len(x)):
        v += (x[i] - v) / n
        out[i] = v
    return out


def true_range(h, l, c) -> np.ndarray:
    """TR для баров 1..m-1 (нужен предыдущий close); длина m-1."""
    return np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))


def atr_wilder(h, l, c, n: int = 14) -> np.ndarray:
    out = np.full(len(h), np.nan)
    if len(h) > n:
        out[1:] = rma_seeded(true_range(h, l, c), n)
    return out


def adx_wilder(h, l, c, n: int = 14) -> np.ndarray:
    """ADX Уайлдера: ATR/+DM/−DM seed = среднее первых n значений (бары 1..n), RMA 1/n; DX с бара n;
    ADX seed = среднее первых n DX (бары n..2n−1), далее RMA. Первое значение — бар 2n−1."""
    out = np.full(len(h), np.nan)
    if len(h) < 2 * n:
        return out
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(h, l, c)
    atr = rma_seeded(tr, n)
    pdi = 100 * rma_seeded(pdm, n) / atr
    mdi = 100 * rma_seeded(mdm, n) / atr
    s = pdi + mdi
    with np.errstate(invalid="ignore", divide="ignore"):
        dx = np.where(s > 0, 100 * np.abs(pdi - mdi) / s, 0.0)
    dx[~np.isfinite(pdi)] = np.nan
    out[1:] = rma_seeded(dx, n, n - 1)
    return out


def ema_sma_seed(c: np.ndarray, n: int = 20) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) < n:
        return out
    a = 2.0 / (n + 1)
    v = float(np.mean(c[:n]))
    out[n - 1] = v
    for i in range(n, len(c)):
        v += a * (c[i] - v)
        out[i] = v
    return out


def by_segments(ok, fn, *arrays, **kw) -> np.ndarray:
    out = np.full(len(ok), np.nan)
    for a, b in segments(ok):
        out[a:b] = fn(*(x[a:b] for x in arrays), **kw)
    return out


@dataclass
class Sym:
    name: str
    tick: float
    step: float
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    b15: dict
    b4: dict
    ema15: np.ndarray
    atr15: np.ndarray
    adx4: np.ndarray
    f_t: np.ndarray                # моменты начислений, округлены вниз до минуты
    f_cum: np.ndarray              # префиксные суммы mark×rate, длина len(f_t)+1
    start: int
    end: int


def make_sym(name: str, m: dict, funding: pd.DataFrame | None, start: int, end: int, cfg: Cfg = CFG,
             tick: float | None = None, step: float | None = None) -> Sym:
    keep = (m["ts"] >= start) & (m["ts"] < end)
    m = {k: v[keep] for k, v in m.items()}
    b15 = build_bars(m, start, end, M15)
    b4 = build_bars(m, start, end, H4)
    ema15 = by_segments(b15["ok"], ema_sma_seed, b15["c"], n=cfg.ema_n)
    atr15 = by_segments(b15["ok"], atr_wilder, b15["h"], b15["l"], b15["c"], n=cfg.atr_n)
    adx4 = by_segments(b4["ok"], adx_wilder, b4["h"], b4["l"], b4["c"], n=cfg.adx_n)
    if funding is None or len(funding) == 0:
        f_t = np.zeros(0, np.int64)
        f_v = np.zeros(0)
    else:
        raw = funding.fundingTime.to_numpy(np.int64)
        f_t = raw - raw % MIN
        rate = funding.fundingRate.to_numpy(float)
        mark = funding.markPrice.to_numpy(float)
        miss = ~np.isfinite(mark) | (mark <= 0)
        if miss.any():                                     # нет mark у биржи → open этой минуты
            i = np.searchsorted(m["ts"], f_t[miss])
            i = np.minimum(i, len(m["ts"]) - 1)
            mark[miss] = np.where(m["ts"][i] == f_t[miss], m["o"][i], np.nan)
        f_v = np.nan_to_num(rate * mark)
        order = np.argsort(f_t, kind="stable")
        f_t, f_v = f_t[order], f_v[order]
    t0, s0 = SPEC.get(name, (0.01, 0.001))
    return Sym(name, tick if tick is not None else t0, step if step is not None else s0, m["ts"], m["o"], m["h"],
               m["l"], m["c"], b15, b4, ema15, atr15, adx4, f_t, np.concatenate([[0.0], np.cumsum(f_v)]), start, end)


# ───────────────────────────── 4h-события ─────────────────────────────

def detect_events(s: Sym, need_adx: bool, cfg: Cfg = CFG) -> list[tuple[int, int, int]]:
    """[(T закрытия 4h, side, i4)]. LONG: close[i] > max(high[i-30..i-1]) (окно без текущей), а close[i-1] не был выше
    max(high[i-31..i-2]); ADX14[i] ≥ 20 (если need_adx). SHORT зеркально. Дыра в барах i-31..i → события нет."""
    b = s.b4
    H, L, C, ok = b["h"], b["l"], b["c"], b["ok"]
    lb = cfg.lookback
    out = []
    for i in range(lb + 1, len(C)):
        if not ok[i - lb - 1:i + 1].all():
            continue
        hh, ll = H[i - lb:i].max(), L[i - lb:i].min()
        hh_p, ll_p = H[i - lb - 1:i - 1].max(), L[i - lb - 1:i - 1].min()
        up = C[i] > hh and not C[i - 1] > hh_p
        dn = C[i] < ll and not C[i - 1] < ll_p
        if not (up or dn):
            continue
        if need_adx and not (s.adx4[i] >= cfg.adx_min):
            continue
        out.append((int(b["t"][i] + H4), 1 if up else -1, i))
    return out


# ───────────────────────────── ожидание отката и подтверждения ─────────────────────────────

@dataclass
class Pending:
    eid: str
    sym: str
    side: int
    T: int            # закрытие 4h-свечи пробоя
    k1: int           # индекс 15m-слота свечи №1
    lo4: float
    hi4: float
    touch: int = 0    # номер свечи касания (0 — ещё нет)
    A: float = float("nan")
    ext: float = float("nan")   # low_p (LONG) / high_p (SHORT)


def step(p: Pending, s: Sym, j: int, cfg: Cfg = CFG) -> str | None:
    """Обработать закрытую 15m-свечу j (её номер k = j − k1 + 1). None — ждём дальше, 'confirm' — вход по open
    следующей свечи, иначе причина отмены. Порядок: дыра → close за экстремумом 4h-пробоя → (до касания) касание EMA20
    в №4…16 → (после касания) новый экстремум за low_p/high_p → подтверждение → срок."""
    k = j - p.k1 + 1
    b = s.b15
    if not b["ok"][j]:
        return "cancel_gap"
    side, cl = p.side, b["c"][j]
    if (side > 0 and cl < p.lo4) or (side < 0 and cl > p.hi4):
        return "cancel_close_beyond_4h"
    if p.touch == 0:
        if k >= cfg.touch_first:
            e = s.ema15[j]
            if not np.isfinite(e):
                return "cancel_gap"
            if b["l"][j] <= e <= b["h"][j]:
                a = s.atr15[j]
                if not np.isfinite(a):
                    return "cancel_gap"
                p.touch, p.A = k, float(a)
                p.ext = float(b["l"][p.k1:j + 1].min() if side > 0 else b["h"][p.k1:j + 1].max())
                return "expire_confirm" if k >= cfg.last_bar else None
        return "expire_touch" if k >= cfg.last_bar else None
    if (side > 0 and b["l"][j] < p.ext) or (side < 0 and b["h"][j] > p.ext):
        return "cancel_new_extreme"
    if side > 0 and cl > max(b["h"][j - 1], b["h"][j - 2]):
        return "confirm"
    if side < 0 and cl < min(b["l"][j - 1], b["l"][j - 2]):
        return "confirm"
    if k - p.touch >= cfg.confirm_bars or k >= cfg.last_bar:
        return "expire_confirm"
    return None


def minute_index(s: Sym, t: int) -> int:
    i = int(np.searchsorted(s.ts, t))
    return i if i < len(s.ts) and s.ts[i] == t else -1


def entry_price(raw, side, costs: Costs):
    return raw * (1 + side * costs.slip)


def make_order(s: Sym, i0: int, side: int, raw: float, S: float, costs: Costs, cfg: Cfg = CFG) -> dict | str:
    """Ширина (E − S)/E в [0.7%; 2.0%] по E с проскальзыванием; цель E + 2(E − S)."""
    E = float(entry_price(raw, side, costs))
    w = side * (E - S) / E
    if not (cfg.wmin <= w <= cfg.wmax):
        return "skip_width"
    return {"i0": i0, "t": int(s.ts[i0]), "side": side, "raw": float(raw), "E": E, "S": float(S),
            "TP": E + cfg.rr * (E - S), "w": w}


def order_from_confirm(p: Pending, s: Sym, j: int, costs: Costs, cfg: Cfg = CFG) -> dict | str:
    t = int(s.b15["t"][j] + M15)
    i0 = minute_index(s, t)
    if i0 < 0:
        return "cancel_entry_gap"
    raw = float(s.o[i0])
    if abs(raw - s.b15["c"][j]) > cfg.drift * p.A:
        return "cancel_drift"
    S = p.ext - p.side * cfg.stop_pad * p.A
    o = make_order(s, i0, p.side, raw, S, costs, cfg)
    if isinstance(o, dict):
        o.update(A=p.A, touch=p.touch, confirm=j - p.k1 + 1, ext=p.ext, j_sig=j)
    return o


def order_c1(s: Sym, T: int, side: int, lo4: float, hi4: float, costs: Costs, cfg: Cfg = CFG) -> dict | str:
    j = (T - s.start) // M15 - 1                 # последняя закрытая 15m (кончается в T)
    if j < 0 or not s.b15["ok"][j] or not np.isfinite(s.atr15[j]):
        return "cancel_gap"
    i0 = minute_index(s, T)
    if i0 < 0:
        return "cancel_entry_gap"
    A = float(s.atr15[j])
    S = lo4 - cfg.stop_pad * A if side > 0 else hi4 + cfg.stop_pad * A
    o = make_order(s, i0, side, float(s.o[i0]), S, costs, cfg)
    if isinstance(o, dict):
        o.update(A=A, touch=0, confirm=0, ext=lo4 if side > 0 else hi4, j_sig=j)
    return o


# ───────────────────────────── ЕДИНЫЙ цикл исполнения ─────────────────────────────

def size(B, E, S, side, costs: Costs, step_q: float):
    """q = B / (|E − S*| + fee_in×E + fee_out×S*), S* — стоп с проскальзыванием; вниз по шагу. Возвращает (q, риск на
    единицу)."""
    Sstar = S * (1 - side * costs.slip)
    per = np.abs(E - Sstar) + costs.taker * E + costs.taker * Sstar
    q = np.floor(B / per / step_q + 1e-9) * step_q
    return np.round(q, 10), per


def exits(s: Sym, i0, side, S, tp, hold: int):
    """Минутный проход для N позиций сразу (N=1 у стратегии, N=999 у C3). Порядок в минуте: гэп через стоп по open
    (кроме минуты входа) → стоп (касание; стоп раньше цели в одной минуте) → цель, если high ≥ TP + тик (SHORT: low ≤
    TP − тик). Нет выхода за hold минут → рыночный по open минуты entry+hold. Пропущенная минута до выхода — цензура.
    Возвращает (kind, exit_raw, exit_time)."""
    i0 = np.asarray(i0, np.int64)
    side = np.asarray(side, float)
    S = np.asarray(S, float)
    tp = np.asarray(tp, float)                 # имя tp, а не TP: TP — код вида выхода
    N, L = len(i0), hold + 1
    n = len(s.ts)
    off = np.arange(L, dtype=np.int64)
    idx = i0[:, None] + off[None, :]
    valid = idx < n
    idc = np.where(valid, idx, n - 1)
    contig = valid & (s.ts[idc] == s.ts[i0][:, None] + off[None, :] * MIN)
    lead = np.where(contig.all(axis=1), L, np.argmin(contig, axis=1))
    o, h, l = s.o[idc], s.h[idc], s.l[idc]
    lg = (side > 0)[:, None]
    Sx, Tx = S[:, None], tp[:, None]
    gap = (off[None, :] > 0) & np.where(lg, o <= Sx, o >= Sx)
    slh = np.where(lg, l <= Sx, h >= Sx)
    tph = np.where(lg, h >= Tx + s.tick, l <= Tx - s.tick)
    ev = (gap | slh | tph)[:, :hold] & (off[None, :hold] < lead[:, None])
    hit = ev.any(axis=1)
    first = np.argmax(ev, axis=1)
    r = np.arange(N)
    g, sl = gap[r, first], slh[r, first]
    kind = np.full(N, CENS, np.int64)
    xraw = np.full(N, np.nan)
    xt = np.full(N, -1, np.int64)
    tmin = s.ts[idc[r, first]]
    m = hit & g
    kind[m], xraw[m], xt[m] = SL_GAP, o[r, first][m], tmin[m]
    m = hit & ~g & sl
    kind[m], xraw[m], xt[m] = SL, S[m], tmin[m] + MIN - 1
    m = hit & ~g & ~sl
    kind[m], xraw[m], xt[m] = TP, tp[m], tmin[m] + MIN - 1
    m = ~hit & (lead >= L)
    kind[m], xraw[m], xt[m] = TIME, o[r, hold][m], s.ts[idc[r, hold]][m]
    return kind, xraw, xt


def funding_sum(s: Sym, t_in, t_out):
    """Σ mark×rate по начислениям entry < t ≤ exit и их число."""
    a = np.searchsorted(s.f_t, np.asarray(t_in, np.int64), side="right")
    b = np.searchsorted(s.f_t, np.asarray(t_out, np.int64), side="right")
    b = np.maximum(a, b)
    return s.f_cum[b] - s.f_cum[a], b - a


def settle(s: Sym, side, raw, E, S, q, per, kind, xraw, xt, t_in, costs: Costs) -> dict:
    side = np.asarray(side, float)
    X = np.where(kind == TP, xraw, xraw * (1 - side * costs.slip))
    fee_in = costs.taker * E * q
    fee_out = np.where(kind == TP, costs.maker, costs.taker) * X * q
    fu, fn = funding_sum(s, t_in, np.where(xt < 0, t_in, xt))
    funding = side * q * fu                                  # > 0 — заплачено (LONG при rate>0), < 0 — получено
    pnl = side * (X - E) * q - fee_in - fee_out - funding
    risk_usd = q * per
    with np.errstate(invalid="ignore", divide="ignore"):
        R = pnl / risk_usd
        Rg = side * (xraw - raw) * q / risk_usd
    cens = kind == CENS
    for a in (X, pnl, R, Rg):
        a[cens] = np.nan
    return {"X": X, "fee_in": fee_in, "fee_out": fee_out, "funding": np.where(cens, np.nan, funding),
            "funding_n": fn, "pnl": pnl, "risk_usd": risk_usd, "R": R, "R_gross": Rg}


def simulate(s: Sym, i0, side, raw, E, S, tp, B, costs: Costs, cfg: Cfg = CFG) -> dict:
    """Единый цикл исполнения: размер → минутный проход → расчёт. Векторно по N позициям."""
    i0 = np.atleast_1d(np.asarray(i0, np.int64))
    side, raw, E, S, tp, B = (np.broadcast_to(np.asarray(x, float), i0.shape).copy() for x in (side, raw, E, S, tp, B))
    q, per = size(B, E, S, side, costs, s.step)
    ok = (q > 0) & (q * E >= cfg.min_notional)
    kind, xraw, xt = exits(s, i0, side, S, tp, cfg.hold)
    t_in = s.ts[i0]
    st = settle(s, side, raw, E, S, q, per, kind, xraw, xt, t_in, costs)
    st.update(q=q, per=per, ok=ok, kind=kind, xraw=xraw, xt=xt, t_in=t_in)
    return st


# ───────────────────────────── портфельный реплей ─────────────────────────────

def replay(syms: list[Sym], variant: str, costs: Costs, cfg: Cfg = CFG, end: int | None = None) -> dict:
    """variant: 'S' — стратегия, 'C1' — прямой 4h-вход, 'C2' — откат без ADX. Одна позиция на весь список символов;
    по одному символу — отдельный прогон. Капитал cfg.capital, сложный процент, риск 0.25%, дневной лимит 0.75%."""
    end = end if end is not None else min(s.end for s in syms)
    order_names = sorted(s.name for s in syms)
    rank = {nm: i for i, nm in enumerate(order_names)}
    ev_at: dict[int, list] = {}
    for si, s in enumerate(syms):
        for T, side, i4 in detect_events(s, need_adx=(variant != "C2"), cfg=cfg):
            ev_at.setdefault(T, []).append((si, side, i4))
    counts: Counter = Counter()
    log: list[dict] = []
    pend: dict[str, Pending | None] = {s.name: None for s in syms}
    pos_in, pos_out = -1, -1
    closed: list[tuple[int, float]] = []
    trades: list[dict] = []
    t0 = min(s.start for s in syms) + M15
    for t in range(t0, end + 1, M15):
        intents = []
        for si, s in enumerate(syms):                      # 1) 15m-свеча, закрывшаяся в t
            p = pend[s.name]
            if p is None:
                continue
            j = (t - s.start) // M15 - 1
            if j < p.k1 or j >= len(s.b15["ok"]):
                continue
            res = step(p, s, j, cfg)
            if res is None:
                continue
            pend[s.name] = None
            counts[res] += 1
            if res == "confirm":
                intents.append((p.T, rank[s.name], si, p, j))
            else:
                log.append({"eid": p.eid, "sym": s.name, "side": p.side, "T": p.T, "outcome": res, "at": t})
        if t % H4 == 0:                                    # 2) 4h-событие, закрывшееся в t
            for si, side, i4 in ev_at.get(t, []):
                s = syms[si]
                eid = f"{s.name}-{iso(t)}-{'L' if side > 0 else 'S'}"
                counts["events"] += 1
                if pos_in <= t < pos_out:
                    counts["ignored_in_position"] += 1
                    log.append({"eid": eid, "sym": s.name, "side": side, "T": t, "outcome": "ignored_in_position", "at": t})
                    continue
                p = pend[s.name]
                if p is not None:
                    if p.side == side:
                        counts["ignored_same_side_pending"] += 1
                        log.append({"eid": eid, "sym": s.name, "side": side, "T": t,
                                    "outcome": "ignored_same_side_pending", "at": t})
                        continue
                    counts["cancel_opposite_event"] += 1
                    log.append({"eid": p.eid, "sym": s.name, "side": p.side, "T": p.T,
                                "outcome": "cancel_opposite_event", "at": t})
                    pend[s.name] = None
                lo4, hi4 = float(s.b4["l"][i4]), float(s.b4["h"][i4])
                if variant == "C1":
                    intents.append((t, rank[s.name], si, Pending(eid, s.name, side, t, 0, lo4, hi4), None))
                else:
                    pend[s.name] = Pending(eid, s.name, side, t, int((t - s.start) // M15), lo4, hi4)
        intents.sort(key=lambda x: (x[0], x[1]))
        for T, _, si, p, j in intents:                    # 3) входы по open минуты t
            s = syms[si]
            o = order_c1(s, T, p.side, p.lo4, p.hi4, costs, cfg) if j is None else order_from_confirm(p, s, j, costs, cfg)
            outcome = None
            if isinstance(o, str):
                outcome = o
            elif pos_out > t:
                outcome = "skip_busy"
            else:
                day0 = t - t % DAY
                eq_day0 = cfg.capital + sum(x for xt, x in closed if xt < day0)
                today = sum(x for xt, x in closed if day0 <= xt <= t)
                if today <= -cfg.daily * eq_day0:
                    outcome = "skip_daily_limit"
            if outcome is None:
                eq = cfg.capital + sum(x for xt, x in closed if xt <= t)
                B = cfg.risk * eq
                st = simulate(s, o["i0"], p.side, o["raw"], o["E"], o["S"], o["TP"], B, costs, cfg)
                if not st["ok"][0]:
                    outcome = "skip_min_notional"
                else:
                    tr = {"eid": p.eid, "sym": s.name, "side": p.side, "event_T": p.T, "touch": o["touch"],
                          "confirm": o["confirm"], "entry_ts": o["t"], "raw": o["raw"], "E": o["E"], "S": o["S"],
                          "TP": o["TP"], "width": o["w"], "A": o["A"], "j_sig": o["j_sig"], "equity": eq, "B": B,
                          **{k: (v[0].item() if hasattr(v[0], "item") else v[0]) for k, v in st.items() if k != "ok"}}
                    tr["kind"] = KIND[int(tr["kind"])]
                    tr["exit_ts"] = int(tr.pop("xt"))
                    tr["exit_raw"] = tr.pop("xraw")
                    tr["censored"] = tr["kind"] == "CENSORED"
                    trades.append(tr)
                    pos_in = t
                    if tr["censored"]:
                        pos_out = t + cfg.hold * MIN            # занят до исходного дедлайна
                        counts["censored"] += 1
                    else:
                        pos_out = tr["exit_ts"]
                        closed.append((tr["exit_ts"], tr["pnl"]))
                    outcome = "entered"
            counts[outcome] += 1
            log.append({"eid": p.eid, "sym": s.name, "side": p.side, "T": p.T, "outcome": outcome, "at": t})
    for nm, p in pend.items():
        if p is not None:
            counts["pending_at_end"] += 1
    return {"variant": variant, "costs": costs.name, "symbols": [s.name for s in syms], "trades": trades,
            "counts": dict(counts), "log": log, "end": end}


# ───────────────────────────── C3: случайное время ─────────────────────────────

def c3_candidates(s: Sym, cfg: Cfg = CFG) -> dict:
    """Все 15m-свечи j, после которых возможен вход по open первой минуты свечи j+1 с полным окном 481 минута."""
    b = s.b15
    j = np.arange(len(b["t"]) - 1)
    vol = s.atr15[j] / b["c"][j]
    t = b["t"][j] + M15
    i0 = np.searchsorted(s.ts, t)
    i0c = np.minimum(i0, len(s.ts) - 1)
    ie = np.minimum(i0 + cfg.hold, len(s.ts) - 1)
    full = (i0 + cfg.hold < len(s.ts)) & (s.ts[i0c] == t) & (s.ts[ie] == t + cfg.hold * MIN)
    good = b["ok"][j] & np.isfinite(vol) & full
    q1, q2 = np.quantile(vol[good], [1 / 3, 2 / 3])
    terc = np.where(vol <= q1, 0, np.where(vol <= q2, 1, 2))
    return {"j": j[good], "i0": i0c[good], "t": t[good], "terc": terc[good], "bucket": ((t[good] % DAY) // H6),
            "q": (float(q1), float(q2)), "vol": vol}


def c3_rank(trades: list[dict], syms: list[Sym], costs: Costs, cfg: Cfg = CFG, reps: int = 999,
            seed: int = 20261015) -> dict:
    tr = [x for x in trades if not x["censored"]]
    if not tr:
        return {"n": 0, "rank": None}
    by = {s.name: s for s in syms}
    cands = {nm: c3_candidates(by[nm], cfg) for nm in {x["sym"] for x in tr}}
    rng = np.random.default_rng(seed)
    Rm = np.full((len(tr), reps), np.nan)
    for k, x in enumerate(tr):
        s, c = by[x["sym"]], cands[x["sym"]]
        terc = 0 if c["vol"][x["j_sig"]] <= c["q"][0] else (1 if c["vol"][x["j_sig"]] <= c["q"][1] else 2)
        bucket = (x["entry_ts"] % DAY) // H6
        pool = np.flatnonzero((c["terc"] == terc) & (c["bucket"] == bucket))
        pick = pool[rng.integers(0, len(pool), size=reps)]
        i0 = c["i0"][pick]
        side = x["side"]
        raw = s.o[i0]
        E = entry_price(raw, side, costs)
        S = E * (1 - side * x["width"])
        tp = E + cfg.rr * (E - S)
        st = simulate(s, i0, side, raw, E, S, tp, x["B"], costs, cfg)
        R = np.where(st["ok"], st["R"], np.nan)
        Rm[k] = R
    means = np.nanmean(Rm, axis=0)
    strat = float(np.mean([x["R"] for x in tr]))
    kk = int((means >= strat).sum())
    return {"n": len(tr), "reps": reps, "seed": seed, "strategy_mean_R": strat, "random_mean_R": float(np.mean(means)),
            "random_p95_R": float(np.quantile(means, 0.95)), "k_ge": kk, "rank": (kk + 1) / (reps + 1),
            "nan_draws": int(np.isnan(Rm).sum())}


# ───────────────────────────── запуск ─────────────────────────────

LEDGER_COLS = ["eid", "sym", "side", "event_T", "touch", "confirm", "entry_ts", "raw", "E", "S", "TP", "width", "A",
               "equity", "B", "q", "per", "risk_usd", "kind", "exit_ts", "exit_raw", "X", "fee_in", "fee_out",
               "funding", "funding_n", "pnl", "R", "R_gross", "censored"]


def write_ledger(path: Path, trades: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(LEDGER_COLS + ["entry_utc", "exit_utc"])
        for x in trades:
            w.writerow([x.get(k) for k in LEDGER_COLS] + [iso(x["entry_ts"]), iso(x["exit_ts"]) if x["exit_ts"] > 0 else ""])


def main() -> None:
    sys.path.insert(0, str(HERE))
    import stats as st                                     # noqa: E402

    OUT.mkdir(exist_ok=True)
    names = ["ETHUSDT", "XRPUSDT", "BTCUSDT"]
    raw = {nm: read_minutes(nm) for nm in names}
    fund = {nm: read_funding(nm) for nm in names}
    end = min(int(raw[nm]["ts"][-1]) for nm in names) + MIN
    manifest = {"protocol": str(PROTOCOL.relative_to(ROOT)), "protocol_commit": PROTOCOL_COMMIT,
                "protocol_sha256": sha256(PROTOCOL), "replay_sha256": sha256(Path(__file__)),
                "stats_sha256": sha256(HERE / "stats.py"), "start": iso(START), "end_exclusive": iso(end),
                "inputs": {}, "funding": {}}
    syms = {}
    for nm in names:
        p = FROZEN / f"{nm}_UM_1m.csv"
        q = FROZEN / f"{nm}_funding.csv"
        f = fund[nm]
        ft = f.fundingTime.to_numpy(np.int64)
        inside = (ft > START) & (ft < end)
        gaps = Counter(int(round(x / 3_600_000)) for x in np.diff(ft[inside]))
        manifest["inputs"][nm] = {"minutes": str(p.relative_to(ROOT)), "sha256": sha256(p), **check_minutes(raw[nm])}
        manifest["funding"][nm] = {"file": str(q.relative_to(ROOT)), "sha256": sha256(q), "rows": int(len(f)),
                                   "in_period": int(inside.sum()), "first": iso(ft[0]), "last": iso(ft[-1]),
                                   "interval_hours": {str(k): v for k, v in sorted(gaps.items())},
                                   "missing_mark": int((~np.isfinite(f.markPrice.to_numpy(float))).sum()),
                                   "jitter_ms_max": int((ft % MIN).max())}
        syms[nm] = make_sym(nm, raw[nm], f, START, end)
        manifest["inputs"][nm].update(bars15=int(len(syms[nm].b15["ok"])), bars15_holes=int((~syms[nm].b15["ok"]).sum()),
                                      bars4=int(len(syms[nm].b4["ok"])), bars4_holes=int((~syms[nm].b4["ok"]).sum()))
        print(nm, manifest["inputs"][nm], manifest["funding"][nm], flush=True)

    scopes = {"PORT": ["ETHUSDT", "XRPUSDT"], "ETH": ["ETHUSDT"], "XRP": ["XRPUSDT"], "BTC": ["BTCUSDT"]}
    runs = {}
    for scope, nms in scopes.items():
        ss = [syms[nm] for nm in nms]
        for variant in ("S", "C1", "C2"):
            for costs in ((BASE, SLIP2) if variant == "S" else (BASE,)):
                key = f"{variant}_{scope}_{costs.name}"
                r = replay(ss, variant, costs, CFG, end)
                runs[key] = r
                write_ledger(OUT / f"ledger_{key}.csv", r["trades"])
                with (OUT / f"events_{key}.csv").open("w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerow(["eid", "sym", "side", "T_utc", "outcome", "at_utc"])
                    for e in r["log"]:
                        w.writerow([e["eid"], e["sym"], e["side"], iso(e["T"]), e["outcome"], iso(e["at"])])
                done = [x for x in r["trades"] if not x["censored"]]
                print(key, "n", len(done), "meanR", round(float(np.mean([x["R"] for x in done])), 4) if done else None,
                      dict(r["counts"]), flush=True)

    summary = {"manifest": manifest, "cfg": CFG.__dict__, "formalizations": FORMALIZATIONS, "runs": {}, "c3": {}}
    for key, r in runs.items():
        summary["runs"][key] = st.summarize(r["trades"], START, end, CFG.capital, r["counts"])
    for scope, nms in scopes.items():
        key = f"S_{scope}_base"
        summary["c3"][scope] = c3_rank(runs[key]["trades"], [syms[nm] for nm in nms], BASE, CFG)
        print("C3", scope, summary["c3"][scope], flush=True)
    for scope in scopes:
        summary.setdefault("status", {})[scope] = st.status(summary, scope)
    manifest["outputs"] = {p.name: sha256(p) for p in sorted(OUT.glob("*.csv"))}
    (OUT / "summary.json").write_text(json.dumps(st.jsonable(summary), ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for scope in scopes:
        print(scope, summary["status"][scope]["label"], flush=True)


if __name__ == "__main__":
    main()
