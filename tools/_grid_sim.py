"""GinArea INDICATOR GRID simulator (Win R&D) — unified LONG/SHORT + instop + regime gate.

Validated: clean-trend edge 0.292% ~ anchor 0.295% (volume = one-side notional). No cumulative
stop -> realized edge ≡ target-min_stop when closed; chop/DN drag = open negative bag at snapshot
-> RISK metric = MAX-BAG (worst unrealized inside the window). Gate = price vs red line (TEMA200
4h): full-cycle апр'25→фев'26 turned −272 LOSS into +63 with −89% max-bag, −19% harvest.

This file: unified sim(side), instop (Semantic A: open on the reversal, not every tick -> real
order count -> absolute $), short gate (mirror close<t200), and absolute calibration vs anchors.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC1m = ROOT / "backtests" / "frozen" / "BTCUSDT_1m_2y.csv"


def load_1m(a, b):
    df = pd.read_csv(SRC1m)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts").loc[a:b]


def tema(s, nn):
    e1 = s.ewm(span=nn, adjust=False).mean(); e2 = e1.ewm(span=nn, adjust=False).mean()
    e3 = e2.ewm(span=nn, adjust=False).mean(); return 3 * e1 - 3 * e2 + e3


def build_allow(close_1m, side="long", hold=2, band=0.0, tf="4h"):
    """1m gate mask around the red line TEMA200(`tf`) with a FLAT BAND.
    LONG allowed while close > t200*(1-band%); SHORT while close < t200*(1+band%).
    Inside ±band BOTH sides are allowed (FLAT harvest). Outside it, only the trend side ->
    the counter ('losing') side gets disallowed and (with close_on_disallow) is closed.
    tf='1h' = faster regime (earlier flips, more whipsaw); '4h' = slower/cleaner."""
    c = close_1m.resample(tf).last().dropna()
    t200 = tema(c, 200)
    held = lambda b: (b.astype(int).groupby((~b).cumsum()).cumsum() >= hold)
    cond = (c > t200 * (1 - band / 100)) if side == "long" else (c < t200 * (1 + band / 100))
    allow4h = held(cond)
    # CAUSAL: resample labels the bin by its START but holds the END close. Shift the mask by
    # +tf so a bin's regime applies only to 1m bars AFTER the bin closed (no lookahead).
    shifted = pd.Series(allow4h.to_numpy(), index=c.index + pd.Timedelta(tf))
    return shifted.reindex(close_1m.index, method="ffill").fillna(False).astype(bool).to_numpy()


def sim(close, side="long", step=0.04, target=0.30, min_stop=0.008, size0=0.001,
        order_mult=1.0, max_orders=600, dip_thr=1.0, ind_win=30, instop=0.05,
        fee_bps=0.0, restart=True, allow=None, close_on_disallow=False, close_mask=None):
    """Unified grid. side=long accumulates on dips / profits up; short = mirror.
    instop (Semantic A): after price passes a grid level, open the IN only on the reversal
    (>= instop% bounce from the local extremum) -> one IN per swing, not per tick = real count."""
    c = close.to_numpy(float); n = len(c)
    d = 1 if side == "long" else -1
    step /= 100; target /= 100; min_stop /= 100; dip_thr /= 100; instop /= 100
    realized = 0.0; volume = 0.0; max_bag = 0.0
    positions = []
    started = False; last_in = None; level = 0; cur_step = step
    pending = False; swing = None
    for i in range(ind_win, n):
        px = c[i]
        # close INs that reached target (profit = target-min_stop)
        still = []
        for p in positions:
            hit = px >= p["entry"] * (1 + target) if d > 0 else px <= p["entry"] * (1 - target)
            if hit:
                realized += p["size"] * p["entry"] * (target - min_stop)
                realized -= fee_bps / 1e4 * p["size"] * px
            else:
                still.append(p)
        positions = still
        cur_unreal = sum(p["size"] * (px - p["entry"]) * d for p in positions)
        if cur_unreal < max_bag:
            max_bag = cur_unreal
        gate_ok = allow is None or allow[i]
        # CLOSE THE LOSING SIDE only when the move is OBVIOUS (price far past the line = close_mask),
        # OR (legacy) on any disallow. Near the line (chop) close_mask is False -> both legs harvest.
        force_close = (close_on_disallow and not gate_ok) or (close_mask is not None and close_mask[i])
        if force_close and positions:
            for p in positions:
                realized += p["size"] * (px - p["entry"]) * d
                realized -= fee_bps / 1e4 * p["size"] * px
            positions = []
            started = False; last_in = None; level = 0; pending = False
        # start cycle on indicator (long: dip>=thr; short: pump>=thr)
        if not started and len(positions) == 0:
            mv = c[i] / c[i - ind_win] - 1
            trig = (mv <= -dip_thr) if d > 0 else (mv >= dip_thr)
            if gate_ok and trig:
                positions.append({"entry": px, "size": size0}); volume += size0 * px
                realized -= fee_bps / 1e4 * size0 * px
                last_in = px; level = 1; started = True; cur_step = step
                pending = False; swing = px
            continue
        # accumulate against the bot (long: price down; short: price up) with instop reversal
        adverse = px <= last_in * (1 - cur_step) if d > 0 else px >= last_in * (1 + cur_step)
        if started and gate_ok and len(positions) < max_orders and last_in is not None:
            if adverse:
                pending = True
                swing = px if swing is None else (min(swing, px) if d > 0 else max(swing, px))
            if pending:
                swing = (min(swing, px) if d > 0 else max(swing, px))
                bounce = px >= swing * (1 + instop) if d > 0 else px <= swing * (1 - instop)
                if bounce:
                    positions.append({"entry": px, "size": size0}); volume += size0 * px
                    realized -= fee_bps / 1e4 * size0 * px
                    last_in = px; level += 1; cur_step = min(cur_step * order_mult, 0.5)
                    pending = False; swing = px
        if started and len(positions) == 0 and restart:
            started = False; last_in = None; level = 0; pending = False
    unreal = sum(p["size"] * (c[-1] - p["entry"]) * d for p in positions)
    profit = realized + unreal
    edge = 100 * profit / volume if volume else 0.0
    return dict(profit=profit, realized=realized, unreal=unreal, volume=volume,
                edge=edge, max_bag=max_bag, open_pos=len(positions))


def sim_dg(close, step=0.3, target=0.55, size0=0.005, max_order=0.02, mult=1.1,
           max_orders=200, exit_at_average=True, fee_bps=3.5, both_sides=True,
           per_order_tp=False, multi_fill=False, high=None, low=None):
    """GinArea DYNAMIC GRID: симметричная сетка + ВЫХОД ПО СРЕДНЕЙ (obap).

    Добавлено 2026-08-02 для калибровки по 20 якорям Вина (v2). Прежний sim()
    моделирует INDICATOR GRID (односторонний, вход по просадке) и выход по
    средней НЕ умеет — закрывает только по таргету позиции и force-close.

    Механика, снятая с живых ботов и конфигов якорей:
      * две независимые лестницы. ЛОНГ добавляется, когда цена ушла на `step`
        НИЖЕ последнего входа лонга; ШОРТ — когда на `step` ВЫШЕ последнего
        входа шорта. Отсчёт от последнего залива, а не от центра (сетка
        «динамическая» — границы едут за ценой);
      * размер ордера растёт: size0 · mult^level, но не выше max_order.
        ВАЖНО: в конфиге якорей max_size=0.02 — это потолок ОДНОГО ордера, а не
        всей позиции. Иначе «мешок завис 1.5 BTC» был бы невозможен. Совпадает
        с живыми ботами OKX (minQ 0.005 → maxQ 0.025, qr 1.1);
      * при ВЫКЛЮЧЕННОМ выходе по средней каждая позиция закрывается по своему
        тейку `target`. При ВКЛЮЧЁННОМ — НЕТ: закрывается весь мешок разом.
        Проверено на реальных ордерах: у ботов с obap=true 78–99% закрытий
        идут ПАЧКАМИ (BTC 14 ордеров в одну секунду с входами 60 534…62 965,
        итог +$34 при 7 плюсовых из 14; XRP 33 ордера разом, 3 плюсовых из 33).
        У LTC/BCH, где obap выключен, наоборот 61–74% закрытий поодиночке;
      * ВЫХОД ПО СРЕДНЕЙ: ВЕСЬ мешок стороны закрывается, когда цена доходит до
        уровня СРЕДНЯЯ · (1 ± target) — не до самой средней. Снято с живого
        бота: stat.extension даёт avgPL 63941.79 → tapb 64242.32 (+0.470%) и
        avgPS 63040.89 → taps 62744.60 (−0.470%) при его tog=0.47. Отношение
        совпадает с целевым в точности. Отсюда же и «обрыв целевого»: чем
        больше target, тем дальше отодвинут уровень флаша, и на глубоком
        обвале цена до него не дотягивается — мешок остаётся висеть.
        После флаша лестница сбрасывается и начинает заново.

    Возвращает и `max_bag` — худшую нереализованную просадку внутри окна
    («транзитная яма»), и `stuck` — что осталось висеть на конец окна.
    """
    c = np.asarray(close, dtype=float)
    n = len(c)
    # Внутрибарное исполнение (гипотеза Вина 02.08, подтвердилась): лимитная
    # заявка исполняется по ХАЮ/ЛОУ бара, а не по закрытию. Фитиль, задевший
    # уровень, у close-модели не заливался — отсюда и недобор объёма.
    hi = np.asarray(high, dtype=float) if high is not None else c
    lo = np.asarray(low, dtype=float) if low is not None else c
    st, tg = step / 100.0, target / 100.0
    fee = fee_bps / 1e4
    books = {1: {"pos": [], "ref": c[0], "lvl": 0},        # +1 = лонг
             -1: {"pos": [], "ref": c[0], "lvl": 0}}       # -1 = шорт
    if not both_sides:
        books.pop(-1)
    realized = volume = 0.0
    max_bag = 0.0
    flushes = target_closes = 0

    for i in range(n):
        px = c[i]
        for d, bk in books.items():
            # 1) свой тейк у каждой позиции («помол» сетки). Работает вместе с
            # выходом по средней: помол даёт оборот, средняя — флаш мешка.
            if per_order_tp or not exit_at_average:
                keep = []
                for p in bk["pos"]:
                    hit = ((px >= p["e"] * (1 + tg)) if d > 0
                           else (px <= p["e"] * (1 - tg)))
                    if hit:
                        realized += p["s"] * (px - p["e"]) * d - fee * p["s"] * px
                        target_closes += 1
                    else:
                        keep.append(p)
                bk["pos"] = keep
            # 2) ВЫХОД ПО СРЕДНЕЙ — весь мешок стороны разом.
            # Уровень флаша тоже может быть задет фитилём внутри бара.
            if exit_at_average and bk["pos"]:
                tot = sum(p["s"] for p in bk["pos"])
                avg = sum(p["s"] * p["e"] for p in bk["pos"]) / tot
                goal = avg * (1 + tg) if d > 0 else avg * (1 - tg)
                crossed = (hi[i] >= goal) if d > 0 else (lo[i] <= goal)
                if crossed:
                    px = goal          # исполнение по уровню, а не по закрытию
                    for p in bk["pos"]:
                        realized += p["s"] * (px - p["e"]) * d - fee * p["s"] * px
                    bk["pos"] = []
                    bk["ref"] = px
                    bk["lvl"] = 0
                    flushes += 1
            # 3) добор против движения. ВАЖНО: за один бар цена может пройти
            # НЕСКОЛЬКО ступеней сетки — на обвале заливаются все, а не одна.
            # С «одним доливом за минуту» сим давал объём 0.05x от реального
            # (сверка с якорями 02.08) — форма верна, масштаб занижен в 15-20 раз.
            # multi_fill=True физичнее (цена реально проходит несколько уровней),
            # НО на калибровке ломает обрыв: молодая лестница успевает флашиться
            # на мелких отскоках внутри падения и глубокий мешок не набирается.
            # Реальность (якорь 5234319055) — мешок ДА набрался, 1.5 BTC.
            # Поэтому по умолчанию один долив за бар: он воспроизводит форвард
            # по четырём величинам сразу (PnL, место обрыва, размер мешка, яма).
            while len(bk["pos"]) < max_orders:
                lvl_px = (bk["ref"] * (1 - st)) if d > 0 else (bk["ref"] * (1 + st))
                # заявка стоит на уровне: её задевает ЛОУ (лонг) / ХАЙ (шорт)
                reached = (lo[i] <= lvl_px) if d > 0 else (hi[i] >= lvl_px)
                if not reached:
                    break
                size = min(size0 * (mult ** bk["lvl"]), max_order)
                bk["pos"].append({"e": lvl_px, "s": size})
                volume += size * lvl_px
                realized -= fee * size * lvl_px
                bk["ref"] = lvl_px
                bk["lvl"] += 1
                if not multi_fill:
                    break
        bag = sum(p["s"] * (px - p["e"]) * d
                  for d, bk in books.items() for p in bk["pos"])
        if bag < max_bag:
            max_bag = bag

    stuck = sum(p["s"] * (c[-1] - p["e"]) * d
                for d, bk in books.items() for p in bk["pos"])
    open_pos = sum(len(bk["pos"]) for bk in books.values())
    open_qty = sum(p["s"] for bk in books.values() for p in bk["pos"])
    return dict(total=realized + stuck, realized=realized, stuck=stuck,
                volume=volume, max_bag=max_bag, open_pos=open_pos,
                open_qty=open_qty, flushes=flushes, target_closes=target_closes)


def run_ab(label, a, b, side="long", warm_days=50, **kw):
    a_ts = pd.Timestamp(a, tz="UTC")
    warm = (a_ts - pd.Timedelta(days=warm_days)).strftime("%Y-%m-%d")
    ext = load_1m(warm, b)["close"]
    allow = build_allow(ext, side=side)
    inwin = np.asarray(ext.index >= a_ts)
    close = ext[inwin]; allow = allow[inwin]
    off = sim(close, side=side, allow=None, **kw)
    on = sim(close, side=side, allow=allow, **kw)
    print(f"\n=== {label}  [{side}]  {a}→{b} ===")
    for tag, r in (("GATE OFF", off), ("GATE ON ", on)):
        print(f"  {tag} real {r['realized']:8.0f}  МАКС-МЕШОК {r['max_bag']:9.0f}  "
              f"итог {r['profit']:8.0f}  vol {r['volume']:11.0f}  edge {r['edge']:.3f}%")
    if off["max_bag"]:
        print(f"  → мешок {100*(1-on['max_bag']/off['max_bag']):+.0f}%  "
              f"харвест {100*(on['realized']/off['realized']-1) if off['realized'] else 0:+.0f}%")
    return off, on


def calibrate(a="2025-04-10", b="2025-05-22", anchor_profit=1593, anchor_vol=540000):
    """Tune instop so R1 long ~ anchor (+1593 / 540k vol / 0.295%). Absolute calibration."""
    print(f"=== КАЛИБРОВКА АБСОЛЮТА на R1 (anchor: +{anchor_profit} / vol {anchor_vol} / 0.295%) ===")
    ext = load_1m("2025-02-20", b)["close"]
    inwin = np.asarray(ext.index >= pd.Timestamp(a, tz="UTC"))
    close = ext[inwin]
    print(f"{'instop%':>8}{'profit':>10}{'volume':>12}{'edge%':>8}{'vs anchor vol':>14}")
    for ins in (0.02, 0.05, 0.10, 0.20, 0.40):
        r = sim(close, side="long", instop=ins)
        print(f"{ins:8.2f}{r['profit']:10.0f}{r['volume']:12.0f}{r['edge']:8.3f}{r['volume']/anchor_vol:13.1f}x")


def _load(a, b, warm_days=50):
    a_ts = pd.Timestamp(a, tz="UTC")
    warm = (a_ts - pd.Timedelta(days=warm_days)).strftime("%Y-%m-%d")
    ext = load_1m(warm, b)["close"]
    return ext, np.asarray(ext.index >= a_ts)


def variants(label, a, b, band=0.5, **kw):
    """long-only vs short-only vs DUAL (both legs; losing side closed when price exits ±band)."""
    ext, inwin = _load(a, b); close = ext[inwin]
    la = build_allow(ext, "long",  band=band)[inwin]
    sa = build_allow(ext, "short", band=band)[inwin]
    L = sim(close, "long",  allow=la, close_on_disallow=True, **kw)
    S = sim(close, "short", allow=sa, close_on_disallow=True, **kw)
    print(f"\n=== {label}  {a}→{b}  (band ±{band}%) ===")
    print(f"  LONG-only   итог {L['profit']:8.0f}  vol {L['volume']:10.0f}  макс-мешок {L['max_bag']:8.0f}")
    print(f"  SHORT-only  итог {S['profit']:8.0f}  vol {S['volume']:10.0f}  макс-мешок {S['max_bag']:8.0f}")
    print(f"  DUAL (L+S)  итог {L['profit']+S['profit']:8.0f}  vol {L['volume']+S['volume']:10.0f}  "
          f"макс-мешок {min(L['max_bag'],S['max_bag']):8.0f}")


def band_sweep(label, a, b, **kw):
    """The PLAN for WHEN to close the losing side = how wide the FLAT band is.
    band 0 = close at the line (early, small loss, more whipsaw); wide = late (bigger loss)."""
    ext, inwin = _load(a, b); close = ext[inwin]
    print(f"\n=== ПЛАН «когда закрывать проигрышную» — свип band, {label} {a}→{b} ===")
    print(f"  {'band±%':>7}{'DUAL итог':>11}{'DUAL vol':>11}{'худш.мешок':>11}  трактовка")
    for band in (0.0, 0.3, 0.6, 1.0, 1.5):
        la = build_allow(ext, "long",  band=band)[inwin]
        sa = build_allow(ext, "short", band=band)[inwin]
        L = sim(close, "long",  allow=la, close_on_disallow=True, **kw)
        S = sim(close, "short", allow=sa, close_on_disallow=True, **kw)
        tag = "режем РАНО у линии" if band == 0 else ("режем ПОЗДНО" if band >= 1.0 else "баланс")
        print(f"  {band:7.1f}{L['profit']+S['profit']:11.0f}{L['volume']+S['volume']:11.0f}"
              f"{min(L['max_bag'],S['max_bag']):11.0f}  {tag}")


def main():
    print("ВАРИАНТЫ: long-only / short-only / DUAL (обе ноги, проигрышную режем при выходе за band)\n")
    variants("FLAT/чоп июнь'25",          "2025-06-01", "2025-06-30")
    variants("Полный цикл апр'25→фев'26", "2025-04-01", "2026-02-15")
    band_sweep("полный цикл", "2025-04-01", "2026-02-15")


if __name__ == "__main__":
    main()
