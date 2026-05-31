"""Visualize the trend-aligned LONG strategy on candles — every entry & exit.

Runs the real detectors over 2y BTC, keeps only trades aligned with the 4h trend
(long in 4h-up), simulates exits (tp1.5/sl0.5/2h), and renders an interactive
candlestick chart: 1h candles + 4h-EMA trend line + entry ▲ / exit ● markers
(green win / red loss) with the real exit reason and pnl. Lightweight-charts is
INLINED so the file opens offline (no CDN).

Output: docs/STRATEGIES/trend_strategy_chart.html
"""
import json
import sys
import urllib.request
from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from tools._setup_2y_backtest import (  # noqa: E402
    _load, _trend_series, DetectionContext,
    detect_long_pdl_bounce, detect_long_dump_reversal,
)

FEE_MAKER = 0.03
TP, SL, HOLD = 1.5, 0.5, 120
STEP, H1W, M1W = 15, 60, 60
OUT = ROOT / "docs" / "STRATEGIES" / "trend_strategy_chart.html"
LIB_URL = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"


def _sim_full(cl, hi, lo, ts_ns, idx, t, entry):
    pos = int(np.searchsorted(ts_ns, t.value, side="left"))
    end = pos + HOLD
    if pos >= len(cl) or end > len(cl):
        return None
    tp, sl = entry * (1 + TP / 100), entry * (1 - SL / 100)
    for i in range(pos, end):
        if lo[i] <= sl:
            return (idx[i], sl, "SL", -SL - FEE_MAKER)
        if hi[i] >= tp:
            return (idx[i], tp, "TP", TP - FEE_MAKER)
    ex = float(cl[end - 1])
    return (idx[end - 1], ex, "TIMEOUT", (ex / entry - 1) * 100 - FEE_MAKER)


def main():
    pair = "BTCUSDT"
    m1 = _load(pair)
    h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()
    trend = _trend_series(m1)
    tr_ns = trend.index.astype("int64").to_numpy(); tr_v = trend.to_numpy()
    ts_ns = m1.index.astype("int64").to_numpy()
    cl = m1["close"].to_numpy(float); hi = m1["high"].to_numpy(float); lo = m1["low"].to_numpy(float)
    m1_idx = m1.index

    trades = []
    last_exit = None
    for pos in range(M1W, len(m1) - HOLD, STEP):
        t = m1_idx[pos]
        if last_exit is not None and t < last_exit:
            continue
        hpos = int(np.searchsorted(h1.index.astype("int64").to_numpy(), t.value, side="right"))
        if hpos < 16:
            continue
        ctx = DetectionContext(pair=pair, current_price=float(cl[pos]), regime_label="range_wide",
                               session_label="ANY", ohlcv_1m=m1.iloc[pos-M1W:pos+1],
                               ohlcv_1h=h1.iloc[max(0, hpos-H1W):hpos])
        tp_i = int(np.searchsorted(tr_ns, t.value, side="right")) - 1
        tr = tr_v[tp_i] if 0 <= tp_i < len(tr_v) else "flat"
        if tr != "up":          # ALIGNED LONG only
            continue
        for fn, name in ((detect_long_dump_reversal, "dump_reversal"),
                         (detect_long_pdl_bounce, "pdl_bounce")):
            try:
                s = fn(ctx)
            except Exception:
                s = None
            if s is not None:
                r = _sim_full(cl, hi, lo, ts_ns, m1_idx, t, float(cl[pos]))
                if r:
                    ex_ts, ex_px, reason, pnl = r
                    trades.append({"t_in": int(t.timestamp()), "p_in": round(float(cl[pos]), 1),
                                   "t_out": int(ex_ts.timestamp()), "p_out": round(ex_px, 1),
                                   "reason": reason, "pnl": round(pnl, 3), "type": name})
                    last_exit = t + timedelta(minutes=HOLD)
                break
    print(f"aligned-long trades: {len(trades)}")
    wins = sum(1 for x in trades if x["pnl"] > 0)
    print(f"WR {wins/len(trades)*100:.0f}%  sum {sum(x['pnl'] for x in trades):.1f}%")

    # 1h candles + 4h EMA mapped onto 1h timeline
    candles = [{"time": int(ts.timestamp()), "open": round(o, 1), "high": round(hh, 1),
                "low": round(ll, 1), "close": round(c, 1)}
               for ts, o, hh, ll, c in zip(h1.index, h1["open"], h1["high"], h1["low"], h1["close"])]
    ema4 = m1["close"].resample("4h").last().ewm(span=20, adjust=False).mean()
    ema_line = [{"time": int(ts.timestamp()), "value": round(float(v), 1)}
                for ts, v in ema4.dropna().items()]

    markers = []
    for x in trades:
        color = "#26a69a" if x["pnl"] > 0 else "#ef5350"
        markers.append({"time": x["t_in"], "position": "belowBar", "color": "#2962FF",
                        "shape": "arrowUp", "text": "IN"})
        markers.append({"time": x["t_out"], "position": "aboveBar", "color": color,
                        "shape": "circle", "text": f"{x['reason']} {x['pnl']:+.2f}%"})
    markers.sort(key=lambda m: m["time"])

    # inline the JS library (offline-capable)
    try:
        lib = urllib.request.urlopen(LIB_URL, timeout=20).read().decode("utf-8")
        lib_tag = f"<script>{lib}</script>"
    except Exception:
        lib_tag = f'<script src="{LIB_URL}"></script>'

    html = _render(candles, ema_line, markers, lib_tag, len(trades), wins,
                   sum(x["pnl"] for x in trades))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


def _render(candles, ema, markers, lib_tag, n, wins, total):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Trend-aligned LONG — entries & exits</title>{lib_tag}
<style>body{{background:#0a0c10;color:#d1d4dc;font-family:-apple-system,Segoe UI,sans-serif;margin:0;padding:14px}}
h1{{font-size:18px}} .legend{{font-size:13px;color:#9aa;margin:6px 0 12px}}
.tp{{color:#26a69a}} .sl{{color:#ef5350}} #c{{width:100%;height:560px}}</style></head><body>
<h1>🎯 Тренд-выровненный LONG (BTC, 2г) — входы и выходы на свечах</h1>
<div class="legend">Сетапы dump_reversal/pdl_bounce ТОЛЬКО когда 4h-тренд вверх (мейкер-вход).
Свечи 1ч · оранжевая линия = 4h-EMA20 (тренд) · ▲ синяя = вход · ● <span class="tp">зелёная=прибыль</span>/<span class="sl">красная=убыток</span> с причиной выхода (TP/SL/таймаут) и pnl.<br>
Итого: {n} сделок, WR {wins/n*100:.0f}%, sum {total:+.1f}% (мейкер 0.03%). Зум/пан — колесо/перетаскивание.</div>
<div id="c"></div>
<script>
var ch=LightweightCharts.createChart(document.getElementById('c'),{{
 layout:{{background:{{color:'#0e1116'}},textColor:'#d1d4dc'}},
 grid:{{vertLines:{{color:'#1c2230'}},horzLines:{{color:'#1c2230'}}}},
 timeScale:{{timeVisible:true,secondsVisible:false}},rightPriceScale:{{borderColor:'#1c2230'}}}});
var cs=ch.addCandlestickSeries();
cs.setData({json.dumps(candles)});
var el=ch.addLineSeries({{color:'#ffa726',lineWidth:2,priceLineVisible:false}});
el.setData({json.dumps(ema)});
cs.setMarkers({json.dumps(markers)});
ch.timeScale().fitContent();
</script></body></html>"""


if __name__ == "__main__":
    main()
