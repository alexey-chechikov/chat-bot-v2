"""Trend-following signal — trade WITH the 4h trend on 1h pullback-reclaims.

Operator pivot: reversal setups are too sparse (big no-trade gaps). Instead ride
the trend — frequent entries on pullbacks:
  4h-EMA20 trend.  1h-EMA20 = pullback reference.
  LONG  : 4h up   AND 1h close crosses back ABOVE 1h-EMA (pullback reclaim).
  SHORT : 4h down AND 1h close crosses back BELOW 1h-EMA.
Exit: tp 1.5% / sl 0.5% / max hold 8h, maker fee 0.03% (limit entry like grids).
1 YEAR (recent). Renders an offline candlestick chart with entries/exits.

Output: docs/STRATEGIES/trend_signal_chart.html
"""
import json
import os
import sys
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
FEE = float(os.getenv("FEE", "0.03"))
TP = float(os.getenv("TP", "1.5"))
SL = float(os.getenv("SL", "0.5"))
HOLD_MIN = int(os.getenv("HOLD_MIN", "480"))
EMA_1H, EMA_4H = 20, 20
OUT = ROOT / "docs" / "STRATEGIES" / "trend_signal_chart.html"
LIB = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    df = pd.read_csv(ROOT / "backtests" / "frozen" / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    m1 = df.set_index("ts")[["open", "high", "low", "close"]].sort_index()
    # last 1 year
    m1 = m1[m1.index >= m1.index.max() - pd.Timedelta(days=365)]
    h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    h4c = m1["close"].resample("4h").last().dropna()
    ema4 = h4c.ewm(span=EMA_4H, adjust=False).mean()
    ema4_rising = ema4 > ema4.shift(3)
    h1["ema1h"] = h1["close"].ewm(span=EMA_1H, adjust=False).mean()

    # map 4h trend onto 1h bars
    def trend_at(ts):
        i = ema4.index.searchsorted(ts, side="right") - 1
        if i < 3:
            return "flat"
        up = h4c.iloc[i] > ema4.iloc[i] and bool(ema4_rising.iloc[i])
        dn = h4c.iloc[i] < ema4.iloc[i] and not bool(ema4_rising.iloc[i])
        return "up" if up else ("down" if dn else "flat")

    ts_ns = m1.index.astype("int64").to_numpy()
    hi = m1["high"].to_numpy(float); lo = m1["low"].to_numpy(float); cl = m1["close"].to_numpy(float)
    m1_idx = m1.index

    def sim(t, entry, side):
        pos = int(np.searchsorted(ts_ns, t.value, side="left")); end = pos + HOLD_MIN
        if pos >= len(cl) or end > len(cl):
            return None
        if side == "long":
            tp, sl = entry*(1+TP/100), entry*(1-SL/100)
            for i in range(pos, end):
                if lo[i] <= sl: return (m1_idx[i], sl, "SL", -SL-FEE)
                if hi[i] >= tp: return (m1_idx[i], tp, "TP", TP-FEE)
            return (m1_idx[end-1], float(cl[end-1]), "TIMEOUT", (cl[end-1]/entry-1)*100-FEE)
        else:
            tp, sl = entry*(1-TP/100), entry*(1+SL/100)
            for i in range(pos, end):
                if hi[i] >= sl: return (m1_idx[i], sl, "SL", -SL-FEE)
                if lo[i] <= tp: return (m1_idx[i], tp, "TP", TP-FEE)
            return (m1_idx[end-1], float(cl[end-1]), "TIMEOUT", (entry/cl[end-1]-1)*100-FEE)

    hc = h1["close"].to_numpy(float); he = h1["ema1h"].to_numpy(float); hidx = h1.index
    trades = []
    last_exit = None
    for i in range(EMA_1H + 2, len(h1)):
        t = hidx[i]
        if last_exit is not None and t < last_exit:
            continue
        tr = trend_at(t)
        long_sig = tr == "up" and hc[i-1] < he[i-1] and hc[i] > he[i]
        short_sig = tr == "down" and hc[i-1] > he[i-1] and hc[i] < he[i]
        side = "long" if long_sig else ("short" if short_sig else None)
        if side is None:
            continue
        r = sim(t, float(hc[i]), side)
        if r:
            ex_ts, ex_px, reason, pnl = r
            trades.append({"t_in": int(t.timestamp()), "p_in": round(float(hc[i]), 1),
                           "t_out": int(ex_ts.timestamp()), "p_out": round(ex_px, 1),
                           "reason": reason, "pnl": round(pnl, 3), "side": side})
            last_exit = ex_ts

    n = len(trades); wins = sum(1 for x in trades if x["pnl"] > 0)
    total = sum(x["pnl"] for x in trades)
    print(f"{pair} 1y: trades={n} WR={wins/n*100:.0f}% sum={total:+.1f}% EV={total/n:+.3f}%/tr")
    for sd in ("long", "short"):
        s = [x for x in trades if x["side"] == sd]
        if s:
            w = sum(1 for x in s if x["pnl"] > 0)
            print(f"  {sd:5s} n={len(s)} WR={w/len(s)*100:.0f}% sum={sum(x['pnl'] for x in s):+.1f}% EV={sum(x['pnl'] for x in s)/len(s):+.3f}%")
    # by quarter (OOS within year)
    dfq = pd.DataFrame(trades)
    if len(dfq):
        dfq["q"] = pd.to_datetime(dfq["t_in"], unit="s").dt.to_period("Q")
        print("  by quarter:", end=" ")
        for q, g in dfq.groupby("q"):
            print(f"{q}:n={len(g)} EV={g['pnl'].mean():+.3f}", end="  ")
        print()

    _render(pair, h1, ema4, trades, n, wins, total)


def _render(pair, h1, ema4, trades, n, wins, total):
    candles = [{"time": int(ts.timestamp()), "open": round(o, 1), "high": round(hh, 1),
                "low": round(ll, 1), "close": round(c, 1)}
               for ts, o, hh, ll, c in zip(h1.index, h1["open"], h1["high"], h1["low"], h1["close"])]
    ema_line = [{"time": int(ts.timestamp()), "value": round(float(v), 1)} for ts, v in ema4.dropna().items()]
    markers = []
    for x in trades:
        ec = "#26a69a" if x["pnl"] > 0 else "#ef5350"
        ic = "#2962FF" if x["side"] == "long" else "#e91e63"
        markers.append({"time": x["t_in"], "position": "belowBar" if x["side"] == "long" else "aboveBar",
                        "color": ic, "shape": "arrowUp" if x["side"] == "long" else "arrowDown", "text": x["side"][0].upper()})
        markers.append({"time": x["t_out"], "position": "aboveBar", "color": ec, "shape": "circle",
                        "text": f"{x['reason']} {x['pnl']:+.2f}%"})
    markers.sort(key=lambda m: m["time"])
    try:
        lib_tag = f"<script>{urllib.request.urlopen(LIB, timeout=20).read().decode()}</script>"
    except Exception:
        lib_tag = f'<script src="{LIB}"></script>'
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Trend signal {pair}</title>{lib_tag}
<style>body{{background:#0a0c10;color:#d1d4dc;font-family:-apple-system,sans-serif;margin:0;padding:14px}}
h1{{font-size:18px}}.legend{{font-size:13px;color:#9aa;margin:6px 0 12px}}#c{{width:100%;height:580px}}
.tp{{color:#26a69a}}.sl{{color:#ef5350}}</style></head><body>
<h1>🎯 Трендовый сигнал {pair} (1 год) — вход на откате по тренду</h1>
<div class="legend">4h-тренд (оранжевая EMA20). LONG на откате-реклейме к 1h-EMA в тренде ВВЕРХ, SHORT в тренде ВНИЗ.
▲ синяя=LONG / ▼ розовая=SHORT вход · ● <span class="tp">зел=плюс</span>/<span class="sl">красн=минус</span> (TP/SL/таймаут).<br>
Итого: {n} сделок, WR {wins/n*100:.0f}%, sum {total:+.1f}% (мейкер {FEE}%).</div>
<div id="c"></div>
<script>var ch=LightweightCharts.createChart(document.getElementById('c'),{{
layout:{{background:{{color:'#0e1116'}},textColor:'#d1d4dc'}},grid:{{vertLines:{{color:'#1c2230'}},horzLines:{{color:'#1c2230'}}}},
timeScale:{{timeVisible:true}}}});var cs=ch.addCandlestickSeries();cs.setData({json.dumps(candles)});
var el=ch.addLineSeries({{color:'#ffa726',lineWidth:2}});el.setData({json.dumps(ema_line)});
cs.setMarkers({json.dumps(markers)});ch.timeScale().fitContent();</script></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
