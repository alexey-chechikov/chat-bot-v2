"""Регрессии по разбору GPT e53a117 (P1/P2): каждый тест падает на b740c02/ee19c78 именно на дефекте.
Импортирует только модули, существовавшие до исправления (compare, tv_export) — чтобы прогон на старом коммите
показывал дефект, а не смену интерфейса. Без сети и браузера."""
from __future__ import annotations

import functools
import json
import sys
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from services.coinglass_web import compare, tv_export

T0 = pd.Timestamp("2026-10-01 00:00", tz="UTC")


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


# ─────────── P1: прогноз «3 из 4» с ценой входа до момента решения ───────────

def test_composite_outcome_starts_after_decision_not_at_midnight(tmp_path, monkeypatch):
    """Решение записано в 06:02 — исход не должен включать рост 00:00–06:00, который признаки уже видели."""
    df = _frame(600)
    df["bid_ask_delta"] = np.linspace(-100, 100, len(df))       # все 4 линии вверх → вывод +1
    df["fr_pct"] = np.linspace(0.001, 0.01, len(df))
    df["ls_acc"] = np.linspace(1, 2, len(df))
    df["wi2"] = np.linspace(-50, 50, len(df))
    day = df.index[480].floor("1D")
    px = np.where(df.index < day, 100.0, np.where(df.index < day + pd.Timedelta(hours=6),
                                                  100 + 5 * (df.index - day) / pd.Timedelta(hours=6), 105.0))
    for c in ("px_close", "px_open", "px_high", "px_low", "close"):
        df[c] = px
    monkeypatch.setattr(compare, "binance_open_at",
                        lambda sym, t: float(df.at[pd.Timestamp(t).floor("1h"), "px_open"]), raising=False)
    path = tmp_path / "comp.jsonl"
    compare.log_composite("BTCUSDT", df, (day + pd.Timedelta(hours=6, minutes=2)).to_pydatetime(), path=path)
    compare.log_composite("BTCUSDT", df, (day + pd.Timedelta(hours=31)).to_pydatetime(), path=path)
    out = [json.loads(x) for x in path.read_text().splitlines()]
    out = [r for r in out if r["kind"] == "outcome" and r["day"] == day.strftime("%Y-%m-%d")]
    assert len(out) == 1
    assert abs(out[0]["ret_24h_pct"]) < 0.5                     # было +5%: рост до решения засчитывался в исход


def test_composite_needs_three_nonzero_signs(tmp_path):
    """Два плюса и два нуля — не «три согласные линии» (было S = 2 → записан вывод +1)."""
    df = _frame(300)
    df["bid_ask_delta"] = np.linspace(-100, 100, len(df))
    df["fr_pct"] = np.linspace(0.001, 0.01, len(df))
    df["ls_acc"] = 2.0                                            # наклон ровно 0
    df["wi2"] = 5.0
    day = df.index[200].floor("1D")
    path = tmp_path / "comp.jsonl"
    compare.log_composite("BTCUSDT", df, (day + pd.Timedelta(hours=6, minutes=2)).to_pydatetime(), path=path)
    calls = [json.loads(x) for x in path.read_text().splitlines() if '"call"' in x]
    assert len(calls) == 1 and calls[0]["S"] == 2
    assert calls[0]["call"] == 0


# ─────────── P1: пропуски сжимали окна «6/24 ч» ───────────

def test_now_summary_window_is_calendar_and_shows_coverage():
    df = _frame()
    last = df.index[-1]
    df.loc[last - pd.Timedelta(hours=5):, "taker_delta"] = -500.0
    df.loc[last - pd.Timedelta(hours=7):last - pd.Timedelta(hours=6), "taker_delta"] = -400.0
    df.loc[[last - pd.Timedelta(hours=1), last - pd.Timedelta(hours=3)], "taker_delta"] = np.nan   # 2 пропуска
    lines = compare.now_summary(df, (last + pd.Timedelta(minutes=30)).to_pydatetime(), "BTC")
    six = lines[0]                                                # час last не закрыт: окно — last−6 … last−1
    assert "4 из 6" in six                                        # было: 6 непустых за 8 часов как «6 ч»
    assert compare._n(-1900.0, True) in six                       # сумма — только по 4 настоящим часам окна


def test_now_summary_day_ago_is_the_exact_hour():
    df = _frame()
    df["ls_acc"] = np.linspace(1, 9, len(df))                    # 0.02 за час — соседние часы различимы в 2 знаках
    last = df.index[-1]
    df.loc[[last - pd.Timedelta(hours=k) for k in (2, 5, 9)], "ls_acc"] = np.nan
    lines = compare.now_summary(df, (last + pd.Timedelta(minutes=30)).to_pydatetime(), "BTC")
    line = next(x for x in lines if x.startswith("Толпа L/S"))
    closed = last - pd.Timedelta(hours=1)                         # last не закрыт к last+30 мин
    want = f"{df.at[closed - pd.Timedelta(hours=24), 'ls_acc']:.2f}"
    assert f"Толпа L/S {df.at[closed, 'ls_acc']:.2f} (24 ч назад {want})" == line   # было: 25-я непустая запись


# ─────────── P1: исход эпизода считался от заново выделенного конца ───────────

def _hot(df, t, k=1.0):
    df.loc[t:, ["px_close", "px_open", "px_high", "px_low", "close"]] *= 1 - 0.03 * k
    df.loc[t, "px_open"] = df.loc[t - pd.Timedelta(hours=1), "px_close"]
    df.loc[t, "taker_delta"] = -9000
    df.loc[t, "liq_all_long"] = 6e7


def test_episode_outcome_uses_stored_contract_when_group_grows(tmp_path):
    df = _frame()
    h10, h13 = df.index[350], df.index[353]
    _hot(df, h10)
    _hot(df, h13)
    path = tmp_path / "ep.jsonl"
    z = compare.zscores(df)
    now1 = (h10 + pd.Timedelta(hours=2, minutes=30)).to_pydatetime()   # закрыты часы до h11, h13 ещё впереди
    view1 = df[df.index < pd.Timestamp(now1).floor("1h")]
    compare.log_episodes("BTCUSDT", view1, compare.zscores(view1), now1, path=path)
    first = [json.loads(x) for x in path.read_text().splitlines()]
    first = [r for r in first if r.get("start") == h10.isoformat() and r.get("kind") != "outcome"]
    assert len(first) == 1 and first[0]["end"] == h10.isoformat()
    now2 = (h13 + pd.Timedelta(hours=30)).to_pydatetime()
    compare.log_episodes("BTCUSDT", df, z, now2, path=path)
    recs = [json.loads(x) for x in path.read_text().splitlines()]
    ep = [r for r in recs if r.get("start") == h10.isoformat() and r.get("kind") != "outcome"]
    assert ep[0]["end"] == h10.isoformat()                        # первая запись не переписана
    assert any(r["end"] == h13.isoformat() for r in ep[1:])       # расширение — новой записью
    rec = ep[0]
    ref_t = pd.Timestamp(rec.get("ref_time") or (pd.Timestamp(rec["end"]) + pd.Timedelta(hours=1)).isoformat())
    ref_px = rec.get("ref_price", rec["numbers"]["price"]["end"])
    want = (df.at[ref_t + pd.Timedelta(hours=5), "px_close"] / ref_px - 1) * 100
    outs = [r for r in recs if r.get("kind") == "outcome" and r.get("h") == "6h" and
            (r.get("ref", "").startswith(f"BTCUSDT:{h10:%Y-%m-%dT%H}|{rec['kind']}|") or r.get("start") == rec["start"])]
    assert outs, "исход первой записи не посчитан"
    got = outs[0].get("ret_pct", outs[0].get("price_pct"))
    assert got == pytest.approx(want, abs=1e-6)                   # было: от конца 13:00 вместо сохранённого


# ─────────── P1: несверенная выгрузка попадала в рабочие данные ───────────

def test_unverified_export_goes_to_quarantine_not_working_log(tmp_path, monkeypatch):
    main, quar = tmp_path / "tv", tmp_path / "q"
    monkeypatch.setattr(tv_export, "DIR", main)
    monkeypatch.setattr(tv_export, "QUARANTINE", quar, raising=False)
    monkeypatch.setattr(tv_export, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.setattr(tv_export, "append_changes", functools.partial(tv_export.append_changes, base=main))
    t = int(datetime(2026, 10, 28, 8, tzinfo=timezone.utc).timestamp())
    obs = datetime(2026, 10, 28, 10, 1, tzinfo=timezone.utc)
    fake = {"sym": "BTCUSDT", "obs": obs, "rows": {t: {"close": 1.0, "wi2": 5.0}}, "setup": {"names": {}},
            "checks": [{"ok": False, "why": "бар по OHLC не однозначен (0)"}], "stable": True, "seconds": 1.0,
            "export_resolution": "60", "export_symbol": "BINANCE:BTCUSDT"}
    monkeypatch.setattr(tv_export, "export_symbol", lambda br, sym, days=21: fake)

    class _Br:
        def close(self):
            pass

    class _CM:
        def __enter__(self):
            return types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda headless=True: _Br()))

        def __exit__(self, *a):
            return False

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _CM()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    s = tv_export.collect(("BTCUSDT",))
    assert s["symbols"]["BTCUSDT"]["status"] == "check"
    assert compare.load_tv("BTCUSDT", base=main).empty           # было: записано в рабочий журнал
    q = compare.load_tv("BTCUSDT", base=quar)
    assert len(q) == 1 and not bool(q["verified"].iloc[0])


# ─────────── P1: частичный снимок бара считался окончательным ───────────

def test_frame_ignores_bar_whose_last_record_was_before_close(tmp_path):
    t1 = int(datetime(2026, 10, 28, 8, tzinfo=timezone.utc).timestamp())
    t2 = t1 + 3600
    tv_export.append_changes("BTCUSDT", {t1: {"close": 1.0, "wi2": 5.0}, t2: {"close": 2.0, "wi2": 7.0}},
                             datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc), base=tmp_path)
    tv = compare.load_tv("BTCUSDT", base=tmp_path)
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)    # по часам 09:00 давно закрыт, а запись — с 09:30
    df, _p, _m = compare.frame("BTCUSDT", now, days=1, tv=tv, deriv=pd.DataFrame(), liq=pd.DataFrame(),
                               binance=(pd.DataFrame(), pd.DataFrame()))
    assert df.at[pd.Timestamp(t1, unit="s", tz="UTC"), "wi2"] == 5.0
    assert pd.isna(df.at[pd.Timestamp(t2, unit="s", tz="UTC"), "wi2"])


# ─────────── P2: неизвестное становилось утверждением ───────────

def test_explain_keeps_unknown_oi_and_liquidations_unknown():
    df = _frame()
    df["oi_coins"] = np.nan
    df["liq_all_long"] = np.nan
    df["liq_all_short"] = np.nan
    h = df.index[350]
    df.loc[h:, ["px_close", "px_open", "px_high", "px_low"]] *= 1.02
    df.loc[h, "px_open"] = df.loc[df.index[349], "px_close"]
    ep = {"start": h, "end": h, "peak": h, "score": 10.0, "metrics": ["price", "taker"]}
    d = compare.describe(df, ep, now=(h + pd.Timedelta(hours=2)).to_pydatetime())
    assert d["direction"] == "рост"
    assert "OI: нет данных" in d["main"] and "Новые покупатели" not in d["main"]   # было «Новые покупатели… OI нет данных»
    assert "$0K" not in d["main"] and "нет данных" in d["main"]


def test_explain_small_oi_change_is_its_own_branch():
    df = _frame()
    h = df.index[350]
    df.loc[h:, ["px_close", "px_open", "px_high", "px_low"]] *= 0.98
    df.loc[h, "px_open"] = df.loc[df.index[349], "px_close"]
    df.loc[df.index[349]:, "oi_coins"] = df.at[df.index[349], "oi_coins"] * 1.0005   # +0.05% — «почти не изменился»
    ep = {"start": h, "end": h, "peak": h, "score": 10.0, "metrics": ["price", "taker"]}
    d = compare.describe(df, ep, now=(h + pd.Timedelta(hours=2)).to_pydatetime())
    assert "почти не изменился" in d["main"] and "Новые продавцы" not in d["main"]


# ─────────── вопрос 2: нулевой разброс — заданная ветка ───────────

def test_robust_z_zero_mad_is_defined():
    s = pd.Series([0.0] * 200 + [0.002], index=pd.date_range(T0, periods=201, freq="1h"))
    z = compare._robust_z(s)
    assert z.iloc[-1] >= compare.Z and z.iloc[-2] == 0.0          # было NaN: изменение после недели без движения
