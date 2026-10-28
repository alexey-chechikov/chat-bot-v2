"""28.10: сравнительная аналитика CoinGlass (tv_export, compare, compare_view) — без сети и без браузера."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from services import regime_watch
from services.coinglass_web import compare, compare_view, tv_export

T0 = pd.Timestamp("2026-10-01 00:00", tz="UTC")


# ─────────────── tv_export: разбор выгрузки и легенды ───────────────

SCHEMA = [{"type": "time"},
          {"sourceType": "series", "plotTitle": "open"}, {"sourceType": "series", "plotTitle": "high"},
          {"sourceType": "series", "plotTitle": "low"}, {"sourceType": "series", "plotTitle": "close"},
          {"sourceType": "study", "sourceId": "W", "plotTitle": "value"},
          {"sourceType": "study", "sourceId": "Q", "plotTitle": "Long"},
          {"sourceType": "study", "sourceId": "Q", "plotTitle": "Short"},
          {"sourceType": "study", "sourceId": "X", "plotTitle": "value"}]
IDS = {"wi2": "W", "liq_all": "Q"}


def test_rows_of_maps_columns_and_keeps_null():
    data = [[1792569600, 83130.3, 83686.2, 83065.0, 83213.6, 33.6, 249671.34, -7822716.46, 9.9],
            [1792573200, 1, 2, 0.5, 1.5, None, None, -62661.0, 1.0]]
    rows = tv_export.rows_of({"schema": SCHEMA, "data": data}, IDS)
    assert rows[1792569600] == {"open": 83130.3, "high": 83686.2, "low": 83065.0, "close": 83213.6, "wi2": 33.6,
                                "liq_all_long": 249671.34, "liq_all_short": -7822716.46}   # чужой индикатор X — мимо
    assert rows[1792573200]["wi2"] is None and rows[1792573200]["liq_all_long"] is None     # «∅» не становится нулём


def test_parse_shown_suffix_minus_and_empty():
    assert tv_export.parse_shown("−7.823M") == pytest.approx((-7.823e6, 500.0 + 1e-12))
    assert tv_export.parse_shown("33.6000")[0] == 33.6
    assert tv_export.parse_shown("∅") == (None, 0.0)
    with pytest.raises(ValueError):
        tv_export.parse_shown("abc")


def test_check_legend_matches_bar_by_ohlc_and_flags_mismatch():
    rows = {1792569600: {"open": 83130.3, "high": 83686.2, "low": 83065.0, "close": 83213.6, "wi2": 33.6,
                         "liq_all_long": 249671.34, "liq_all_short": -7822716.46},
            1792573200: {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "wi2": 1.0}}
    names = {"wi2": "<CoinGlass> Whale Index 2", "liq_all": "<CoinGlass> Совокупные ликвидации",
             "liq_coin": "<CoinGlass> Совокупные ликвидации (Coin-залогом)"}
    leg = {"series": ["BTCUSDT 1Ч Binance ОТКР83130.3МАКС83686.2МИН83065.0ЗАКР83213.6+83.4 (+0.10%)"],
           "studies": ["<CoinGlass> Whale Index 2 No Filter 33.6000",
                       "<CoinGlass> Совокупные ликвидации Long No Filter 249.671K −7.823M",
                       "<CoinGlass> Совокупные ликвидации (Coin-залогом) Long No Filter ∅ ∅"]}
    r = tv_export.check_legend(leg, rows, names)
    assert r["ok"] and r["bar"].startswith("2026-10-21T08:00") and len(r["checks"]) == 5
    leg["studies"][0] = "<CoinGlass> Whale Index 2 No Filter 30.0000"
    assert not tv_export.check_legend(leg, rows, names)["ok"]


def test_append_changes_writes_only_new_or_changed(tmp_path):
    obs = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    t1, t2 = int(datetime(2026, 10, 28, 8, tzinfo=timezone.utc).timestamp()), int(datetime(2026, 10, 28, 10, tzinfo=timezone.utc).timestamp())
    rows = {t1: {"close": 1.0, "wi2": 5.0}, t2: {"close": 2.0, "wi2": None}}
    assert tv_export.append_changes("BTCUSDT", rows, obs, base=tmp_path) == 2
    assert tv_export.append_changes("BTCUSDT", rows, obs, base=tmp_path) == 0
    rows[t2] = {"close": 2.5, "wi2": 7.0}
    assert tv_export.append_changes("BTCUSDT", rows, obs + timedelta(minutes=40), base=tmp_path) == 1
    recs = [json.loads(x) for x in (tmp_path / "BTCUSDT_1h.jsonl").read_text().splitlines()]
    assert [r["closed"] for r in recs] == [True, False, True]   # 10:00 закрыт к 11:10, не закрыт к 10:30


def test_load_tv_as_of_ignores_later_observations(tmp_path):
    obs1 = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    t = int(datetime(2026, 10, 28, 10, tzinfo=timezone.utc).timestamp())
    tv_export.append_changes("BTCUSDT", {t: {"close": 2.0, "wi2": 1.0}}, obs1, base=tmp_path)
    tv_export.append_changes("BTCUSDT", {t: {"close": 2.4, "wi2": 3.0}}, obs1 + timedelta(hours=1), base=tmp_path)
    assert compare.load_tv("BTCUSDT", asof=obs1 + timedelta(minutes=5), base=tmp_path)["wi2"].iloc[0] == 1.0
    assert compare.load_tv("BTCUSDT", base=tmp_path)["wi2"].iloc[0] == 3.0


# ─────────────── compare: источники ───────────────

def test_load_deriv_converts_funding_to_percent_and_counts_samples(tmp_path):
    p = tmp_path / "h.jsonl"
    since = datetime.now(timezone.utc) - timedelta(hours=3)
    t = since.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    lines = [{"last_updated": (t + timedelta(minutes=m)).isoformat(), "BTCUSDT": {
        "funding_rate_8h": 6.5e-05, "oi_native": 100.0 + m, "global_ls_ratio": 2.0, "top_trader_ls_ratio": 1.9}}
        for m in (0, 5, 10)]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    d = compare.load_deriv("BTCUSDT", since, path=p)
    row = d.loc[pd.Timestamp(t)]
    assert row["fr_premium_pct"] == pytest.approx(0.0065) and row["oi_native"] == 110.0 and row["deriv_samples"] == 3


def test_load_liq_uses_exchange_time_and_avg_price(tmp_path):
    day = datetime.now(timezone.utc).replace(hour=1, minute=0, second=0, microsecond=0)
    ex_ms = int((day + timedelta(minutes=59, seconds=59)).timestamp() * 1000)
    recs = [{"recv_ms": ex_ms + 5000, "exchange": "binance", "symbol": "BTCUSDT", "side_liquidated": "long",
             "exchange_ts_ms": ex_ms, "qty": "0.5", "price": "79000", "raw": {"ap": "80000"}},
            {"recv_ms": ex_ms, "exchange": "binance", "symbol": "ETHUSDT", "side_liquidated": "long",
             "exchange_ts_ms": ex_ms, "qty": "1", "price": "2000", "raw": {}}]
    (tmp_path / f"binance_{day:%Y%m%d}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    d = compare.load_liq("BTCUSDT", day - timedelta(hours=1), base=tmp_path)
    assert d.loc[pd.Timestamp(day), "our_liq_long"] == 40000.0      # час биржи 01:00, хотя приём — 02:00:04
    assert d.loc[pd.Timestamp(day), "our_liq_events"] == 1


# ─────────────── compare: z без будущего, эпизоды ───────────────

def _frame(n: int = 400, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(T0, periods=n, freq="1h")
    close = 80000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    df = pd.DataFrame(index=idx)
    df["px_close"] = close
    df["px_open"] = np.r_[close[0], close[:-1]]
    df["px_high"] = np.maximum(df["px_open"], close) * 1.001
    df["px_low"] = np.minimum(df["px_open"], close) * 0.999
    df["close"] = close
    df["volume_usd"] = rng.uniform(2e8, 3e8, n)
    df["taker_delta"] = rng.normal(0, 300, n)
    df["bid_ask_delta"] = rng.normal(0, 500, n)
    df["liq_all_long"] = rng.uniform(1e5, 1e6, n)
    df["liq_all_short"] = -rng.uniform(1e5, 1e6, n)
    df["oi_coins"] = 95000 * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))
    df["fr_pct"] = 0.005 + rng.normal(0, 0.0003, n)
    df["ls_acc"] = 2 + np.cumsum(rng.normal(0, 0.005, n))
    df["ls_top_pos"] = 1.8 + np.cumsum(rng.normal(0, 0.005, n))
    df["wi2"] = np.cumsum(rng.normal(0, 1, n))
    return df


def test_zscores_have_no_lookahead():
    df = _frame()
    z1 = compare.zscores(df)
    df2 = df.copy()
    df2.iloc[300:, :] = df2.iloc[300:, :] * 3                    # будущее после часа 299 переписано
    z2 = compare.zscores(df2)
    pd.testing.assert_frame_equal(z1.iloc[:300], z2.iloc[:300])


def test_episode_needs_three_families_not_three_related_ratios():
    df = _frame()
    h = df.index[350]
    df.loc[h, "px_close"] *= 0.97                                 # цена −3%
    df.loc[h, "px_low"] = df.loc[h, "px_close"] * 0.998
    df.loc[h, "taker_delta"] = -9000                              # продают рынком
    df.loc[h, "liq_all_long"] = 6e7                               # вынос лонгов
    p = df.index[380]
    for c, dv in (("ls_acc", 0.5), ("ls_top_pos", 0.5), ("wi2", 60)):   # только «позиции» — родственные ряды
        df.loc[p:, c] += dv
    eps = compare.find_episodes(df, compare.zscores(df), df.index[200], closed_before=df.index[-1])
    starts = [e["start"] for e in eps]
    assert h in starts and p not in starts


def test_describe_long_flush_and_after_only_when_matured():
    df = _frame()
    h = df.index[350]
    df.loc[h:, ["px_close", "px_open", "px_high", "px_low"]] *= 0.97
    df.loc[h, "px_open"] = df.loc[df.index[349], "px_close"]
    df.loc[h, "taker_delta"] = -9000
    df.loc[h, "liq_all_long"] = 6e7
    df.loc[h:, "oi_coins"] *= 0.97
    ep = {"start": h, "end": h, "peak": h, "score": 30.0, "metrics": ["price", "taker", "liq_long", "oi"]}
    d = compare.describe(df, ep, now=(h + pd.Timedelta(hours=8)).to_pydatetime())
    assert d["direction"] == "падение" and "совместима с закрытием лонгов, в том числе принудительным" in d["main"]
    assert any("агрессивнее сторона движения" in x for x in d["agree"])
    assert any("преобладали ликвидации лонгов на падении" in x for x in d["agree"])
    assert d["after"]["6h"] is not None and d["after"]["24h"] is None   # сутки ещё не прошли — исхода нет
    assert "−" in d["main"] and "-3" not in d["main"]
    assert d["hypothesis"]["side"] == -1 and "не будет обновлён закрытием часа" in d["watch"]


def test_now_summary_strength_against_past_week():
    df = _frame()
    df.loc[df.index[-7]:, "taker_delta"] = -3000                  # последние часы — сильные продажи
    lines = compare.now_summary(df, (df.index[-1] + pd.Timedelta(minutes=30)).to_pydatetime(), "BTC")
    assert lines[0].startswith("Чистая дельта тейкеров 6 ч") and "агрессивнее продавцы" in lines[0]
    assert "сильнее обычного" in lines[0]


def test_composite_v2_logs_in_slot_once_then_outcome(tmp_path, monkeypatch):
    df = _frame(600)                                              # данные дальше дня решения + суток исхода
    df["bid_ask_delta"] = np.linspace(-100, 100, len(df))
    df["fr_pct"] = np.linspace(0.001, 0.01, len(df))
    df["ls_acc"] = np.linspace(1, 2, len(df))
    df["wi2"] = np.linspace(-50, 50, len(df))
    day = df.index[480].floor("1D")
    c = compare.composite(df, day)
    assert c["S"] == 4 and c["pos"] == 4 and c["call"] == 1
    monkeypatch.setattr(compare, "binance_open_at", lambda sym, t: float(df.at[pd.Timestamp(t).floor("1h"), "px_open"]))
    path = tmp_path / "comp.jsonl"
    early = (day + pd.Timedelta(hours=2)).to_pydatetime()         # до окна 06–08 UTC — решения нет
    assert compare.log_composite("BTCUSDT", df, early, path=path)["call"] is None and not path.exists()
    now = (day + pd.Timedelta(hours=6, minutes=2)).to_pydatetime()
    compare.log_composite("BTCUSDT", df, now, path=path)
    compare.log_composite("BTCUSDT", df, now, path=path)          # повтор — без дубля
    recs = [json.loads(x) for x in path.read_text().splitlines()]
    assert [r["kind"] for r in recs] == ["call"] and recs[0]["v"] == "comp-2" and recs[0]["call"] == 1
    assert recs[0]["execution_at"] == (day + pd.Timedelta(hours=6, minutes=3)).isoformat()
    later = (day + pd.Timedelta(hours=31)).to_pydatetime()        # следующий день 07:00 — свой вызов и исход вчерашнего
    compare.log_composite("BTCUSDT", df, later, path=path)
    out = [json.loads(x) for x in path.read_text().splitlines() if '"outcome"' in x]
    assert len(out) == 1 and out[0]["hit"] is not None and compare.composite_stats("BTCUSDT", path)["n"] == 1
    late = (day + pd.Timedelta(hours=57)).to_pydatetime()         # третий день, 09:00 — окно пропущено
    compare.log_composite("BTCUSDT", df, late, path=path)
    assert json.loads(path.read_text().splitlines()[-1])["kind"] in ("skip", "outcome")
    assert any(json.loads(x).get("kind") == "skip" for x in path.read_text().splitlines())


def test_log_episodes_final_once_with_lag(tmp_path):
    df = _frame()
    h = df.index[350]
    df.loc[h, "px_close"] *= 0.97
    df.loc[h, "taker_delta"] = -9000
    df.loc[h, "liq_all_long"] = 6e7
    path = tmp_path / "ep.jsonl"
    now = (df.index[-1] + pd.Timedelta(minutes=30)).to_pydatetime()
    z = compare.zscores(df)
    n1 = compare.log_episodes("BTCUSDT", df, z, now, path=path)
    assert n1 >= 1 and compare.log_episodes("BTCUSDT", df, z, now, path=path) == 0
    rec = next(json.loads(x) for x in path.read_text().splitlines() if '"final"' in x and h.isoformat() in x)
    assert rec["fixed_after_end_h"] > 40 and "after" not in rec   # найден задним числом — видно по задержке


def test_checks_detect_aligned_hours():
    df = _frame(60)
    df["bn_close"] = df["close"]
    ck = compare.checks(df)
    assert ck["close_cg_vs_binance"]["share_exact"] == 1.0 and ck["close_shifted_1h_max_rel_diff"] > 0
    assert ck["duplicate_bars"] == 0


# ─────────────── compare_view и доставка ───────────────

def _payload():
    df = _frame()
    df["taker_buy"] = np.abs(df["taker_delta"]) + 500
    df["taker_sell"] = -(df["taker_buy"] - df["taker_delta"])
    paid = pd.DataFrame({"paid_pct": [0.01, 0.008]}, index=[df.index[-20], df.index[-12]])
    now = (df.index[-1] + pd.Timedelta(minutes=30)).to_pydatetime()
    return compare_view.payload("BTCUSDT", now, data=(df, paid, {"checks": compare.checks(df), "errors": {}}))


@pytest.fixture(autouse=True)
def _no_live_journals(tmp_path, monkeypatch):
    """Показ не читает живые журналы и прогоны мака."""
    from services.coinglass_web import scenarios
    monkeypatch.setattr(scenarios, "JOURNAL", tmp_path / "shadow.jsonl")
    monkeypatch.setattr(tv_export, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.setattr(compare, "COMPOSITE", tmp_path / "comp.jsonl")


def test_payload_keeps_payments_apart_and_caption_fits():
    p = _payload()
    assert p["scenario"] and p["scenario"]["source"].startswith("расчёт по графику")
    assert compare_view.caption(p).splitlines()[1].startswith("🧭 Состояние:")
    assert "paid_pct" not in p["s"] and len(p["paid"]["t"]) == 2   # выплаты — точками, не линией ставки
    assert len(compare_view.caption(p)) <= compare_view.CAPTION_LIMIT
    cov = {r["key"]: r for r in p["coverage"]}
    assert cov["wi2"]["missing"] == 0 and cov["our_liq_long"]["missing"] == cov["our_liq_long"]["hours"]


def test_render_html_both_variants_and_png():
    p = _payload()
    full = compare_view.render_html({"BTCUSDT": p})
    part = compare_view.render_html({"BTCUSDT": p}, standalone=False)
    assert full.startswith("<!doctype html>") and "</body></html>" in full and "plotly.js-dist-min@2.35.2" in full
    assert "<html" not in part and "<body>" not in part and "<title>" in part and "</style>" in part
    assert part.count("<script") == 3                             # plotly, данные, код
    assert compare_view.render_png(p)[:8] == b"\x89PNG\r\n\x1a\n"


def test_send_lens_prefers_compare_and_sends_html(monkeypatch):
    photos, docs = [], []
    monkeypatch.setattr("services.grid_report.enabled", lambda key: True)
    monkeypatch.setattr(compare_view, "build_all", lambda now=None, symbols=None: {
        "photos": [(b"a", "A"), (b"b", "B")], "html": b"<html>", "filename": "metrics_x.html"})
    regime_watch._send_lens(lambda png, cap: photos.append(cap), doc_fn=lambda d, n, c: docs.append(n))
    assert photos == ["A", "B"] and docs == ["metrics_x.html"]
