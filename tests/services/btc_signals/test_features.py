"""Признаки сделки: без заглядывания вперёд, путь сделки, история, балл M2, строки таблицы в службе."""
from __future__ import annotations

import json

import numpy as np
import pytest

from services.btc_signals import engine as en
from services.btc_signals import features as fx
from services.btc_signals import run as rn

T0 = 1_700_000_000 // 86400 * 86400


def rich(n=24 * 260, seed=3):
    """Почасовые ряды со всеми полями, которые читает features.prepare (значения 4ч — ступеньки по 4 часа)."""
    g = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(g.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    t = T0 + 3600 * (np.arange(n) + 1)
    j = (t - 1) // 14400
    j = j - j[0]
    step = lambda x: x[np.r_[np.flatnonzero(np.r_[True, j[1:] != j[:-1]])][j]]  # noqa: E731
    ema = lambda x, k: en.ema(x, k)  # noqa: E731
    a = {"t": t, "o": o, "h": h, "l": l, "c": c, "j": j, "i0": 24 * 30,
         "f_close": step(c), "f_G": step(ema(c, 50)), "f_Y": step(ema(c, 100)), "f_R": step(ema(c, 200)), "f_B": step(ema(c, 300)), "B4p": step(ema(c, 300)),
         "atr4": np.full(n, 1.0), "B1h": ema(c, 200), "R1": ema(c, 150), "f_B1": ema(c, 200),
         "order": np.zeros(n), "f_width_rank": np.full(n, 0.5), "er24": np.full(n, 0.3), "f_adx": np.full(n, 20.0),
         "x_hi30": np.maximum.accumulate(h), "x_lo30": np.minimum.accumulate(l), "flat": np.zeros(n), "phase": np.array(["рост"] * n, object),
         "F": np.cumsum(np.full(n, 0.001)), "run_B1": np.zeros(n), "run_R": np.zeros(n), "f_run_G_prev": np.zeros(n)}
    for k in "GYRB":
        a[f"f_run_{k}"] = np.sign(a["f_close"] - a[f"f_{k}"])
    a["st"] = np.zeros((n, 15))
    lay = (np.full(n, 0.5), np.full(n, en.DIV))
    return a, lay


def cut(a, m):
    return {k: (v[:m] if isinstance(v, np.ndarray) else v) for k, v in a.items()}


def test_prepare_has_no_lookahead():
    a, lay = rich()
    full = fx.prepare(a, lay)
    for i in (24 * 120 + 5, 24 * 200 + 3, len(a["t"]) - 30):
        part = fx.prepare(cut(a, i + 1), (lay[0][:i + 1], lay[1][:i + 1]))
        for k, v in full.items():
            if k.startswith("_"):
                continue
            x, y = v[i], part[k][i]
            assert (np.isnan(x) and np.isnan(y)) or x == pytest.approx(y, rel=1e-9, abs=1e-12), (k, i, x, y)


def test_prepare_values_make_sense():
    a, lay = rich()
    P = fx.prepare(a, lay)
    i = 24 * 200
    assert P["от зелёной, ATR"][i] == pytest.approx(a["f_close"][i] - a["f_G"][i])
    assert 0 <= P["линий ниже цены"][i] <= 4 and 0 <= P["пар в порядке роста"][i] <= 6
    assert P["ход 24ч, %"][i] == pytest.approx((a["c"][i] / a["c"][i - 24] - 1) * 100)
    assert P["фандинг 7д, %"][i] == pytest.approx(0.001 * 168)
    assert 0 <= P["RSI 1ч"][i] <= 100 and np.isfinite(P["от SMA100 дня, %"][i])
    assert np.isnan(P["объём сутки к медиане 30д"][i])
    r = fx.row(P, a, i)
    assert r["фаза"] == "рост" and len(r["порядок линий"]) == 7


def test_path_long_and_short():
    a, _ = rich(n=24 * 40)
    a["h"][:] = 100.0
    a["l"][:] = 100.0
    a["c"][:] = 100.0
    a["atr4"][:] = 2.0
    a["h"][11], a["l"][13] = 106.0, 97.0
    p = fx.path(a, 10, 15, 1, 100.0, 101.0)
    assert p["MFE, ATR"] == pytest.approx(3.0) and p["MAE, ATR"] == pytest.approx(1.5)
    assert p["часов до MFE"] == 1 and p["часов до MAE"] == 3 and p["сначала +1 ATR или −1 ATR"] == 1.0
    assert p["отдача, ATR"] == pytest.approx(2.5) and p["часов в сделке"] == 5
    s = fx.path(a, 10, 15, -1, 100.0, 99.0)
    assert s["MFE, ATR"] == pytest.approx(1.5) and s["MAE, ATR"] == pytest.approx(3.0) and s["сначала +1 ATR или −1 ATR"] == -1.0


def test_history_only_closed_before_entry():
    prev = [(0, 3600, 1, 2.0), (7200, 10 * 3600, -1, -1.0), (20 * 3600, 40 * 3600, 1, 5.0)]
    h = fx.history(prev, 30 * 3600, -1)
    assert h["прошлая сделка, % базы"] == -1.0 and h["прошлая та же сторона"] == 1.0 and h["часов после прошлой"] == 20
    assert h["из 5 прошлых в плюсе"] == 1.0 and h["итог 30д, % базы"] == pytest.approx(1.0)
    assert fx.history([], 100, 1)["прошлая сделка, % базы"] is None


def test_m2_score_in_unit_range_and_monotone():
    m = fx.m2_load()
    assert m is not None and len(m["coef"]) == len(fx.M2_FEATS)
    x = np.zeros(len(fx.M2_FEATS))
    j = int(np.argmax(m["coef"]))
    lo, hi = x.copy(), x.copy()
    lo[j], hi[j] = -3 * m["scale"][j] + m["mean"][j], 3 * m["scale"][j] + m["mean"][j]
    s_lo, s_hi = fx.m2_score(m, lo), fx.m2_score(m, hi)
    assert 0.0 <= s_lo < s_hi <= 1.0


def test_feature_rows_entry_exit_and_errors():
    a, lay = rich()
    a["st"] = np.zeros((len(a["t"]), 15))
    i0, i1 = 24 * 150, 24 * 160
    pos = {"side": 1, "tag": "над синей", "entry": float(a["c"][i0]), "entry_t": int(a["t"][i0]), "entry_i": i0, "w": 1.0, "atr": 1.0,
           "add_lv": 0.0, "add_done": False, "add_px": None, "add_t": None}
    ent = {"kind": "вход", "t": int(a["t"][i0]), "i": i0, "side": 1, "tag": "над синей", "px": pos["entry"], "pos": pos}
    ex = {"kind": "выход", "t": int(a["t"][i1]), "i": i1, "side": 1, "tag": "над синей", "px": float(a["c"][i1]), "why": "x", "res": 1.5, "pos": pos}
    R = {"a": a, "lay": lay, "h4f": None, "ev": [ent, ex], "ev432": []}
    rows = rn.feature_rows(R, [ent, ex], 0)
    assert rows[0]["features"]["прошлая сделка, % базы"] is None and 0 <= rows[0]["m2_score"] <= 1
    assert rows[1]["res"] == 1.5 and rows[1]["path"]["часов в сделке"] == 240
    bad = dict(R, a={k: v for k, v in a.items() if k != "f_adx"})
    rows = rn.feature_rows(bad, [ent], 0)
    assert "error" in rows[0] and "features" not in rows[0]


def test_describe_places_value_among_history():
    ref = {"types": {"лонг над синей": [
        {"feat": "от красной, ATR", "q": list(np.linspace(0, 10, 101)), "n": 320, "note": "выше значение — ход обычно больше"},
        {"feat": "ADX 4ч", "q": list(np.linspace(10, 50, 101)), "n": 320, "note": ""},
        {"feat": "нет такого", "q": list(np.linspace(0, 1, 101)), "n": 320, "note": ""}]}}
    row = {"side": 1, "tag": "над синей", "features": {"от красной, ATR": 8.56, "ADX 4ч": 20.2}}
    d = rn.describe(row, ref)
    assert d[0].startswith("Описание входа (320 таких сделок")
    assert d[1] == "• от красной +8.6 ATR — больше, чем у 85% таких входов (выше значение — ход обычно больше)"
    assert d[2] == "• ADX 4ч 20.2 — больше, чем у 25% таких входов" and len(d) == 3
    assert rn.describe({"side": -1, "tag": "под синей", "features": {}}, ref) == []
    assert rn.describe({"side": 1, "tag": "над синей", "error": "x"}, ref) == []


def test_entry_message_carries_description(tmp_path, monkeypatch):
    from tests.services.btc_signals.test_btc_signals import long_case, wire
    a, lay = long_case()
    box = {"m": 3}
    sent = []
    wire(monkeypatch, tmp_path, a, lay, box, lambda text: sent.append(text) or True)
    fake = {"key": None, "side": 1, "tag": "над синей", "features": {"ADX 4ч": 30.2}}

    def frows(R, events, now):
        return [dict(fake, key=rn.ev_key(e), kind=e["kind"]) for e in events]
    monkeypatch.setattr(rn, "feature_rows", frows)
    monkeypatch.setattr(rn, "REF", tmp_path / "ref.json")
    (tmp_path / "ref.json").write_text(json.dumps({"types": {"лонг над синей": [{"feat": "ADX 4ч", "q": list(np.linspace(10, 50, 101)), "n": 10, "note": ""}]}}))
    assert rn.main() == 0
    box["m"] = 5
    assert rn.main() == 0
    assert "ЛОНГ над синей — вход" in sent[-1] and "• ADX 4ч 30.2 — больше, чем у 50% таких входов" in sent[-1]
    box["m"] = 11
    assert rn.main() == 0
    assert "добор" in sent[-1] and "Описание входа" not in sent[-1]


def test_main_writes_feature_rows_once(tmp_path, monkeypatch):
    from tests.services.btc_signals.test_btc_signals import long_case, wire
    a, lay = long_case()
    box = {"m": 3}
    sent = []
    wire(monkeypatch, tmp_path, a, lay, box, lambda text: sent.append(text) or True)
    monkeypatch.setattr(rn, "FEATURES", tmp_path / "f.jsonl")
    assert rn.main() == 0
    box["m"] = 17
    assert rn.main() == 0
    box["m"] = 18
    assert rn.main() == 0
    rows = [json.loads(x) for x in (tmp_path / "f.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["вход", "добор", "выход"]
    assert rows[0]["key"].startswith("вход|") and "error" in rows[0]
    assert rows[2]["path"]["часов в сделке"] == 12
