"""Visual trade breakdown — survivor setups on real candles (entries/exits).

Like a strategy-breakdown video: candlestick chart per (setup, pair) with every
real precision_outcomes trade marked — green up-arrow = entry, circle = exit
(green TP1 / red SL / grey TIMEOUT) with the actual pnl%. Self-contained HTML
using TradingView lightweight-charts (CDN) — opens in any browser, zoom/pan.

Truth source: setup_precision_outcomes.jsonl (NOT paper). Exit time reconstructed
by scanning forward to the bar whose range contains the recorded exit price.

Output: docs/STRATEGIES/setup_charts.html
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
PO = ROOT / "state" / "setup_precision_outcomes.jsonl"
FROZEN = ROOT / "backtests" / "frozen"
OUT = ROOT / "docs" / "STRATEGIES" / "setup_charts.html"
SURVIVORS = ("long_double_bottom", "long_pdl_bounce", "long_dump_reversal")
HOLD_BARS = 96          # 15m bars = 24h max scan for exit
PAD_BARS = 24           # padding around the trade cluster


def _load_15m(pair):
    df = pd.read_csv(FROZEN / f"{pair}_1m_2y.csv")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    o = (df.set_index("ts").resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna())
    return o


def main() -> int:
    rows = [json.loads(l) for l in PO.read_text().splitlines() if l.strip()]
    groups = {}
    for r in rows:
        if r.get("setup_type") in SURVIVORS and r.get("detected_at") and r.get("entry"):
            groups.setdefault((r["setup_type"], r.get("pair", "?")), []).append(r)

    panels = []
    cache = {}
    for (setup, pair), trades in sorted(groups.items()):
        if len(trades) < 2 or pair not in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
            continue
        if pair not in cache:
            cache[pair] = _load_15m(pair)
        ohlc = cache[pair]
        idx = ohlc.index
        t0 = min(pd.Timestamp(t["detected_at"]) for t in trades)
        t1 = max(pd.Timestamp(t["detected_at"]) for t in trades)
        lo = idx.searchsorted(t0) - PAD_BARS
        hi = idx.searchsorted(t1) + HOLD_BARS + PAD_BARS
        lo = max(0, lo); hi = min(len(idx), hi)
        win = ohlc.iloc[lo:hi]
        candles = [{"time": int(t.timestamp()), "open": round(o, 4),
                    "high": round(h, 4), "low": round(l, 4), "close": round(c, 4)}
                   for t, o, h, l, c in zip(win.index, win["open"], win["high"],
                                             win["low"], win["close"])]
        markers = []
        wins = 0
        for tr in trades:
            ent_t = pd.Timestamp(tr["detected_at"])
            entry = float(tr["entry"]); exitp = float(tr["exit"])
            oc = str(tr.get("outcome", "")).upper()
            pnl = tr.get("pnl_pct")
            ei = idx.searchsorted(ent_t)
            ts_in = int(idx[min(ei, len(idx) - 1)].timestamp())
            markers.append({"time": ts_in, "position": "belowBar",
                            "color": "#2962FF", "shape": "arrowUp",
                            "text": f"IN {entry:g}"})
            # reconstruct exit bar: first bar in [ei, ei+HOLD] whose range hits exitp
            ex_ts = None
            for j in range(ei, min(ei + HOLD_BARS, len(ohlc))):
                bar = ohlc.iloc[j]
                if bar["low"] <= exitp <= bar["high"]:
                    ex_ts = int(idx[j].timestamp())
                    break
            if ex_ts is None:
                ex_ts = int(idx[min(ei + HOLD_BARS, len(idx) - 1)].timestamp())
            color = {"TP1": "#26a69a", "SL": "#ef5350"}.get(oc, "#9e9e9e")
            if oc == "TP1":
                wins += 1
            markers.append({"time": ex_ts, "position": "aboveBar", "color": color,
                            "shape": "circle",
                            "text": f"{oc} {pnl:+.2f}%" if pnl is not None else oc})
        markers.sort(key=lambda m: m["time"])
        panels.append({
            "id": f"{setup}_{pair}".replace(" ", "_"),
            "title": f"{setup} · {pair} — n={len(trades)}, TP1={wins}/{len(trades)}",
            "candles": candles, "markers": markers,
        })

    html = _render(panels)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(panels)} panels)")
    for p in panels:
        print(f"  {p['title']}  (candles={len(p['candles'])}, marks={len(p['markers'])})")
    return 0


def _render(panels) -> str:
    blocks = []
    for p in panels:
        blocks.append(f"""
  <div class="panel">
    <h3>{p['title']}</h3>
    <div id="{p['id']}" class="chart"></div>
  </div>""")
    scripts = []
    for p in panels:
        scripts.append(f"""
    (function() {{
      var el = document.getElementById({json.dumps(p['id'])});
      var chart = LightweightCharts.createChart(el, {{
        width: el.clientWidth, height: 360,
        layout: {{ background: {{ color: '#0e1116' }}, textColor: '#d1d4dc' }},
        grid: {{ vertLines: {{ color: '#1c2230' }}, horzLines: {{ color: '#1c2230' }} }},
        timeScale: {{ timeVisible: true, secondsVisible: false }},
      }});
      var s = chart.addCandlestickSeries();
      s.setData({json.dumps(p['candles'])});
      s.setMarkers({json.dumps(p['markers'])});
      chart.timeScale().fitContent();
    }})();""")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Survivor setups — visual breakdown</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
 body {{ background:#0a0c10; color:#d1d4dc; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:16px; }}
 h1 {{ font-size:20px; }} h3 {{ margin:18px 0 6px; font-size:15px; color:#8fb3ff; }}
 .legend {{ font-size:13px; color:#9aa; margin-bottom:10px; }}
 .panel {{ margin-bottom:26px; }} .chart {{ width:100%; }}
 .tp {{ color:#26a69a }} .sl {{ color:#ef5350 }} .to {{ color:#9e9e9e }}
</style></head><body>
<h1>🎯 Разбор выживших сетапов на реальных свечах</h1>
<div class="legend">Источник: setup_precision_outcomes (правда, не paper).
▲ синяя = вход · ● <span class="tp">зелёная=TP1</span> / <span class="sl">красная=SL</span> / <span class="to">серая=TIMEOUT</span> с реальным pnl%.
Окно сделок: 8–12 мая 2026 (одно окно — out-of-time ещё не проверен).</div>
{''.join(blocks)}
<script>{''.join(scripts)}</script>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
