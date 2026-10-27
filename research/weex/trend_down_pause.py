"""Пауза / закрытие лонг-сеток при «падении без отката» по признакам оператора (27.10: «нет обновления хаев,
постоянное обновление лоёв, объёмы, амплитуда отличается от обычного запила, тело свечи — не угадывать, а понимать,
что происходит сейчас»). Прошлые замеры: пауза по нижним максимумам (18.10), стоп по падению (21.10), «нет тейков» и
гладкое падение (22.10) — все хуже базы; объёма и амплитуды против обычного запила в них не было.

ПРАВИЛА ДО ПРОГОНА (не менять после):
- Данные: Binance spot 1m 2017-08-17…2026-10-24 (BTC, ETH; остановки биржи заполнены fill_outages — в заполненные
  минуты нет исполнений и входов, смена режима ждёт первой торговой минуты); фандинг Binance с 09.2019.
- База — живые сетки: BTC 0.6/1.4 ордер $96, потолок $12 000, 50 лотов; B34 0.1/0.34 $48, $4 462, 61; ETH 0.6/1.4 $46,
  $2 500, 50. Ордер — фиксированные $ (объём = $ / цена уровня), шаг от нижнего открытого лота, тейк у каждого лота.
  Режим SMA100 с полосой 2% (выход при закрытии дня ниже SMA·0.98, вход выше SMA·1.02, состояние — с первого дня вне
  полосы), смена режима — закрытие по рынку. Мейкер 0.016%, тейкер 0.048% + проскальзывание 0.02%.
- Состояние «падение» на закрытии часового бара b, окно — W последних часов, ВСЕ условия:
  1) нет обновления хаев: максимум окна ниже максимума предыдущих W часов;
  2) постоянное обновление лоёв: не меньше W/2 баров окна поставили новый минимум окна; закрытие b — в нижней
     четверти размаха окна;
  3) тела: Σ|C−O| / Σ(H−L) окна ≥ 0.5, закрытие b ниже открытия окна;
  4) амплитуда: размах окна / C(b) больше k × медианы того же размаха за прошлые 30 суток;
  5) объём: сумма объёма окна больше k × медианы таких сумм за прошлые 30 суток.
  Ячейки: W ∈ {6, 12} ч, k ∈ {1.3, 1.7}.
- Действие — с первой минуты следующего часа: «пауза» — новых входов нет, лоты держат тейки; «закрыть» — все лоты по
  рынку (open минуты, тейкер + проскальзывание), затем пауза. Возобновление — первое закрытие часа выше максимума трёх
  предыдущих часов (обновление хая); вход после паузы не дороже текущей цены. Смена режима снимает паузу.
- Вариант засчитывается, только если он лучше базы в ОБЕИХ половинах (срез — средняя минута ряда) И по просадке.
  Нет такого — ответ «нет», контроль не нужен. Есть — контроль «те же паузы, сдвинутые во времени» (999 повторов).
- Итог первого прогона 27.10: 0 из 24 засчитано. «Закрыть» резало просадку на 2/3, но 2-я половина хуже во всех 12.
ДОСЧЁТ --follow (записан после первого прогона, до второго): «закрыть» как инструмент риска засчитывается, только если
  итог / просадка выше, чем у базы, в КАЖДОЙ половине — то есть лучше, чем просто торговать базу меньшим размером
  (итог и просадка базы масштабируются вместе). Просадка 2-й половины — от капитала на срезе.
  --recent=<свежий 1m> — когда состояние «падение» включалось за последние 14 суток (без выводов).
Запуск: trend_down_pause.py <BTC 1m 2017–2026> <ETH 1m 2017–2026> [--follow] [--recent=<BTC 2y>,<ETH 2y>]
"""
from __future__ import annotations

import hashlib
import sys
from array import array
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

MAKER, TAKER, SLIP = 0.00016, 0.00048, 0.0002
GRIDS = {"BTCUSDT": {"BTC 0.6/1.4": (0.6, 1.4, 96.0, 12000.0, 50), "B34 0.1/0.34": (0.1, 0.34, 48.0, 4462.0, 61)},
         "ETHUSDT": {"ETH 0.6/1.4": (0.6, 1.4, 46.0, 2500.0, 50)}}
CELLS = [(w, k) for w in (6, 12) for k in (1.3, 1.7)]
ACTIONS = ("пауза", "закрыть")
BAND = 0.02


def load(path: str, sym: str):
    raw = open(path, "rb").read()
    d = pd.read_csv(path)
    if "filled" not in d:
        d["filled"] = 0
    ms = d["ts"].to_numpy(np.int64)
    if (np.diff(ms) != 60_000).any():
        sys.exit(f"{sym}: минуты не подряд — отказ")
    print(f"{sym}: строк {len(d)}, {pd.to_datetime(ms[0], unit='ms')} … {pd.to_datetime(ms[-1], unit='ms')} UTC, "
          f"заполнено {int(d['filled'].sum())}, sha256 {hashlib.sha256(raw).hexdigest()[:16]}…", flush=True)
    ts = ms // 1000
    o, h, l, c, v = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    filled = d["filled"].to_numpy(bool)
    # режим SMA100 с полосой: решение по закрытию полного дня d действует в день d+1
    day = ts // 86400
    days, first_i, cnt = np.unique(day, return_index=True, return_counts=True)
    full = cnt == 1440
    dc = pd.Series(np.nan, index=np.arange(days[0], days[-1] + 1))
    dc.loc[days[full]] = c[(first_i + cnt - 1)[full]]
    sma = dc.rolling(100).mean()
    st, state = None, {}
    for dd, x, s in zip(dc.index, dc.to_numpy(), sma.to_numpy()):
        if np.isfinite(x) and np.isfinite(s):
            if x > s * (1 + BAND):
                st = 1
            elif x < s * (1 - BAND):
                st = 0
        state[dd + 1] = st
    reg = np.array([state.get(x) for x in day], dtype=object)
    known = np.array([r is not None for r in reg])
    start = int(np.argmax(known))
    reg = np.array([bool(r) for r in reg[start:]])
    # часовые бары и признаки
    hr = ts // 3600
    hb = pd.DataFrame({"hr": hr, "o": o, "h": h, "l": l, "c": c, "v": v}).groupby("hr").agg(
        o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"))
    H, L, O, C, V = (hb[k].to_numpy() for k in ("h", "l", "o", "c", "v"))
    hrs = hb.index.to_numpy()
    first_min = {int(x): int(i) for x, i in zip(*np.unique(hr, return_index=True))}
    res_h = np.zeros(len(H), bool)                          # закрытие часа выше максимума трёх предыдущих
    res_h[3:] = C[3:] > np.maximum.reduce([H[2:-1], H[1:-2], H[:-3]])
    trig = {}
    for w, k in CELLS:
        hs, ls = pd.Series(H), pd.Series(L)
        mxw, mnw = hs.rolling(w).max().to_numpy(), ls.rolling(w).min().to_numpy()
        prev_mx = hs.shift(w).rolling(w).max().to_numpy()
        rng = (mxw - mnw) / C
        body = pd.Series(np.abs(C - O)).rolling(w).sum().to_numpy() / np.maximum(
            pd.Series(H - L).rolling(w).sum().to_numpy(), 1e-12)
        o_w = pd.Series(O).shift(w - 1).to_numpy()
        vol = pd.Series(V).rolling(w).sum()
        med_r = pd.Series(rng).shift(1).rolling(720, min_periods=360).median().to_numpy()
        med_v = vol.shift(1).rolling(720, min_periods=360).median().to_numpy()
        vol = vol.to_numpy()
        newlow = np.zeros(len(L), int)                       # сколько баров окна поставили новый минимум окна
        for b in range(w, len(L)):
            run, n_new = L[b - w + 1], 0
            for j in range(b - w + 2, b + 1):
                if L[j] < run:
                    run, n_new = L[j], n_new + 1
            newlow[b] = n_new
        on = ((mxw < prev_mx) & (newlow >= w / 2) & (C <= mnw + 0.25 * (mxw - mnw)) & (body >= 0.5) & (C < o_w)
              & (rng > k * med_r) & (vol > k * med_v))
        on = np.nan_to_num(on, nan=False).astype(bool)
        mins = np.zeros(len(ts), bool)
        for b in np.flatnonzero(on):
            nxt = first_min.get(int(hrs[b]) + 1)
            if nxt is not None:
                mins[nxt] = True
        trig[(w, k)] = mins[start:]
        print(f"   {sym} W {w}ч k {k}: часов в состоянии «падение» {int(on.sum())} из {len(on)}", flush=True)
    res = np.zeros(len(ts), bool)
    for b in np.flatnonzero(res_h):
        nxt = first_min.get(int(hrs[b]) + 1)
        if nxt is not None:
            res[nxt] = True
    fr = pd.read_csv(f"/Users/alexeychechikov/code/bot7/backtests/frozen/{sym}_funding_full.csv")
    ft = fr["fundingTime"].to_numpy(np.int64) // 1000
    tsl = ts[start:]
    idx = np.searchsorted(tsl, ft, side="right") - 1
    ok = (idx >= 0) & (ft < tsl[-1] + 60)
    fund = {int(i): float(r) for i, r in zip(idx[ok], fr["fundingRate"].to_numpy(float)[ok])}
    print(f"   {sym}: старт {pd.to_datetime(int(tsl[0]), unit='s')} UTC, в ЛОНГЕ {reg.mean():.0%} времени, "
          f"срез половин {pd.to_datetime(int(tsl[len(tsl) // 2]), unit='s')} UTC", flush=True)
    sl = slice(start, None)
    return dict(o=o[sl], h=h[sl], l=l[sl], c=c[sl], filled=filled[sl], reg=reg, res=res[sl], trig=trig, fund=fund,
                ts=ts[sl])


def init(data):
    global D
    D = {k: (array("d", v.tobytes()) if isinstance(v, np.ndarray) and v.dtype == float else v) for k, v in data.items()}
    D["filled"] = data["filled"].tolist()
    D["reg"] = data["reg"].tolist()
    D["res"] = data["res"].tolist()
    D["trig"] = {k: set(np.flatnonzero(v).tolist()) for k, v in data["trig"].items()}
    D["res_set"] = set(np.flatnonzero(data["res"]).tolist())


def run(job):
    gname, gp, cell, action, forced = job
    step, tgt, usd, cap, max_lots = gp
    o, h, l, c = D["o"], D["h"], D["l"], D["c"]
    filled, reg, F = D["filled"], D["reg"], D["fund"]
    trig = forced if forced is not None else (D["trig"][cell] if cell else set())
    res = D["res_set"]
    g, t = step / 100, tgt / 100
    n = len(c)
    mid = n // 2
    lots: list = []                                          # [вход, тейк, объём], последний — нижний
    Q = QE = real = fee = fund = 0.0
    ref = None
    peak = dd = dd1 = 0.0
    eq_mid = 0.0
    prev = False
    defer = False
    paused = False
    fired: list = []
    paused_min = 0
    for i in range(n):
        if i == mid:
            eq_mid = real - fee - fund + (Q * c[i - 1] - QE)
            dd1, peak = dd, eq_mid                                # просадка 2-й половины — от капитала на срезе
            dd = 0.0
        if i in F:
            fund += Q * o[i] * F[i]
        act_reg = reg[i]
        if filled[i]:
            defer = defer or (prev and not act_reg)
            eq = real - fee - fund + (Q * c[i] - QE)
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
            continue
        if (prev and not act_reg) or defer:
            defer = False
            if lots:
                px = o[i] * (1 - SLIP)
                real += Q * px - QE
                fee += Q * px * TAKER
                lots, Q, QE = [], 0.0, 0.0
            ref = None
            paused = False
        if prev != act_reg:
            paused = False
        prev = act_reg
        if act_reg and action and i in trig and not paused:
            paused = True
            fired.append(i)
            if action == "закрыть" and lots:
                px = o[i] * (1 - SLIP)
                real += Q * px - QE
                fee += Q * px * TAKER
                lots, Q, QE = [], 0.0, 0.0
                ref = None
        elif paused and i in res:
            paused = False
        if paused:
            paused_min += 1
        act = act_reg and not paused
        up = c[i] >= o[i]
        for p in (o[i], l[i] if up else h[i], h[i] if up else l[i], c[i]):
            while lots and p >= lots[-1][1]:
                e, tp, q = lots.pop()
                real += q * (tp - e)
                fee += q * tp * MAKER
                Q -= q
                QE -= q * e
            if not lots:
                Q = QE = 0.0
            if not act:
                continue
            if lots:
                ref = lots[-1][0]
            elif ref is None:
                ref = p
            else:
                ref = max(ref, p)
            lvl = ref * (1 - g)
            if p <= lvl and len(lots) < max_lots:
                px_in = min(lvl, p)
                q = usd / px_in
                if max(QE, Q * p) + usd <= cap:
                    lots.append([px_in, px_in * (1 + t), q])
                    fee += usd * MAKER
                    Q += q
                    QE += usd
        eq = real - fee - fund + (Q * c[i] - QE)
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    eq = real - fee - fund + (Q * c[-1] - QE)
    return gname, cell, action, eq, eq_mid, min(dd1, dd), len(fired), paused_min / n, fired, dd1, dd


def recent(paths: str):
    for sym, path in zip(("BTCUSDT", "ETHUSDT"), paths.split(",")):
        data = load(path, sym)
        ts, reg = data["ts"], data["reg"]
        since = ts[-1] - 14 * 86400
        print(f"{sym}: последние 14 суток (до {pd.to_datetime(int(ts[-1]), unit='s')} UTC), режим сейчас "
              f"{'ЛОНГ' if reg[-1] else 'вне'}")
        for cell, mins in data["trig"].items():
            hits = [pd.to_datetime(int(ts[i]), unit="s").strftime("%d.%m %H:%M") for i in np.flatnonzero(mins)
                    if ts[i] >= since]
            print(f"   W {cell[0]}ч k {cell[1]}: срабатываний {len(hits)} — {', '.join(hits) or 'нет'}")


def follow(sym, data):
    jobs = []
    for gname, gp in GRIDS[sym].items():
        jobs.append((gname, gp, None, None, None))
        jobs += [(gname, gp, cell, "закрыть", None) for cell in CELLS]
    with ProcessPoolExecutor(max_workers=2, initializer=init, initargs=(data,)) as ex:
        out = list(ex.map(run, jobs))
    for gname in GRIDS[sym]:
        b = next(r for r in out if r[0] == gname and r[1] is None)
        b1, b2 = b[4], b[3] - b[4]
        print(f"\n=== {gname}: база 1-я {b1:+,.0f} / просадка {b[9]:+,.0f} (итог/просадка {b1 / -b[9]:.2f}); 2-я "
              f"{b2:+,.0f} / {b[10]:+,.0f} ({b2 / -b[10]:.2f})", flush=True)
        for r in out:
            if r[0] != gname or r[1] is None:
                continue
            (w, k), eq, mid, dd1, dd2 = r[1], r[3], r[4], r[9], r[10]
            e1, e2 = mid / -dd1 if dd1 < 0 else float("inf"), (eq - mid) / -dd2 if dd2 < 0 else float("inf")
            ok = e1 > b1 / -b[9] and e2 > b2 / -b[10]
            print(f"   W{w:>2}ч k{k:<4} закрыть: 1-я {mid:+,.0f} / {dd1:+,.0f} ({e1:.2f}) · 2-я {eq - mid:+,.0f} / "
                  f"{dd2:+,.0f} ({e2:.2f}) · база того же риска во 2-й: {b2 * dd2 / b[10]:+,.0f} | "
                  f"{'лучше меньшего размера в обеих' if ok else 'нет'}", flush=True)


def main():
    rec = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--recent=")), None)
    if rec:
        recent(rec)
    for sym, path in (("BTCUSDT", sys.argv[1]), ("ETHUSDT", sys.argv[2])):
        data = load(path, sym)
        if "--follow" in sys.argv:
            follow(sym, data)
            del data
            continue
        jobs = []
        for gname, gp in GRIDS[sym].items():
            jobs.append((gname, gp, None, None, None))
            jobs += [(gname, gp, cell, a, None) for cell in CELLS for a in ACTIONS]
        with ProcessPoolExecutor(max_workers=2, initializer=init, initargs=(data,)) as ex:
            out = list(ex.map(run, jobs))
        for gname in GRIDS[sym]:
            b = next(r for r in out if r[0] == gname and r[1] is None)
            print(f"\n=== {gname}: без паузы итог {b[3]:+,.0f} (1-я {b[4]:+,.0f}, 2-я {b[3] - b[4]:+,.0f}), "
                  f"просадка {b[5]:+,.0f}", flush=True)
            print(f"{'ячейка':<12} {'действие':<8} | {'итог':>8} {'Δитог':>7} {'Δ1-я':>7} {'Δ2-я':>7} | {'просадка':>8} "
                  f"{'Δпрос':>7} | {'сраб.':>5} {'в паузе':>7} | засчитан")
            for r in out:
                if r[0] != gname or r[1] is None:
                    continue
                _, (w, k), a, eq, mid, dd, nf, pf = r[:8]
                d1, d2, ddd = mid - b[4], (eq - mid) - (b[3] - b[4]), dd - b[5]
                print(f"W{w:>2}ч k{k:<5} {a:<8} | {eq:+8,.0f} {eq - b[3]:+7,.0f} {d1:+7,.0f} {d2:+7,.0f} | "
                      f"{dd:+8,.0f} {ddd:+7,.0f} | {nf:5d} {pf:7.1%} | {'ДА' if d1 > 0 and d2 > 0 and ddd > 0 else 'нет'}",
                      flush=True)
        del data


if __name__ == "__main__":
    main()
