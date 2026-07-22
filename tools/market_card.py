"""РЫНОК — структурная карточка без прогнозов.

Оператор 2026-07-22: «не нужно угадывание направления — нужно: вышли из
рейнджа / рост продолжается / не разворот / цели такие-то / отмена такая-то».

Всё здесь — факты и арифметика, никаких вероятностей:
  структура  — границы диапазона из свечей, где цена относительно них
  цели       — проекция высоты диапазона от границы (геометрия)
  отмена     — сама граница (уровень, где сценарий мёртв)
  механика   — OI/тейкеры/объём: новые деньги или закрытие позиций
  толпа      — global L/S против top-trader L/S (расхождение = факт)
  боль       — где реально ликвидировало за 24ч (кластеры цен)
  альты      — сила/слабость и раскорреляция с BTC

Запуск: .venv/bin/python3 tools/market_card.py [--symbol BTCUSDT]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MARKET = {"BTCUSDT": ROOT / "market_live" / "market_1m.csv"}
LIQ = {"BTCUSDT": ROOT / "market_live" / "liquidations.csv",
       "ETHUSDT": ROOT / "market_live" / "liquidations_ETHUSDT.csv",
       "XRPUSDT": ROOT / "market_live" / "liquidations_XRPUSDT.csv"}
DERIV = ROOT / "state" / "deriv_live.json"
FROZEN = {s: ROOT / "backtests" / "frozen" / f"{s}_1m_2y.csv"
          for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT")}

RANGE_LOOKBACK_H = 72
RANGE_VALID_FRAC = 0.70      # доля времени внутри границ, ниже — не диапазон
OI_NEW_MONEY_PCT = 0.3       # |OI 1ч| выше — трактуем как поток, а не шум


def load_1m(symbol: str) -> pd.DataFrame:
    p = MARKET.get(symbol)
    if p and p.exists():
        d = pd.read_csv(p, names=["ts", "o", "h", "l", "c", "v"], skiprows=1)
        d["dt"] = pd.to_datetime(d["ts"], utc=True, format="ISO8601")
    else:
        d = pd.read_csv(FROZEN[symbol])
        unit = "ms" if d["ts"].iloc[-1] > 1e12 else "s"
        d["dt"] = pd.to_datetime(d["ts"], unit=unit, utc=True)
        d = d.rename(columns={"open": "o", "high": "h", "low": "l",
                              "close": "c", "volume": "v"})
    return d.set_index("dt").sort_index()


def hourly(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("1h").agg({"o": "first", "h": "max", "l": "min",
                                  "c": "last", "v": "sum"}).dropna()


def detect_range(h1: pd.DataFrame) -> dict:
    w = h1.tail(RANGE_LOOKBACK_H)
    hi = float(w["h"].quantile(0.90))
    lo = float(w["l"].quantile(0.10))
    inside = float(((w["c"] >= lo) & (w["c"] <= hi)).mean())
    return {"hi": hi, "lo": lo, "height": hi - lo, "inside_frac": inside,
            "valid": inside >= RANGE_VALID_FRAC, "bars": len(w)}


def liq_clusters(symbol: str, hours: int = 24, buckets: int = 4) -> list[dict]:
    """Где реально ликвидировало за N часов — кластеры по цене."""
    p = LIQ.get(symbol)
    if not p or not p.exists():
        return []
    try:
        d = pd.read_csv(p)
    except Exception:
        return []
    d = d.dropna(subset=["price", "qty"])
    if d.empty:
        return []
    d["ts_utc"] = pd.to_datetime(d["ts_utc"], utc=True, errors="coerce")
    d = d[d["ts_utc"] >= datetime.now(timezone.utc) - timedelta(hours=hours)]
    d["price"] = pd.to_numeric(d["price"], errors="coerce")
    d["qty"] = pd.to_numeric(d["qty"], errors="coerce")
    d = d.dropna(subset=["price", "qty"])
    if len(d) < 10:
        return []
    d["bucket"] = pd.cut(d["price"], bins=buckets)
    out = []
    for b, g in d.groupby("bucket", observed=True):
        out.append({"lo": b.left, "hi": b.right, "qty": float(g["qty"].sum()),
                    "long": float(g[g["side"] == "long"]["qty"].sum()),
                    "short": float(g[g["side"] == "short"]["qty"].sum())})
    out.sort(key=lambda r: -r["qty"])
    return out[:3]


def fmt(symbol: str) -> str:
    d1 = load_1m(symbol)
    h1 = hourly(d1)
    px = float(d1["c"].iloc[-1])
    now = d1.index[-1]
    rng = detect_range(h1)
    L: list[str] = []

    L.append(f"📐 РЫНОК {symbol.replace('USDT','')} ${px:,.0f}   "
             f"({now:%d.%m %H:%M} UTC)")

    # ── структура
    hi, lo, height = rng["hi"], rng["lo"], rng["height"]
    hpct = height / px * 100
    if not rng["valid"]:
        L.append(f"\nСТРУКТУРА: диапазона нет — цена внутри границ только "
                 f"{rng['inside_frac']*100:.0f}% времени (тренд/расширение)")
    else:
        L.append(f"\nДИАПАЗОН {rng['bars']}ч: ${lo:,.0f} — ${hi:,.0f} "
                 f"(высота {hpct:.1f}%, внутри {rng['inside_frac']*100:.0f}% времени)")

    if px > hi:
        L.append(f"  ВЫШЛИ ВВЕРХ на {(px/hi-1)*100:.2f}% от границы")
        scen = ("вверх", hi + height, hi)
    elif px < lo:
        L.append(f"  ВЫШЛИ ВНИЗ на {(lo/px-1)*100:.2f}% от границы")
        scen = ("вниз", lo - height, lo)
    else:
        up_d, dn_d = (hi - px) / px * 100, (px - lo) / px * 100
        L.append(f"  ВНУТРИ: до верха {up_d:.2f}%, до низа {dn_d:.2f}%")
        scen = None

    # ── механика
    deriv = {}
    try:
        deriv = json.loads(DERIV.read_text(encoding="utf-8")).get(symbol, {})
    except Exception:
        pass
    oi = deriv.get("oi_change_1h_pct")
    taker = deriv.get("taker_buy_sell_ratio")
    fund = (deriv.get("funding_rate_8h") or 0) * 100
    vol_ratio = float(h1["v"].iloc[-1]) / max(float(h1["v"].tail(24).mean()), 1e-9)
    L.append(f"\nПОТОК: OI 1ч {oi:+.2f}%  тейкеры {taker}  "
             f"объём {vol_ratio:.1f}×  фандинг {fund:+.4f}%"
             if oi is not None else f"\nПОТОК: объём {vol_ratio:.1f}×")

    if oi is not None and taker:
        if oi > OI_NEW_MONEY_PCT and taker > 1.1:
            L.append("  → приходят НОВЫЕ ЛОНГИ (OI↑ + покупки) = движение обеспечено")
        elif oi > OI_NEW_MONEY_PCT and taker < 0.9:
            L.append("  → приходят НОВЫЕ ШОРТЫ (OI↑ + продажи) = давление вниз обеспечено")
        elif oi < -OI_NEW_MONEY_PCT and taker > 1.1:
            L.append("  → ЗАКРЫТИЕ ШОРТОВ (OI↓ + покупки) = вынос, а не спрос. "
                     "Топливо кончается на выносе")
        elif oi < -OI_NEW_MONEY_PCT and taker < 0.9:
            L.append("  → ЗАКРЫТИЕ ЛОНГОВ (OI↓ + продажи) = разгрузка, а не новые продажи")
        else:
            L.append("  → потока нет, движение без денег")

    # ── сценарий
    L.append("\nСЦЕНАРИЙ:")
    if scen:
        direction, target, invalid = scen
        L.append(f"  Пробой {direction} → цель ${target:,.0f} "
                 f"({(target/px-1)*100:+.1f}%)")
        L.append(f"  ОТМЕНА: возврат {'под' if direction=='вверх' else 'над'} "
                 f"${invalid:,.0f}")
    elif rng["valid"]:
        L.append(f"  Пока внутри — работает край. Включается по закрытию часа:")
        L.append(f"    ↑ за ${hi:,.0f} → цель ${hi+height:,.0f}, "
                 f"отмена — возврат под ${hi:,.0f}")
        L.append(f"    ↓ за ${lo:,.0f} → цель ${lo-height:,.0f}, "
                 f"отмена — возврат над ${lo:,.0f}")
    else:
        w = h1.tail(RANGE_LOOKBACK_H)
        L.append(f"  Тренд: удержание ${float(w['l'].tail(24).min()):,.0f} "
                 f"продолжает сценарий, пробой — ломает")

    # ── толпа
    g_ls = deriv.get("global_ls_ratio")
    t_ls = deriv.get("top_trader_ls_ratio")
    if g_ls and t_ls:
        L.append(f"\nПОЗИЦИИ: толпа L/S {g_ls}  крупные L/S {t_ls}")
        if g_ls > 1.5 and t_ls < g_ls * 0.75:
            L.append("  ⚠️ толпа в лонгах, крупные заметно сдержаннее — "
                     "расхождение (топливо для выноса вниз)")
        elif g_ls < 0.9 and t_ls > 1.1:
            L.append("  ⚠️ толпа в шортах, крупные в лонгах — "
                     "расхождение (топливо для выноса вверх)")

    # ── боль
    cl = liq_clusters(symbol)
    if cl:
        L.append("\nГДЕ ЛИКВИДИРОВАЛО за 24ч:")
        for c in cl:
            dom = "лонги" if c["long"] > c["short"] else "шорты"
            L.append(f"  ${c['lo']:,.0f}–${c['hi']:,.0f}: {c['qty']:.1f} "
                     f"({dom} — {max(c['long'], c['short']):.1f})")

    # ── уровни
    w7 = h1.tail(168)
    L.append(f"\nУРОВНИ 7д: хай ${float(w7['h'].max()):,.0f} "
             f"({(float(w7['h'].max())/px-1)*100:+.1f}%)  "
             f"лой ${float(w7['l'].min()):,.0f} "
             f"({(float(w7['l'].min())/px-1)*100:+.1f}%)")
    return "\n".join(L)


def alts_block() -> str:
    """Сила альтов и раскорреляция с BTC — на 1ч барах за 48ч."""
    out = ["\n🔀 АЛЬТЫ (48ч):"]
    try:
        btc = hourly(load_1m("BTCUSDT")).tail(48)
    except Exception:
        return ""
    for sym in ("ETHUSDT", "XRPUSDT"):
        try:
            a = hourly(load_1m(sym)).tail(48)
        except Exception:
            continue
        j = pd.concat([btc["c"].rename("b"), a["c"].rename("a")], axis=1).dropna()
        if len(j) < 24:
            continue
        corr = j["b"].pct_change().corr(j["a"].pct_change())
        b_chg = (j["b"].iloc[-1] / j["b"].iloc[0] - 1) * 100
        a_chg = (j["a"].iloc[-1] / j["a"].iloc[0] - 1) * 100
        rel = a_chg - b_chg
        mark = ""
        if corr < 0.7:
            mark = "  ← РАСКОРРЕЛИРОВАН (живёт своей жизнью)"
        out.append(f"  {sym.replace('USDT',''):4s} {a_chg:+.1f}% vs BTC {b_chg:+.1f}% "
                   f"→ {rel:+.1f}% отн.  corr {corr:.2f}{mark}")
    return "\n".join(out) if len(out) > 1 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    args = ap.parse_args()
    print(fmt(args.symbol))
    print(alts_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
