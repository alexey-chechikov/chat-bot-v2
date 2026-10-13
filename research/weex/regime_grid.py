"""Сетка по режиму SMA100 (11.10): выше SMA100 — только лонг-сетка, ниже — только шорт-сетка; смена режима —
сторона закрывается целиком по рынку. Продолжение гейта шорта (CLAUDE.md: в ралли −$143 против −$3 180, контроль
по отрезкам пройден) на обе стороны — лонговую половину никто не проверял.

ПРАВИЛА ДО ПРОГОНА: режим дня d+1 = закрытие дня d выше/ниже SMA100 дневных закрытий (причинно). Сетка — как
fast_grid (правило GinArea: шаг от крайнего открытого лота, тейк каждого лота, лимитки по уровню, мейкер 0.016%),
ордер 0.0012 BTC, 50 ордеров, потолок $6 000 на сторону. Закрытие при смене режима — тейкер 0.048% + 0.02%.
Сравнение: постоянная сетка обе стороны; только лонг; только шорт; режим ПЕРЕВЁРНУТ (контроль знака);
контроль по отрезкам — те же отрезки режима, сторона каждому отрезку случайно (20 сидов).
Данные: BTCUSDT 1m Binance spot backtests/frozen/BTCUSDT_1m_2y.csv (15.05.2024–10.2026), режим — с 100-го дня.
Итог — полный капитал (закрыто − комиссии + мешок), половины — непрерывно, просадка — по закрытиям минут."""
from __future__ import annotations

import hashlib
import io
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fast_grid as fg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SYM = next((a for a in sys.argv[1:] if a.endswith("USDT")), "BTCUSDT")
# --src=<копия снимка>: frozen дописывается каждый час — прогон по протоколу идёт на копии (ревью скилов 12.10)
SRC = Path(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--src=")),
                ROOT / "backtests" / "frozen" / f"{SYM}_1m_2y.csv"))
QTY_ALL = {"BTCUSDT": 0.0012, "ETHUSDT": 0.04, "PAXGUSDT": 0.025, "XRPUSDT": 70.0}   # ≈ $100 на ордер
if SYM not in QTY_ALL:
    sys.exit(f"{SYM}: нет объёма по умолчанию — добавить в QTY_ALL")
_other = [s for s in QTY_ALL if s != SYM and s in SRC.name]
if _other:                                               # раунд 2 ревью: --src ETH без символа гонял BTC-ячейки
    sys.exit(f"--src {SRC.name} похож на {_other[0]}, а символ прогона {SYM} — укажи символ явно")
QTY = QTY_ALL[SYM]
N_CTL = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--ctl=")), "12"))
MAKER, TAKER, SLIP = 0.00016, 0.00048, 0.0002


def load():
    raw = SRC.read_bytes()
    d = pd.read_csv(io.BytesIO(raw))
    first, last = int(d["ts"].iloc[0]), int(d["ts"].iloc[-1])
    gaps = (last - first) // 60_000 + 1 - len(d)
    print(f"данные {SRC.name}: строк {len(d)}, {pd.to_datetime(first, unit='ms')} … {pd.to_datetime(last, unit='ms')} UTC, "
          f"пропусков минут {gaps}, sha256 {hashlib.sha256(raw).hexdigest()[:16]}…", file=sys.stderr)
    ts = (d["ts"].to_numpy() // 1000).astype(np.int64)
    o, h, l, c = (d[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    day = pd.to_datetime(ts, unit="s", utc=True).floor("D")
    dc = pd.Series(c, index=day).groupby(level=0).last()
    sma = dc.rolling(100).mean()
    up_d = (dc > sma).where(sma.notna())                 # решение на закрытии дня d
    reg_next = up_d.shift(1)                              # действует в день d+1
    reg = reg_next.reindex(day).to_numpy()                # по минутам: True лонг / False шорт / nan нет данных
    valid = ~pd.isna(reg)
    if not valid.any():
        sys.exit("нет 100 полных дней прогрева SMA100 — отказ")
    start = int(np.argmax(valid))
    if not valid[start:].all():
        sys.exit("режим с пропусками после прогрева (дыры в днях) — отказ")
    return ts[start:], o[start:], h[start:], l[start:], c[start:], reg[start:].astype(bool)


def run(args):
    name, mode, seed, step, tgt, *extra = args              # extra: объём ордера, потолок на сторону
    ts, o, h, l, c, reg = DATA
    # границы отрезков ИСХОДНОГО режима: на каждой — обязательное закрытие (11.10, разбор GPT: в контроле
    # соседние одинаковые случайные стороны сливались — меньше закрытий, другая механика выхода)
    bound = np.r_[False, reg[1:] != reg[:-1]]
    if mode in ("shuffle", "shuffle_lf"):                 # отрезкам режима — случайная сторона
        rng = np.random.default_rng(seed)
        seg = np.r_[0, np.flatnonzero(reg[1:] != reg[:-1]) + 1, len(reg)]
        reg = reg.copy()
        for a, b in zip(seg[:-1], seg[1:]):
            reg[a:b] = rng.random() < 0.5
    elif mode == "invert":
        reg = ~reg
    pts = fg.path4(o, h, l, c)
    g, t = step / 100, tgt / 100
    qty, cap = (extra[0], extra[1]) if extra else (QTY, 6000.0)
    S = {d: {"lots": [], "ref": None, "real": 0.0, "fee": 0.0} for d in (1, -1)}
    mid_i = len(ts) // 2
    eq_mid, peak, dd, flips = None, 0.0, 0.0, 0
    prev = None
    for i in range(len(ts)):
        if mode in ("regime", "invert", "shuffle"):
            act = {1: bool(reg[i]), -1: not bool(reg[i])}
        elif mode == "longflat":                          # лонг выше SMA100, иначе вне рынка (шорты — оператор)
            act = {1: bool(reg[i]), -1: False}
        elif mode == "shuffle_lf":                        # контроль для longflat: случайные отрезки лонга
            act = {1: bool(reg[i]), -1: False}
        elif mode == "both":
            act = {1: True, -1: True}
        else:
            act = {1: mode == "long", -1: mode == "short"}
        switching = mode in ("regime", "invert", "shuffle", "longflat", "shuffle_lf")
        if prev is not None and switching and bound[i]:   # граница отрезка — закрыть по рынку всё, что было
            flips += 1
            for d in (1, -1):
                if prev[d]:
                    s = S[d]
                    px = o[i] * (1 - d * SLIP)
                    for e, q, _ in s["lots"]:
                        s["real"] += d * q * (px - e)
                        s["fee"] += q * px * TAKER
                    s["lots"], s["ref"] = [], None
        prev = act
        if i == mid_i:
            pc = c[i - 1]
            eq_mid = sum(s["real"] - s["fee"] + sum(d * x[1] * (pc - x[0]) for x in s["lots"]) for d, s in S.items())
        for p in pts[i]:
            for d, s in S.items():
                if s["lots"]:
                    keep = []
                    for lot in s["lots"]:
                        e, q, tp = lot
                        if (d > 0 and p >= tp) or (d < 0 and p <= tp):
                            s["real"] += d * q * (tp - e)
                            s["fee"] += q * tp * MAKER
                        else:
                            keep.append(lot)
                    s["lots"] = keep
                if not act[d]:
                    continue
                if s["lots"]:
                    s["ref"] = min(x[0] for x in s["lots"]) if d > 0 else max(x[0] for x in s["lots"])
                elif s["ref"] is None:
                    s["ref"] = p
                else:
                    s["ref"] = max(s["ref"], p) if d > 0 else min(s["ref"], p)
                lvl = s["ref"] * (1 - d * g)
                if len(s["lots"]) < 50 and ((d > 0 and p <= lvl) or (d < 0 and p >= lvl)):
                    cost = sum(x[1] * x[0] for x in s["lots"])
                    if max(cost, sum(x[1] for x in s["lots"]) * p) + qty * lvl <= cap:
                        s["lots"].append([lvl, qty, lvl * (1 + d * t)])
                        s["fee"] += qty * lvl * MAKER
        eq = sum(s["real"] - s["fee"] + sum(d * x[1] * (c[i] - x[0]) for x in s["lots"]) for d, s in S.items())
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    side = {("лонг" if d > 0 else "шорт"): round(s["real"] - s["fee"] + sum(d * x[1] * (c[-1] - x[0]) for x in s["lots"]), 1)
            for d, s in S.items()}
    return name, mode, seed, step, tgt, eq, eq_mid, dd, flips, side


def init(data):
    global DATA
    DATA = data


def main():
    data = load()
    ts = data[0]
    print(f"окно {pd.to_datetime(ts[0], unit='s').date()} … {pd.to_datetime(ts[-1], unit='s').date()}, "
          f"доля времени выше SMA100 {data[5].mean():.0%}")
    jobs = []
    for step, tgt in ((0.6, 1.4), (0.8, 1.65)):
        for mode in ("regime", "longflat", "both", "long", "invert"):
            jobs.append((f"{step}/{tgt}", mode, 0, step, tgt))
    n_ctl = N_CTL                                          # --ctl=999 для решения (часы счёта); 12 — только ориентир
    jobs += [("0.6/1.4", "shuffle", s, 0.6, 1.4) for s in range(n_ctl)]
    jobs += [("0.6/1.4", "shuffle_lf", s, 0.6, 1.4) for s in range(n_ctl)]
    with ProcessPoolExecutor(max_workers=3, initializer=init, initargs=(data,)) as ex:
        res = list(ex.map(run, jobs))
    names = {"regime": "по режиму", "longflat": "только лонг/вне", "both": "всегда обе", "long": "всегда лонг",
             "short": "всегда шорт", "invert": "режим наоборот"}
    print(f"{'сетка':>9} {'вариант':>15} | {'итог':>8} {'1-я пол':>8} {'2-я пол':>8} | {'просадка':>9} {'смен':>5} | стороны")
    for name, mode, seed, step, tgt, eq, mid, dd, flips, side in res:
        if mode.startswith("shuffle"):
            continue
        print(f"{name:>9} {names[mode]:>15} | {eq:>+8.0f} {mid:>+8.0f} {eq - mid:>+8.0f} | {dd:>+9.0f} {flips:>5} | {side}")
    for real_mode, ctl_mode, what in (("regime", "shuffle", "лонг/шорт"), ("longflat", "shuffle_lf", "только лонг")):
        real = next(r[5] for r in res if r[1] == real_mode and r[0] == "0.6/1.4")
        sh = np.array([r[5] for r in res if r[1] == ctl_mode])
        print(f"контроль {what} (0.6/1.4, те же границы с закрытием, случайная сторона, {n_ctl} сидов): медиана "
              f"{np.median(sh):+.0f}, 10–90% {np.quantile(sh, 0.1):+.0f}…{np.quantile(sh, 0.9):+.0f}; "
              f"не хуже настоящего {int((sh >= real).sum())}/{n_ctl}; ранг (k+1)/(n+1) = "
              f"{(int((sh >= real).sum()) + 1) / (n_ctl + 1):.3f}"
              + ("" if n_ctl >= 999 else " — меньше 999 повторов: не контроль, выводов не делать"))


if __name__ == "__main__":
    main()
