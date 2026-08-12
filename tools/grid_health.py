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

# Пороги заклинивания ИЗМЕРЕНЫ на 774 прогонах архива (2026-08-12):
# мешок > 0.5% книги И оборот ниже пятой части нормы -> 81.4% прогонов
# убыточны против 7.6%, когда нет ни того ни другого (лифт 10.7x).
# Каждый признак по отдельности слабый: только мешок 42%, только оборот 14%.
JAM_BAG_PCT = 0.5        # мешок к книге, %
JAM_TURN_FRAC = 0.20     # оборот к своей же норме
JAM_HOURS = 24.0         # оба условия держатся дольше
MARGIN_TOLERANCE = 0.70  # маржа ниже 70% от закона = флаг

# Затяжное движение: docs/RESEARCH/SUSTAINED_MOVES.md
# «цена выше SMA20д N дней подряд» — 18/30 эпизодов BTC, остаток хода 6.89%,
# ложных 0.3/мес. Зарождение эпизода НЕ предсказуемо (лучший лифт 1.47),
# поэтому здесь только обнаружение уже идущего.
TREND_DAYS = 5
TREND_SPEED_PCT_DAY = 1.53   # медианная скорость затяжного движения


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


def market_regime() -> dict:
    """Затяжное движение по BTC: цена выше/ниже SMA20д N дней подряд."""
    live = ROOT / "market_live" / "market_1m.csv"
    if not live.exists():
        return {}
    px = tail_csv(live, mb=40)
    px["ts"] = pd.to_datetime(px["ts_utc"], utc=True, errors="coerce")
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px = px.dropna(subset=["ts", "close"]).set_index("ts").sort_index()
    h = px["close"].resample("1h").last().ffill()
    if len(h) < 480 + TREND_DAYS * 24:
        return {"мало данных": len(h)}
    sma = h.rolling(480).mean()
    above = (h > sma).to_numpy()
    below = (h < sma).to_numpy()

    def streak(flags):
        k = 0
        for v in flags[::-1]:
            if not v:
                break
            k += 1
        return k

    up_h, dn_h = streak(above), streak(below)
    state = ("РОСТ" if up_h >= TREND_DAYS * 24
             else "ПАДЕНИЕ" if dn_h >= TREND_DAYS * 24 else "нет")
    return {"состояние": state, "часов выше SMA20д": up_h,
            "часов ниже SMA20д": dn_h, "цена": float(h.iloc[-1]),
            "SMA20д": float(sma.iloc[-1]),
            "отклонение%": float(h.iloc[-1] / sma.iloc[-1] - 1) * 100}


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
    for c in ("status", "position", "average_price", "profit",
              "current_profit", "trade_volume"):
        if c in s.columns:
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
        # Единицы position зависят от типа контракта: у линейных USDT-ботов
        # позиция в МОНЕТАХ, у инверсных COIN — уже в USD-контрактах.
        # Схеме не доверяем (maxQ бывает и 0.025, и 300) — проверяем данными:
        # позиция не может быть больше всего оборота бота за окно.
        as_coin = g["position"].abs() * g["average_price"].fillna(0)
        as_usd = g["position"].abs()
        total_vol = float(g["trade_volume"].iloc[-1]
                          - g["trade_volume"].iloc[0])
        inverse = bool(total_vol > 0 and as_coin.max() > total_vol)
        notional = as_usd if inverse else as_coin
        cur = float(notional.iloc[-1])
        peak = float(notional.max())

        # часы с последнего роста оборота
        grew = g.loc[g["trade_volume"].diff().fillna(0) > 0, "ts"]
        idle_h = ((now - grew.iloc[-1]).total_seconds() / 3600
                  if len(grew) else float("inf"))

        # МЕШОК = currentProfit - profit (нереализованное), в % от книги
        bag_pct = float("nan")
        if "current_profit" in g.columns and peak > 0:
            bag = float(last["current_profit"] - last["profit"])
            bag_pct = bag / peak * 100

        # ОБОРОТ к собственной норме: последние сутки против медианы по суткам
        turn_frac = float("nan")
        vser = g.set_index("ts")["trade_volume"]
        daily = vser.resample("1D").last().diff().dropna()
        if len(daily) >= 3 and daily.median() > 0:
            turn_frac = float(daily.iloc[-1] / daily.median())

        # часы, в течение которых ОБА условия держатся
        stuck_h = 0.0
        if (bag_pct == bag_pct and bag_pct < -JAM_BAG_PCT
                and turn_frac == turn_frac and turn_frac < JAM_TURN_FRAC):
            stuck_h = idle_h if idle_h != float("inf") else JAM_HOURS

        dv = float(g["trade_volume"].iloc[-1] - g["trade_volume"].iloc[0])
        dp = float(g["profit"].iloc[-1] - g["profit"].iloc[0])
        # У ИНВЕРСНЫХ ботов profit в БАЗОВОЙ МОНЕТЕ, а оборот в USD.
        # Делить одно на другое без перевода нельзя — маржа выходит нулём.
        # Инверсный опознаётся тем же признаком, что и позиция выше.
        if inverse:
            px_last = float(last.get("average_price") or 0) or float(
                g["average_price"].replace(0, pd.NA).dropna().iloc[-1]
                if g["average_price"].replace(0, pd.NA).notna().any() else 0)
            dp *= px_last
        marg = dp / dv * 100 if dv > 1000 else float("nan")
        is_dyn = str(m.get("strategy") or "").upper().startswith("DYN")
        law = law_margin(m.get("target"), is_dyn)
        ratio = marg / law if law and law == law and marg == marg else float("nan")

        flags = []
        if stuck_h >= JAM_HOURS:
            flags.append(f"ЗАКЛИНИЛА: мешок {bag_pct:.2f}% книги + оборот "
                         f"{turn_frac*100:.0f}% нормы ({stuck_h:.0f}ч)")
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
            "bag_pct_of_book": bag_pct,
            "turnover_frac_of_norm": turn_frac,
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

    reg = market_regime()
    if reg.get("состояние"):
        st = reg["состояние"]
        print(f"РЕЖИМ РЫНКА (BTC): {st}")
        print(f"  цена {reg['цена']:,.0f}   SMA20д {reg['SMA20д']:,.0f}   "
              f"отклонение {reg['отклонение%']:+.2f}%")
        print(f"  выше SMA20д подряд: {reg['часов выше SMA20д']/24:.1f} дн   "
              f"ниже: {reg['часов ниже SMA20д']/24:.1f} дн   "
              f"(порог затяжного движения — {TREND_DAYS} дн)")
        if st == "РОСТ":
            cov = 6.0
            print(f"  >>> НЕ ОТКРЫВАТЬ НОВЫЙ ШОРТ-ГРИД. Медианный остаток хода "
                  f"вверх 6.89%, покрытие книги ~{cov:.0f}%.")
            print(f"  >>> при скорости {TREND_SPEED_PCT_DAY}%/день книга "
                  f"заполнится примерно за {cov/TREND_SPEED_PCT_DAY:.1f} дн.")
        print()
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
