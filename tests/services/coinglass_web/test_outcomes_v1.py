"""Правила досверки v1 (разбор GPT 18.10): утро выбирается ДО фильтра исходов, окно — после времени получения
страницы, неполная сетка минут не принимается, ключ результата с версией, база эмпирическая."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np

from services.coinglass_web import outcomes as oc


def _snap(ts, captured=None, price=100.0, up=101.0, dn=99.0):
    r = {"ts": ts, "levels": {"price": price, "near": {"short_pct": 50, "short_pp_24h": 0},
                              "zones_short": [{"lo": up, "hi": up + 1, "strength": 5}, {"lo": up + 5, "hi": up + 6,
                                                                                         "strength": 9}],
                              "zones_long": [{"lo": dn - 1, "hi": dn, "strength": 7}]}}
    if captured:
        r["levels_captured"] = captured
    return r


def _minutes(a_ms, n, f):
    return [[a_ms + i * 60_000, "0", str(f(i)[0]), str(f(i)[1]), str(f(i)[2])] for i in range(n)]


def test_strongest_zone_nearest_edge_and_window_after_capture(monkeypatch):
    cap = "2026-10-19T05:00:30+00:00"                                   # 07:00:30 Варшавы
    r = _snap("2026-10-19T05:00:00+00:00", cap)
    a = (int(datetime.fromisoformat(cap).timestamp()) // 60 + 1) * 60_000
    seen = {}

    def fake(interval, start, end):
        seen.setdefault(interval, []).append(start)
        if interval == "1m" and start == a:
            return _minutes(a, 1440, lambda i: (106.5, 99.5, 100) if i == 100 else (100.5, 99.5, 100))
        if interval == "1h":
            return _minutes(start, 16, lambda i: (101, 99, 100))
        return [[start, "100", "100", "100", "100"]]
    monkeypatch.setattr(oc, "_klines", fake)
    monkeypatch.setattr(oc, "baseline", lambda du, dl, hist=None: {"n": 1, "upper": .3, "lower": .3, "both": .1,
                                                                    "none": .3})
    rec = oc.evaluate(r, datetime.fromisoformat(cap) + timedelta(days=2), hist={})
    assert rec["upper"] == 106.0                                        # сильнейшая зона шортов (сила 9), её нижний край
    assert rec["outcome"] == "upper" and rec["rules"] == oc.RULES
    assert seen["1m"][0] == a                                           # окно с минуты ПОСЛЕ получения страницы


def test_incomplete_minutes_wait_then_missing(monkeypatch):
    cap = "2026-10-19T05:00:30+00:00"
    r = _snap("2026-10-19T05:00:00+00:00", cap)
    a = (int(datetime.fromisoformat(cap).timestamp()) // 60 + 1) * 60_000
    monkeypatch.setattr(oc, "_klines", lambda iv, s, e: _minutes(a, 1439, lambda i: (100, 99.9, 100)))
    assert oc.evaluate(r, datetime.fromisoformat(cap) + timedelta(days=2), hist={}) is None
    rec = oc.evaluate(r, datetime.fromisoformat(cap) + timedelta(days=4), hist={})
    assert rec["outcome"] == "missing"


def test_morning_chosen_before_outcome_filter(tmp_path, monkeypatch):
    """Утро 07:00 с исходом «none» остаётся в таблице; более поздний «удачный» снимок того же дня его не заменяет."""
    monkeypatch.setattr(oc, "DIR", tmp_path)
    base = {"upper": .25, "lower": .25, "both": .0, "none": .5}
    rows = [{"ts": "x1", "horizon": "24h", "rules": oc.RULES, "captured": "2026-10-19T05:00:30+00:00",
             "outcome": "none", "base": base},
            {"ts": "x2", "horizon": "24h", "rules": oc.RULES, "captured": "2026-10-19T08:00:30+00:00",
             "outcome": "upper", "base": base}]
    (tmp_path / "outcomes.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    t = oc.table()
    assert t["n"] == 1 and t["obs"]["none"] == 1.0 and t["obs"]["upper"] == 0.0


def test_result_key_has_rules_version(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "DIR", tmp_path)
    (tmp_path / "outcomes.jsonl").write_text(json.dumps({"ts": "a", "horizon": "24h"}) + "\n", encoding="utf-8")
    assert oc._done() == {("a", "24h", "v0")}                          # старая запись без версии не блокирует v1


def test_empirical_baseline_counts():
    hist = {"h": np.arange(100), "high": np.full(100, 101.0), "low": np.full(100, 99.0),
            "close": np.full(100, 100.0), "atr": np.full(100, 2.0)}
    b = oc.baseline(0.25, 5.0, hist, horizon_h=24)                      # верх 100.5 задевается сразу, низ 90 — никогда
    assert b["upper"] == 1.0 and b["none"] == 0.0
    b = oc.baseline(0.25, 0.25, hist, horizon_h=24)                     # оба в одном часе
    assert b["both"] == 1.0
