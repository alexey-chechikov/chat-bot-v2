"""27.10: картинка рынка «как у CoinGlass» (services/market_lens.py) — без сети."""
from __future__ import annotations

import math

import pandas as pd

from services import market_lens, regime_watch


def _df(hours: int = 480) -> pd.DataFrame:
    idx = pd.date_range("2026-10-08", periods=hours, freq="1h", tz="UTC")
    rows = []
    for i, t in enumerate(idx):
        c = 80000 + 4000 * math.sin(i / 60) - 5 * i               # вершина около 4-х суток, дно около 10-х
        rows.append({"o": c - 20, "h": c + 60, "l": c - 60, "c": c, "qv": 5e8,
                     "crowd": 2.0 - (c - 80000) / 4000,           # толпа — зеркало цены
                     "top": 1.6 + (0.4 if i >= hours - 30 else 0.0),
                     "oi": 7.5e9 + 1e6 * i,
                     "funding": -0.00002 if i % 100 == 0 else 0.0001,
                     "fund_tick": (-0.00002 if i % 100 == 0 else 0.0001) if t.hour % 8 == 0 else float("nan"),
                     "liq_long": 0.0, "liq_short": 0.0})
    df = pd.DataFrame(rows, index=idx)
    lo_t = df["l"][df.index >= df.index[-1] - pd.Timedelta(days=12)].idxmin()
    df.loc[lo_t, "liq_long"] = 40e6                               # вынос лонгов в час дна
    df.loc[df.index[-3], "liq_short"] = 2e6
    return df


def test_facts_name_what_coincided():
    lines = market_lens.facts("BTCUSDT", _df())
    text = "\n".join(lines)
    assert text.startswith("BTC ")
    assert "от макс. 12 сут" in text and "3 сут: хаи" in text
    assert "👥 Толпа L/S" in text and "на вершине" in text and "на дне" in text
    assert "🐋 Крупные L/S 2.00" in text and "лонгов стало больше" in text and "резкий сдвиг" in text
    assert "макс. час лонгов: $40.0M" in text and "— у дна" in text
    assert "💸 Фандинг" in text
    assert "📊 OI" in text and "от вершины" in text


def test_crowd_mirrors_price_at_top_and_bottom():
    df = _df()
    w = df[df.index >= df.index[-1] - pd.Timedelta(days=12)]
    text = "\n".join(market_lens.facts("BTCUSDT", df))
    at_top = f"на вершине {w.loc[w['h'].idxmax(), 'crowd']:.2f}"
    at_bottom = f"на дне {w.loc[w['l'].idxmin(), 'crowd']:.2f}"
    assert at_top in text and at_bottom in text
    assert w.loc[w["h"].idxmax(), "crowd"] < w.loc[w["l"].idxmin(), "crowd"]


def test_caption_fits_telegram_and_keeps_note():
    cap = market_lens.caption("ETHUSDT", _df())
    assert len(cap) <= market_lens.CAPTION_LIMIT
    assert cap.endswith("угадывать не берусь.") and "−0.64" in cap
    long = _df()
    cap2 = market_lens.caption("BTCUSDT", long)
    assert "−0.69" in cap2


def test_caption_drops_lines_from_end_when_too_long(monkeypatch):
    monkeypatch.setattr(market_lens, "facts", lambda sym, df: ["x" * 400, "y" * 400, "z" * 400])
    cap = market_lens.caption("BTCUSDT", None)
    assert len(cap) <= market_lens.CAPTION_LIMIT and "z" * 10 not in cap and "x" * 400 in cap


def test_structure_words():
    idx = pd.date_range("2026-10-20", periods=72, freq="1h", tz="UTC")
    falling = pd.DataFrame({"h": [100 - i for i in range(72)], "l": [90 - i for i in range(72)]}, index=idx)
    assert market_lens.structure(falling)[0].endswith("→ снижение")
    squeeze = pd.DataFrame({"h": [100 - i * 0.1 for i in range(72)], "l": [90 + i * 0.1 for i in range(72)]},
                           index=idx)
    assert market_lens.structure(squeeze)[0].endswith("→ сжатие")
    assert market_lens.structure(falling.iloc[:30]) is None


def test_render_returns_png():
    png = market_lens.render("BTCUSDT", _df())
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 20_000


def test_liq_hourly_reads_collector_file(tmp_path, monkeypatch):
    p = tmp_path / "liq.csv"
    p.write_text("ts_utc,exchange,side,qty,price\n"
                 "2026-10-24T14:05:00+00:00,bybit,long,2,80000\n"
                 "2026-10-24T14:40:00+00:00,okx,long,1,80000\n"
                 "2026-10-24T15:01:00+00:00,binance,short,0.5,80000\n"
                 "2026-10-24T15:02:00+00:00,bybit,long,,\n", encoding="utf-8")
    monkeypatch.setitem(market_lens.LIQ, "BTCUSDT", p)
    ll, ls = market_lens.liq_hourly("BTCUSDT", pd.Timestamp("2026-10-24", tz="UTC"))
    assert ll == {pd.Timestamp("2026-10-24 14:00", tz="UTC"): 240000.0}
    assert ls == {pd.Timestamp("2026-10-24 15:00", tz="UTC"): 40000.0}


def test_send_lens_toggle_and_symbol_isolation(monkeypatch):
    sent = []
    monkeypatch.setattr("services.grid_report.enabled", lambda key: key != "market_lens")
    regime_watch._send_lens(lambda png, cap: sent.append(cap))
    assert sent == []                                             # выключено ключом market_lens

    def build(sym):
        if sym == "BTCUSDT":
            raise RuntimeError("binance down")
        return b"png", f"cap {sym}"

    def no_compare(*a, **k):                                      # 28.10: сначала метрики CoinGlass; лёг — эта картинка
        raise RuntimeError("coinglass лёг")
    monkeypatch.setattr("services.grid_report.enabled", lambda key: True)
    monkeypatch.setattr("services.coinglass_web.compare_view.deliver", no_compare)
    monkeypatch.setattr(market_lens, "build", build)
    regime_watch._send_lens(lambda png, cap: sent.append(cap))
    assert sent == ["cap ETHUSDT"]                                # сбой BTC не трогает ETH
    regime_watch._send_lens(None)                                 # без фото-канала — ничего
