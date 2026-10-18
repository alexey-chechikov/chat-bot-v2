"""Основная реализация протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (commit b048207; дополнение §7а — 6ed43ad).

Один цикл исполнения — open_trade() → step_bar() → settle() — для стратегии, C1, C2 и всех чувствительностей.
Индикаторы ATR14 и ADX14 — импорт из tools/trend_state (_atr, _adx), не копия.

Данные: P1 = backtests/frozen/<SYM>_UM_1m_early.csv, P2 = <SYM>_UM_1m.csv — один непрерывный ряд; конец — последняя
полная 4h-свеча якоря 00 UTC. Фандинг — <SYM>_funding_full.csv. sha256 входов сверяются с out/data_manifest.json
до использования (run.py).

Ускорение (без изменения правил): выход ищется по 4h-массивам; минуты сканируются только внутри свечи, где
low/high (после минуты входа) реально достаёт до аварийного триггера.
"""
from __future__ import annotations

import hashlib
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.trend_state import _adx, _atr  # noqa: E402  — индикаторы живого кода, не копия

FROZEN = ROOT / "backtests" / "frozen"
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PROTOCOL = ROOT / "docs" / "TREND_4H_RECHECK_PROTOCOL_2026-10-15.md"
PROTOCOL_COMMIT = "b048207"
ADDENDUM_COMMIT = "6ed43ad"       # §7а — дополнение про дыры XRP (только вставка раздела)

MIN = 60_000
HOUR = 3_600_000
H4 = 4 * HOUR
DAY = 24 * HOUR
P1_END = 1715731200000            # 2024-05-15 00:00 UTC — P1 строго раньше (протокол §1)
P1_START = 1577836800000          # 2020-01-01 00:00 UTC — первая минута P1 портфеля (ETH; XRP с 2020-01-06 08:21)
SYMBOLS = ("ETHUSDT", "XRPUSDT", "BTCUSDT")
DECISION = ("ETHUSDT", "XRPUSDT")
SPEC = {"ETHUSDT": (0.01, 0.001), "XRPUSDT": (0.0001, 10.0), "BTCUSDT": (0.1, 0.001)}   # (тик цены, шаг qty)

STOP, GAP, CLOSE, CENS = "emergency_stop", "gap_through_stop", "close_exit", "censored"


@dataclass(frozen=True)
class Cfg:
    lb: int = 30                  # канал: предыдущие 30 свечей
    k: float = 3.0                # Chandelier: пик ∓ K·ATR14
    adx_min: float | None = 20.0  # None — C2 «пробой без ADX»
    warmup: int = 120             # первые 120 свечей ряда — входов нет
    offset_h: int = 0             # якорь 4h-свечей, UTC-час
    delay_min: int = 0            # 0 — open первой минуты после закрытия; 5 — open шестой
    emergency: bool = True        # аварийный стоп на бирже
    buf_pct: float = 1.5          # emergency_buffer_pct
    ratchet_pct: float = 0.2      # stop_update_min_pct
    risk_usd: float = 50.0
    cap_usd: float = 3000.0
    risk_fee: float = 0.0005      # RISK_FEE живого кода — только в формуле размера и R
    taker: float = 0.00048        # тейкер на ногу
    slip: float = 0.0002          # проскальзывание на ногу против позиции

    def tag(self) -> str:
        return (f"lb{self.lb}_k{self.k:g}_adx{'none' if self.adx_min is None else f'{self.adx_min:g}'}"
                f"_off{self.offset_h}_d{self.delay_min}_em{int(self.emergency)}_slip{self.slip:g}")


BASE = Cfg()

# Формализации — записаны ДО первого расчёта. Протокол не меняется; неоднозначности решены здесь.
FORMALIZATIONS = [
    "R1. «Позиция» — позиция бэктеста: после аварийного стопа или пропуска входа позиции нет, и вход ищется со "
    "следующей свечи (свеча выхода исключена). Живой сервис сигналов держит эпизод до выхода по закрытию; такие "
    "повторные входы внутри ещё живого эпизода считаются отдельно (диагностика, не ворота).",
    "R2. Минута входа — первая СУЩЕСТВУЮЩАЯ минута с ts ≥ закрытие свечи сигнала (+5 мин в варианте задержки). "
    "Если её нет (конец данных) — входа нет, считается «data_end».",
    "R3. Неполная 4h-свеча (<240 валидных минут) остаётся в ряду индикаторов; пик, Chandelier и храповик "
    "аварийного стопа на ней обновляются как на любой свече ряда; сигнал входа и выход по закрытию на ней не "
    "исполняются (выход откладывается до следующей полной свечи, если условие ещё выполнено); аварийный стоп внутри "
    "неё проверяется по имеющимся минутам.",
    "R4. Аварийный стоп: в свече входа проверяются только минуты после минуты входа, далее — все минуты свечи. "
    "LONG: low ≤ триггер → исполнение min(триггер, open минуты), затем × (1 − проскальзывание); SHORT зеркально. "
    "Тип «gap_through_stop» — когда open минуты строго за триггером, иначе «emergency_stop».",
    "R5. Триггер = round_tick(Chandelier·(1 ∓ 1.5%)) как services/weex_grid/engine.round_tick: LONG — вниз "
    "(floor(n + 1e-9)), SHORT — вверх (ceil(n − 1e-9)), round(·, 8).",
    "R6. Храповик: |сдвиг| считается как в живом коде d·(Ch_j − Ch_учт)/Ch_учт·100 ≥ 0.2; новый триггер — от Ch_j; "
    "учтённым становится Ch_j. Выход по закрытию сверяется с текущим Ch_j.",
    "R7. qty = floor(q/шаг + 1e-9)·шаг (как _qty_str живого кода), q = min(50/(|E − триггер₀| + 2·0.0005·E), "
    "3000/E); qty < шага → пропуск «qty0».",
    "R8. Проскальзывание — множитель к цене (вход E·(1 + d·0.0002), выход X·(1 − d·0.0002)); комиссия 0.048% — от "
    "цены исполнения с проскальзыванием.",
    "R9. Фандинг: время начисления округляется вниз до минуты (метки плавают ≤ 47 мс); учитывается при "
    "entry_ts < T ≤ exit_ts, где entry_ts/exit_ts — метки минут исполнения. Нет markPrice → close минуты T "
    "(если её нет — последний close до T).",
    "R10. Выход по закрытию на последней свече данных (нет следующей минуты) и позиция на конец данных — censored: "
    "оценка по последнему close, комиссия входа и фандинг до конца данных, без комиссии и проскальзывания выхода; "
    "в n не входит. Сигнал на последней свече — «data_end».",
    "R11. Конец данных — конец последней полной 4h-свечи якоря 00 UTC (у всех трёх символов 2026-10-14 20:00). "
    "Для смещений якоря 01/02/03 — свечи этого якоря внутри тех же минут; хвостовые неполные свечи отбрасываются.",
    "R12. Отнесение к периоду — по метке минуты входа: P1 < 2024-05-15 00:00 UTC ≤ P2.",
    "R13. Трети P1 — календарные трети [2020-01-01 00:00, 2024-05-15 00:00) UTC (первая минута P1 портфеля — ETH): "
    "по 532 дня, границы 2021-06-16 00:00 и 2022-11-30 00:00; одни и те же для всех символов и вариантов.",
    "R14. «> 0» в воротах — среднее R завершённых (не censored) сделок.",
    "R15. Бутстрап: блоки — все календарные ISO-недели P1 (пустые тоже), в повторе среднее = ΣR/Σn выбранных "
    "недель; 9 999 повторов, seed 20261015; ДИ — перцентили 2.5/97.5. Непустые недели — отдельной строкой.",
    "R16. C1: кандидаты — полные свечи с индексом ≥ 120, исполнение которых даёт сделку (не пропуск); страта — "
    "(сторона, период по времени входа, UTC-час закрытия свечи, терциль ATR14/close по всем свечам ряда с ATR). "
    "Шаблоны — все исполненные входы стратегии по символу (P1 и P2) по времени. «Одна позиция»: интервал "
    "[свеча кандидата, свеча выхода] не пересекается с уже поставленными контрольными позициями (кандидат — после "
    "выхода предшествующей ему по времени контрольной позиции и выходит до следующей); равномерный выбор среди "
    "допустимых; нет допустимых — вход выпадает. Буквальный последовательный вариант (кандидат только позже выхода "
    "предыдущей по порядку шаблонов) — диагностика: он сдвигает кандидатов к концу периода. Ранг ворот 7 — по "
    "среднему R завершённых контрольных сделок ETH+XRP на P1; один генератор seed 20261015 на все 999 повторов.",
    "R17. Совместная кривая капитала — на закрытиях 4h-свечей (объединение меток ETH и XRP): закрытые сделки + "
    "плавающий результат открытых по close (с комиссией входа и начисленным фандингом); закрытая сделка "
    "добавляется на первой метке ≥ времени выхода. Просадка — по кривой сделок периода на всей оси времени.",
    "R18. Вариант без аварийного стопа: размер и знаменатель R — те же (по триггеру₀), меняется только выход.",
    "R19. XRP: 7 200 минут дыр в архивах (2022-02-26…28, 2022-04-01…02) не заполнены; свечи без минут выпадают "
    "из ряда (resample + dropna), частично покрытые — неполные.",
    "R20. $ — сумма net PnL сделок с размером по правилу (риск $50, потолок $3 000); дополнительно 50·ΣR.",
    "R21. §7а (дополнение 6ed43ad; записано после него, до расчёта заполненного ряда): ряд XRP с 5 днями из дневных "
    "архивов строится только в памяти (research/trend_recheck/xrp_fill.py; вставка только в дыры, соседние дни "
    "сверены с месячными архивами); на нём пересчитан ВЕСЬ конвейер — база, ×2, C1 (999, seed 20261015), C2, 16 ячеек, "
    "якоря, задержка, без стопа, трети, бутстрап; ETH и BTC — те же минуты. Ворота и статус — только по основному "
    "расчёту; значения ворот по заполненному ряду показываются для сведения.",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def iso(ts: int) -> str:
    return pd.Timestamp(int(ts), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")


def round_away(px: float, tick: float, d: int) -> float:
    """Триггер к тику в сторону от цены — как services/weex_grid/engine.round_tick(px, tick, up=d < 0)."""
    n = px / tick
    n = math.ceil(n - 1e-9) if d < 0 else math.floor(n + 1e-9)
    return round(n * tick, 8)


def size_qty(E: float, trig: float, step: float, cfg: Cfg) -> float:
    q = min(cfg.risk_usd / (abs(E - trig) + 2 * cfg.risk_fee * E), cfg.cap_usd / E)
    return round(math.floor(q / step + 1e-9) * step, 8)


def valid_mask(o, h, l, c, v) -> np.ndarray:
    """Векторный scripts/ohlc_grid.valid_bar: конечные, 0 < low ≤ min(open, close), high ≥ max(open, close), объём ≥ 0."""
    fin = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & np.isfinite(v)
    with np.errstate(invalid="ignore"):
        return fin & (l > 0) & (l <= np.minimum(o, c)) & (h >= np.maximum(o, c)) & (v >= 0)


# ---------------------------------------------------------------- данные
def read_minutes(sym: str) -> dict:
    """P1 + P2 одним рядом. Проверки: строго по возрастанию, только сетка k·60 000, шов без дыр и наложений."""
    cols = ["ts", "open", "high", "low", "close", "volume"]
    dt = {"ts": np.int64, "open": float, "high": float, "low": float, "close": float, "volume": float}
    a = pd.read_csv(FROZEN / f"{sym}_UM_1m_early.csv", usecols=cols, dtype=dt)
    b = pd.read_csv(FROZEN / f"{sym}_UM_1m.csv", usecols=cols, dtype=dt)
    if not (int(a["ts"].iloc[-1]) < P1_END <= int(b["ts"].iloc[0])):
        raise SystemExit(f"{sym}: P1 должен кончаться до 2024-05-15, P2 — начинаться с неё")
    if int(b["ts"].iloc[0]) - int(a["ts"].iloc[-1]) != MIN:
        raise SystemExit(f"{sym}: на шве P1/P2 пропуск или наложение")
    d = pd.concat([a, b], ignore_index=True)
    ts = d["ts"].to_numpy(np.int64)
    if np.any(np.diff(ts) <= 0) or np.any(ts % MIN):
        raise SystemExit(f"{sym}: минуты не по сетке или не по возрастанию")
    return {"ts": ts, "o": d["open"].to_numpy(float), "h": d["high"].to_numpy(float),
            "l": d["low"].to_numpy(float), "c": d["close"].to_numpy(float), "v": d["volume"].to_numpy(float),
            "p1_rows": len(a), "p2_rows": len(b)}


def read_funding(sym: str) -> pd.DataFrame:
    return pd.read_csv(FROZEN / f"{sym}_funding_full.csv",
                       dtype={"fundingTime": np.int64, "fundingRate": float, "markPrice": float})


def bars_from_minutes(ts, o, h, l, c, valid, offset_h: int) -> dict:
    off = offset_h * HOUR
    b = (ts - off) // H4
    mi0 = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    mi1 = np.r_[mi0[1:], len(ts)]
    cnt = mi1 - mi0
    nval = np.add.reduceat(valid.astype(np.int64), mi0)
    return {"start": b[mi0] * H4 + off, "mi0": mi0, "mi1": mi1, "o": o[mi0], "c": c[mi1 - 1],
            "h": np.maximum.reduceat(h, mi0), "l": np.minimum.reduceat(l, mi0),
            "complete": (cnt == 240) & (nval == 240), "n_min": cnt}


def data_end_ms(ts, o, h, l, c, valid) -> int:
    """Конец последней полной 4h-свечи якоря 00 UTC (R11)."""
    bb = bars_from_minutes(ts, o, h, l, c, valid, 0)
    last = int(np.flatnonzero(bb["complete"])[-1])
    return int(bb["start"][last]) + H4


class Series:
    """Минуты + 4h-свечи одного якоря + индикаторы живого кода + фандинг."""

    def __init__(self, sym: str, ts, o, h, l, c, v, offset_h: int = 0, funding: pd.DataFrame | None = None,
                 end_ms: int | None = None, tick: float | None = None, step: float | None = None):
        self.sym = sym
        self.offset_h = offset_h
        self.tick, self.step = (tick, step) if tick is not None else SPEC[sym]
        valid = valid_mask(o, h, l, c, v)
        if end_ms is not None:
            n = int(np.searchsorted(ts, end_ms, "left"))
            ts, o, h, l, c, v, valid = ts[:n], o[:n], h[:n], l[:n], c[:n], v[:n], valid[:n]
        bb = bars_from_minutes(ts, o, h, l, c, valid, offset_h)
        comp = np.flatnonzero(bb["complete"])
        if len(comp) == 0:
            raise ValueError("нет ни одной полной свечи")
        keep = int(comp[-1]) + 1                         # хвостовые неполные свечи отбрасываются (R11)
        if keep < len(bb["start"]):
            bb = {k: v_[:keep] for k, v_ in bb.items()}
        n = int(bb["mi1"][-1])
        self.ts, self.o, self.h, self.l, self.c = ts[:n], o[:n], h[:n], l[:n], c[:n]
        self.valid = valid[:n]
        self.n_min = n
        self.bstart = bb["start"]
        self.bend = bb["start"] + H4
        self.mi0, self.mi1 = bb["mi0"], bb["mi1"]
        self.bo, self.bh, self.bl, self.bc = bb["o"], bb["h"], bb["l"], bb["c"]
        self.complete = bb["complete"]
        self.bars_n_min = bb["n_min"]
        self.nb = len(self.bstart)
        df = pd.DataFrame({"high": self.bh, "low": self.bl, "close": self.bc})
        self.atr = _atr(df).to_numpy(float)
        self.adx = _adx(df)[0].to_numpy(float)
        self._chan: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.data_end = int(self.bend[-1])
        self._set_funding(funding)

    def channel(self, lb: int) -> tuple[np.ndarray, np.ndarray]:
        if lb not in self._chan:
            hh = pd.Series(self.bh).rolling(lb).max().shift(1).to_numpy(float)
            ll = pd.Series(self.bl).rolling(lb).min().shift(1).to_numpy(float)
            self._chan[lb] = (hh, ll)
        return self._chan[lb]

    def _set_funding(self, f: pd.DataFrame | None) -> None:
        if f is None or len(f) == 0:
            self.f_t = np.zeros(0, np.int64)
            self.f_rate = np.zeros(0)
            self.f_mark = np.zeros(0)
            self.f_mark_from_close = 0
            return
        t = f["fundingTime"].to_numpy(np.int64) // MIN * MIN        # R9: вниз до минуты
        rate = f["fundingRate"].to_numpy(float)
        mark = f["markPrice"].to_numpy(float).copy()
        sel = (t > self.ts[0]) & (t <= self.data_end)
        t, rate, mark = t[sel], rate[sel], mark[sel]
        miss = ~np.isfinite(mark) | (mark <= 0)
        idx = np.searchsorted(self.ts, t, "right") - 1              # минута T или последняя до неё
        mark[miss] = self.c[np.clip(idx[miss], 0, None)]
        self.f_t, self.f_rate, self.f_mark = t, rate, mark
        self.f_mark_from_close = int(miss.sum())

    def funding(self, d: int, qty: float, t_in: int, t_out: int) -> tuple[float, int]:
        a = int(np.searchsorted(self.f_t, t_in, "right"))
        b = int(np.searchsorted(self.f_t, t_out, "right"))
        if b <= a:
            return 0.0, 0
        return float(-d * qty * np.dot(self.f_mark[a:b], self.f_rate[a:b])), b - a

    def bar_of_minute(self, mi: int) -> int:
        return int(np.searchsorted(self.mi0, mi, "right")) - 1


def load_series(sym: str, offset_h: int = 0, minutes: dict | None = None) -> Series:
    m = minutes if minutes is not None else read_minutes(sym)
    valid = valid_mask(m["o"], m["h"], m["l"], m["c"], m["v"])
    end = data_end_ms(m["ts"], m["o"], m["h"], m["l"], m["c"], valid)
    return Series(sym, m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], offset_h=offset_h,
                  funding=read_funding(sym), end_ms=end)


# ---------------------------------------------------------------- цикл исполнения
@dataclass
class Pos:
    i: int                  # свеча сигнала
    d: int                  # +1 LONG, −1 SHORT
    mi: int                 # индекс минуты входа
    entry_ts: int
    E: float                # open минуты входа без проскальзывания
    ch0: float
    trig0: float
    qty: float
    peak: float
    last_ch: float          # учтённый храповиком Chandelier
    trig: float             # действующий аварийный триггер
    ch: float = float("nan")
    n_ratchet: int = 0
    deferred: int = 0       # выходов, отложенных из-за неполной свечи
    incomplete_seen: int = 0
    exit_at_end: bool = False
    extra: dict = field(default_factory=dict)


def open_trade(S: Series, i: int, d: int, cfg: Cfg) -> Pos | str:
    peak = float(S.bh[i]) if d > 0 else float(S.bl[i])
    ch0 = peak - d * cfg.k * float(S.atr[i])
    mi = int(np.searchsorted(S.ts, int(S.bend[i]) + cfg.delay_min * MIN, "left"))
    if mi >= S.n_min:
        return "data_end"
    E = float(S.o[mi])
    if d * (E - ch0) <= 0:
        return "beyond_chandelier"                    # живой «пропуск: цена уже за стопом»
    trig = round_away(ch0 * (1 - d * cfg.buf_pct / 100), S.tick, d)
    qty = size_qty(E, trig, S.step, cfg)
    if qty < S.step - 1e-12:
        return "qty0"
    return Pos(i=i, d=d, mi=mi, entry_ts=int(S.ts[mi]), E=E, ch0=ch0, trig0=trig, qty=qty, peak=peak,
               last_ch=ch0, trig=trig, ch=ch0)


def step_bar(S: Series, p: Pos, j: int, cfg: Cfg) -> tuple | None:
    """Свеча j открытой позиции: сначала аварийный стоп по минутам, затем закрытие. → (тип, цена, минута) или None."""
    d = p.d
    m0, s1 = int(S.mi0[j]), int(S.mi1[j])
    s0 = max(m0, p.mi + 1)
    if cfg.emergency and s0 < s1:
        trig = p.trig
        if d > 0:
            ext = float(S.bl[j]) if s0 == m0 else float(S.l[s0:s1].min())
            if ext <= trig:
                k = s0 + int(np.argmax(S.l[s0:s1] <= trig))
                op = float(S.o[k])
                return (GAP if op < trig else STOP), min(trig, op), k
        else:
            ext = float(S.bh[j]) if s0 == m0 else float(S.h[s0:s1].max())
            if ext >= trig:
                k = s0 + int(np.argmax(S.h[s0:s1] >= trig))
                op = float(S.o[k])
                return (GAP if op > trig else STOP), max(trig, op), k
    p.peak = max(p.peak, float(S.bh[j])) if d > 0 else min(p.peak, float(S.bl[j]))
    ch = p.peak - d * cfg.k * float(S.atr[j])
    p.ch = ch
    if not S.complete[j]:
        p.incomplete_seen += 1
    if int(S.bend[j]) > p.entry_ts and d * (float(S.bc[j]) - ch) < 0:
        if S.complete[j]:
            k = s1                                    # первая минута после закрытия свечи j
            if k >= S.n_min:
                p.exit_at_end = True                  # R10: следующей минуты нет — censored
                return None
            return CLOSE, float(S.o[k]), k
        p.deferred += 1                               # R3: на неполной свече выход не исполняется
    if d * (ch - p.last_ch) / p.last_ch * 100 >= cfg.ratchet_pct:
        p.last_ch = ch
        p.trig = round_away(ch * (1 - d * cfg.buf_pct / 100), S.tick, d)
        p.n_ratchet += 1
    return None


def settle(S: Series, p: Pos, kind: str, xraw: float, k_exit: int | None, j_exit: int, cfg: Cfg) -> dict:
    d, q, E = p.d, p.qty, p.E
    ef = E * (1 + d * cfg.slip)
    fee_in = ef * q * cfg.taker
    if kind == CENS:
        xf, fee_out, t_out = xraw, 0.0, S.data_end
    else:
        xf = xraw * (1 - d * cfg.slip)
        fee_out = xf * q * cfg.taker
        t_out = int(S.ts[k_exit])
    gross = d * q * (xf - ef)
    fund, nf = S.funding(d, q, p.entry_ts, t_out)
    net = gross - fee_in - fee_out + fund
    risk = q * (abs(E - p.trig0) + 2 * cfg.risk_fee * E)
    return {"sym": S.sym, "side": "LONG" if d > 0 else "SHORT", "d": d, "signal_bar": int(S.bstart[p.i]),
            "entry_ts": p.entry_ts, "exit_ts": t_out, "E": E, "entry_fill": ef, "ch0": p.ch0, "trig0": p.trig0,
            "qty": q, "exit_raw": xraw, "exit_fill": xf, "kind": kind, "exit_bar": j_exit,
            "signal_bar_idx": p.i, "gross": gross, "fee_in": fee_in, "fee_out": fee_out, "funding": fund,
            "funding_n": nf, "net": net, "risk": risk, "R": net / risk, "R_gross": d * q * (xraw - E) / risk,
            "censored": kind == CENS, "period": "P1" if p.entry_ts < P1_END else "P2", "n_ratchet": p.n_ratchet,
            "deferred_exits": p.deferred, "incomplete_bars_in_trade": p.incomplete_seen,
            "last_trig": p.trig, "exit_signal_at_end": p.exit_at_end}


def simulate_from(S: Series, p: Pos, cfg: Cfg) -> dict:
    """Позиция от свечи после сигнала до выхода или конца данных."""
    for j in range(p.i + 1, S.nb):
        r = step_bar(S, p, j, cfg)
        if r is not None:
            kind, px, k = r
            return settle(S, p, kind, px, k, j, cfg)
    return settle(S, p, CENS, float(S.c[S.n_min - 1]), None, S.nb - 1, cfg)


def run(S: Series, cfg: Cfg = BASE, events: list | None = None) -> dict:
    """Стратегия на всём ряду. → {"trades": [...], "funnel": {...}}"""
    hh, ll = S.channel(cfg.lb)
    funnel = {"signals": 0, "entered": 0, "skip_beyond_chandelier": 0, "skip_qty0": 0, "skip_data_end": 0,
              "signal_on_incomplete_bar": 0, "incomplete_bars_total": int((~S.complete).sum()),
              "incomplete_bars_after_warmup": int((~S.complete[cfg.warmup:]).sum()),
              "deferred_close_exits": 0, "trades_with_incomplete_bars": 0, "exit_signal_at_data_end": 0}
    trades: list[dict] = []
    pos: Pos | None = None
    for j in range(S.nb):
        if pos is not None:
            r = step_bar(S, pos, j, cfg)
            if r is not None:
                kind, px, k = r
                trades.append(settle(S, pos, kind, px, k, j, cfg))
                if events is not None:
                    events.append({"ts": int(S.ts[k]), "event": "exit", "kind": kind, "side": trades[-1]["side"],
                                   "price": px, "bar": int(S.bstart[j])})
                pos = None
            continue                                   # на свече выхода новый вход не ищется
        if j < cfg.warmup:
            continue
        adx_ok = cfg.adx_min is None or float(S.adx[j]) >= cfg.adx_min
        if not adx_ok:
            continue
        c = float(S.bc[j])
        if c > hh[j]:
            d = 1
        elif c < ll[j]:
            d = -1
        else:
            continue
        if not S.complete[j]:
            funnel["signal_on_incomplete_bar"] += 1
            if events is not None:
                events.append({"ts": int(S.bend[j]), "event": "signal_on_incomplete_bar",
                               "side": "LONG" if d > 0 else "SHORT", "bar": int(S.bstart[j])})
            continue
        funnel["signals"] += 1
        p = open_trade(S, j, d, cfg)
        if isinstance(p, str):
            funnel[f"skip_{p}"] += 1
            if events is not None:
                events.append({"ts": int(S.bend[j]), "event": f"skip_{p}", "side": "LONG" if d > 0 else "SHORT",
                               "bar": int(S.bstart[j])})
            continue
        funnel["entered"] += 1
        if events is not None:
            events.append({"ts": p.entry_ts, "event": "entry", "side": "LONG" if d > 0 else "SHORT", "price": p.E,
                           "bar": int(S.bstart[j]), "chandelier0": p.ch0, "trigger0": p.trig0, "qty": p.qty})
        pos = p
    if pos is not None:
        trades.append(settle(S, pos, CENS, float(S.c[S.n_min - 1]), None, S.nb - 1, cfg))
        if events is not None:
            events.append({"ts": S.data_end, "event": "censored", "side": trades[-1]["side"],
                           "price": trades[-1]["exit_raw"]})
    for t in trades:
        funnel["deferred_close_exits"] += t["deferred_exits"]
        funnel["trades_with_incomplete_bars"] += int(t["incomplete_bars_in_trade"] > 0)
        funnel["exit_signal_at_data_end"] += int(t["exit_signal_at_end"])
    return {"trades": trades, "funnel": funnel}


def live_episodes(S: Series, cfg: Cfg = BASE) -> list[tuple[int, int, int]]:
    """Машина сервиса сигналов (tools/trend_state.analyze на закрытых свечах): только выход по закрытию, без
    аварийного стопа и пропусков. → [(свеча сигнала, сторона, свеча выхода или −1)] — для диагностики R1."""
    hh, ll = S.channel(cfg.lb)
    eps: list[list[int]] = []
    pos = None
    for j in range(S.nb):
        if pos is not None:
            d = pos[1]
            pos[2] = max(pos[2], float(S.bh[j])) if d > 0 else min(pos[2], float(S.bl[j]))
            ch = pos[2] - d * cfg.k * float(S.atr[j])
            if S.complete[j] and d * (float(S.bc[j]) - ch) < 0:
                eps.append([pos[0], d, j])
                pos = None
            continue
        if j < cfg.warmup or not S.complete[j]:
            continue
        if cfg.adx_min is not None and not float(S.adx[j]) >= cfg.adx_min:
            continue
        hj, lj, c = hh[j], ll[j], float(S.bc[j])
        if c > hj:
            pos = [j, 1, float(S.bh[j])]
        elif c < lj:
            pos = [j, -1, float(S.bl[j])]
    if pos is not None:
        eps.append([pos[0], pos[1], -1])
    return [tuple(e) for e in eps]


# ---------------------------------------------------------------- C1
def c1_candidates(S: Series, cfg: Cfg = BASE) -> dict:
    """Все полные свечи c ≥ прогрева × обе стороны: исход контрольной сделки тем же циклом исполнения."""
    x = S.atr / S.bc
    ok = np.isfinite(x)
    q1, q2 = np.quantile(x[ok], [1 / 3, 2 / 3])
    terc = np.where(x <= q1, 0, np.where(x <= q2, 1, 2))
    hour = (S.bend // HOUR) % 24
    rows = []
    for c in range(cfg.warmup, S.nb):
        if not S.complete[c] or not ok[c]:
            continue
        for d in (1, -1):
            p = open_trade(S, c, d, cfg)
            if isinstance(p, str):
                continue
            t = simulate_from(S, p, cfg)
            rows.append((c, d, t["exit_bar"], t["R"], t["net"], int(t["censored"]), t["entry_ts"],
                         0 if t["entry_ts"] < P1_END else 1, int(hour[c]), int(terc[c]), t["R_gross"]))
    arr = np.array(rows, dtype=float) if rows else np.zeros((0, 11))
    return {"rows": arr, "terciles": (float(q1), float(q2)), "terc": terc, "hour": hour}


def c1_strata(cand: dict) -> dict:
    a = cand["rows"]
    out: dict[tuple, dict] = {}
    if len(a) == 0:
        return out
    keys = np.stack([a[:, 1], a[:, 7], a[:, 8], a[:, 9]], axis=1).astype(int)
    for key in {tuple(k) for k in keys.tolist()}:
        sel = np.all(keys == np.array(key), axis=1)
        sub = a[sel]
        order = np.argsort(sub[:, 0], kind="stable")
        sub = sub[order]
        out[key] = {"c": sub[:, 0].astype(np.int64), "x": sub[:, 2].astype(np.int64), "R": sub[:, 3],
                    "net": sub[:, 4], "cens": sub[:, 5].astype(bool), "period": sub[:, 7].astype(int)}
    return out


def template_keys(S: Series, trades: list[dict], cand: dict) -> list[tuple]:
    out = []
    for t in sorted(trades, key=lambda z: z["entry_ts"]):
        c = t["signal_bar_idx"]
        out.append((int(t["d"]), 0 if t["entry_ts"] < P1_END else 1, int(cand["hour"][c]), int(cand["terc"][c])))
    return out


def c1_replicate(strata: dict, keys: list[tuple], rng: np.random.Generator, literal: bool = False,
                 independent: bool = False) -> list[tuple]:
    """Один повтор C1 по одному символу. → [(R, net, censored, period, длительность в свечах)] поставленных
    контрольных сделок + число выпавших. R16 — без наложения; literal — буквальный последовательный (диагностика);
    independent — без ограничения одной позиции (диагностика смещения R16 по длительности сделки)."""
    starts = np.zeros(0, np.int64)
    ends = np.zeros(0, np.int64)
    last_exit = -1
    got, dropped = [], 0
    for key in keys:
        st = strata.get(key)
        if st is None:
            dropped += 1
            continue
        if independent:
            feas = np.arange(len(st["c"]))
        elif literal:
            feas = np.flatnonzero(st["c"] > last_exit)
        else:
            if len(starts):
                idx = np.searchsorted(starts, st["c"], "left")
                prev_end = np.where(idx > 0, ends[np.maximum(idx - 1, 0)], -1)
                next_start = np.where(idx < len(starts), starts[np.minimum(idx, len(starts) - 1)], np.iinfo(np.int64).max)
                feas = np.flatnonzero((prev_end < st["c"]) & (st["x"] < next_start))
            else:
                feas = np.arange(len(st["c"]))
        if len(feas) == 0:
            dropped += 1
            continue
        k = int(feas[rng.integers(len(feas))])
        c, x = int(st["c"][k]), int(st["x"][k])
        got.append((float(st["R"][k]), float(st["net"][k]), bool(st["cens"][k]), int(st["period"][k]), x - c))
        if independent:
            continue
        if literal:
            last_exit = x
        else:
            pos = int(np.searchsorted(starts, c))
            starts = np.insert(starts, pos, c)
            ends = np.insert(ends, pos, x)
    return got, dropped
