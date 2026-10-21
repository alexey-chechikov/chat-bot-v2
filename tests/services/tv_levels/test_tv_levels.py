"""Уровни для TradingView (21.10): сборка из учёта сеток и прогноза дня, строка для индикатора, отправка после карточки."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from services import regime_watch, tv_levels

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
COLLECT = tv_levels.collect                                     # до подмены в тестах отправки


def _lot(entry, qty, tp):
    return {"entry": entry, "qty": qty, "tp": tp, "tp_order": {}, "t": 0.0, "parent": "x"}


def _grids(tmp_path: Path):
    grid = {"step_pct": 0.6, "target_pct": 1.4, "order_qty": "0.0012", "max_lots_per_side": 50}
    cfgs = {"BTC": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **grid},
            "B34": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **grid, "step_pct": 0.1,
                    "max_lots_per_side": 4},
            "XAU": {"symbol": "XAUUSDT", "enabled": True, "dry_run": True},       # холостая — не показывать
            "B49": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False},      # учёт битый
            "ETH": {"symbol": "ETHUSDT", "enabled": False, "dry_run": False}}     # выключена
    states = {
        "BTC": {"LONG": {"entry": {"price": 83127.2}, "lots": [_lot(84000.0, "0.0012", 85176.0)]}},
        "B34": {"LONG": {"entry": {"price": 83316.3}, "lots": [_lot(83400.0, "0.0012", 83683.3),
                                                              _lot(83500.0, "0.0024", 83784.0)]}},
        "XAU": {"LONG": {"entry": {"price": 4000.0}, "lots": [_lot(4100.0, "0.023", 4112.3)]}},
    }
    for name, st in states.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "B49.json").write_text("{битый", encoding="utf-8")
    return tv_levels.grid_levels(names=list(cfgs), peek=cfgs.get, state_path=lambda n: tmp_path / f"{n}.json")


def test_grid_levels_live_only_weighted_avg_and_nearest_tp(tmp_path):
    g = _grids(tmp_path)
    assert set(g) == {"BTCUSDT"}                                  # XAU холостая, ETH выключена
    b = g["BTCUSDT"]
    assert b["grids"] == ["BTC", "B34"] and b["skipped"] == ["B49"]
    assert b["entries"] == [83127.2, 83316.3]
    assert b["tps"] == [83683.3, 85176.0]                         # ближайший тейк КАЖДОЙ сетки
    assert b["lots"] == 3
    assert abs(b["avg"] - (84000 * 0.0012 + 83400 * 0.0012 + 83500 * 0.0024) / 0.0048) < 1e-9


def _fc(sym, issued, a_ms, end_ms, lo, hi, levels=()):
    return {"algo": "dr-3", "kind": "forecast", "sym": sym, "issued_utc": issued, "A_ms": a_ms, "end_ms": end_ms,
            "corridor": [lo, hi], "levels": [dict(x) for x in levels]}


def test_day_corridor_takes_current_window_latest_issue():
    fcs = [_fc("BTCUSDT", "2026-10-20T06:02", MS - 2 * 86_400_000, MS - 86_400_000, 1, 2),       # окно прошло
           _fc("BTCUSDT", "2026-10-21T06:02", MS - 3_600_000, MS + 80_000_000, 80683.9, 84665.5,
               [{"price": 83442.7, "chance": 0.38, "side": "up"}, {"price": 81194.4, "chance": 0.2, "side": "dn"}]),
           _fc("BTCUSDT", "2026-10-21T06:01", MS - 3_600_000, MS + 80_000_000, 1, 2),             # раньше выдан
           _fc("ETHUSDT", "2026-10-22T06:02", MS + 3_600_000, MS + 90_000_000, 1, 2)]             # ещё не начался
    d = tv_levels.day_corridor(NOW, forecasts=fcs)
    assert set(d) == {"BTCUSDT"}
    assert (d["BTCUSDT"]["lo"], d["BTCUSDT"]["hi"]) == (80683.9, 84665.5)
    assert d["BTCUSDT"]["zones"] == [(83442.7, 0.38, "up"), (81194.4, 0.2, "dn")]


def _data(tmp_path):
    corr = {"BTCUSDT": {"issued_utc": "x", "lo": 80683.9, "hi": 84665.5,
                        "zones": [(83442.7, 0.38, "up"), (81194.4, 0.2, "dn")]},
            "ETHUSDT": {"issued_utc": "x", "lo": 2349.4189, "hi": 2533.861, "zones": []}}
    return COLLECT(NOW, grids=_grids(tmp_path), corridor=corr, thr={"BTCUSDT": 74738.75, "ETHUSDT": 2296.62})


def _pine_parse(line: str, base: str) -> dict:
    """Зеркало разбора в bot7_regime_grids.pine (f_part + цикл по токенам): часть своей монеты, первая буква — вид."""
    part = next((p.strip() for p in line.split("|") if p.strip().startswith(base + " ")), "")
    out = {"z": [], "e": [], "t": []}
    for tok in part.split(" "):
        if len(tok) < 2:
            continue
        pre, body = tok[0], tok[1:]
        if pre == "k":
            lo, hi = body.split("-")
            out["k"] = (float(lo), float(hi))
        elif pre == "z":
            out["z"] = [tuple(float(v) for v in z.split(":")) for z in body.split(",")]
        elif pre in "et":
            out[pre] = [float(v) for v in body.split(",")]
        elif pre in "uans":
            out[pre] = float(body)
    return out


def test_tv_line_round_trips_through_pine_parser(tmp_path):
    data = _data(tmp_path)
    line = tv_levels.tv_line(data)
    for tok in line.replace("|", " ").split():                          # цены без разделителей тысяч («83,443»)
        assert re.fullmatch(r"[A-Z]{3}|[uans][\d.]+|k[\d.]+-[\d.]+|z[\d.]+:\d+(,[\d.]+:\d+)*|[et][\d.]+(,[\d.]+)*", tok), tok
    btc = _pine_parse(line, "BTC")
    assert btc["u"] == NOW.timestamp()
    assert btc["k"] == (80683.9, 84665.5)
    assert btc["z"] == [(83442.7, 38.0), (81194.4, 20.0)]
    assert btc["e"] == [83127.2, 83316.3] and btc["t"] == [83683.3, 85176.0]
    assert btc["n"] == 3 and btc["s"] == 74738.8 and abs(btc["a"] - 83600.0) < 0.05
    eth = _pine_parse(line, "ETH")
    assert eth["k"] == (2349.42, 2533.86) and eth["s"] == 2296.62
    assert "e" in eth and eth["e"] == [] and "a" not in eth             # живых сеток ETH нет — входов и средней нет
    assert _pine_parse(line, "XAU") == {"z": [], "e": [], "t": []}      # чужая монета ничего не берёт


def test_card_lines_and_message(tmp_path):
    data = _data(tmp_path)
    cl = tv_levels.card_lines(data)
    assert len(cl) == 1 and cl[0].startswith("📍 BTC: средняя 83,600 (3 лот.)")
    assert "входы 83,127–83,316 (2)" in cl[0] and "ближайшие тейки 83,683–85,176" in cl[0]
    assert "учёт не прочитан: B49" in cl[0]
    msg = tv_levels.tv_message(data)
    assert f"<code>{tv_levels.tv_line(data)}</code>" in msg
    assert "зоны ↑83,443 (38%) ↓81,194 (20%)" in msg
    assert "лонги закроются, если день UTC закроется ниже 74,739" in msg


def _one_grid(entry=98.01, cap=3, lo=97.0, hi=100.0, px=99.5):
    g = {"grids": ["G"], "skipped": [], "entries": [entry], "tps": [99.99], "lots": 2, "avg": 99.5,
         "detail": [{"name": "G", "entry": entry, "lots": [(100.0, 0.01, 101.0), (99.0, 0.01, 99.99)],
                     "step": 1.0, "target": 1.0, "qty": 0.01, "cap": cap}]}
    day = {"issued_utc": "x", "lo": lo, "hi": hi, "zones": [(99.8, 0.4, "up")]}
    return {"now": NOW, "syms": {"BTCUSDT": {"grid": g, "day": day, "thr": 90.0, "px": px}}}


def test_scenarios_arithmetic_capped():
    r = tv_levels.scenarios(_one_grid())["BTCUSDT"]
    assert r["takes"] == 1                                               # тейк 99.99 ≤ верха 100, тейк 101 — нет
    assert abs(r["closed"] - ((99.99 - 99) * 0.01 - 99.99 * 0.01 * tv_levels.FEE_MAKER)) < 1e-12
    assert r["adds"] == 1 and r["capped"] == ["G"]                        # 2 лота + 1 добор = потолок 3
    bag = (97 - 100 + 97 - 99 + 97 - 98.01) * 0.01 - 98.01 * 0.01 * tv_levels.FEE_MAKER
    assert abs(r["bag_lo"] - bag) < 1e-12 and abs(r["notional_lo"] - (100 + 99 + 98.01) * 0.01) < 1e-12


def test_scenarios_adds_step_down_to_corridor_low():
    r = tv_levels.scenarios(_one_grid(cap=50, lo=96.5))["BTCUSDT"]
    assert r["adds"] == 2 and r["capped"] == []                          # 98.01, 97.0299; 96.0596 < низа 96.5


def test_level_lines_sorted_from_price():
    lines = tv_levels.level_lines(_one_grid())
    assert lines[0] == "📍 Уровни BTC · цена 99.50"
    prices = [float(x.split()[1].replace(",", "")) for x in lines[1:]]
    assert prices == sorted(prices, reverse=True)
    assert any("вход сетки" in x and "98.01" in x for x in lines)            # один вход — без перечня
    assert any("порог дневного закрытия" in x and "-9.5%" in x for x in lines)


def test_card_order_scenarios_and_levels_on_top(tmp_path, monkeypatch):
    corr = {"BTCUSDT": {"issued_utc": "x", "lo": 80683.9, "hi": 84665.5, "zones": [(83442.7, 0.38, "up")]}}
    monkeypatch.setattr(regime_watch, "_sma_exit",
                        lambda s: {"BTCUSDT": (83388.0, 74738.75), "ETHUSDT": (2462.24, 2296.62)}[s])
    monkeypatch.setattr(regime_watch, "_regime", lambda s: "ЛОНГ")
    monkeypatch.setattr(regime_watch, "_grid_rows", lambda prices, since: [("BTC 0.6/1.4", 13.7, 4, -0.29, 1)])
    monkeypatch.setattr(regime_watch, "_market_brief", lambda: "\n\n📏 РЫНОК")
    monkeypatch.setattr(tv_levels, "collect",
                        lambda now, thr=None, px=None: COLLECT(now, grids=_grids(tmp_path), corridor=corr, thr=thr, px=px))
    card = regime_watch.build_card(NOW)
    first = card.splitlines()[0]
    assert "BTC 83,388" in first and "ETH 2,462.24" in first and "BTC ЛОНГ, ETH ЛОНГ" in first
    assert card.splitlines()[1].startswith("🛡 Лонги закроются")
    pos = [card.index(m) for m in ("🎯 Сетки на сутки", "📍 Уровни BTC", "📊 Сетки WEEX", "BTC 0.6/1.4: +13.70$",
                                   "📏 РЫНОК")]
    assert pos == sorted(pos)
    assert "в потолке: B34" in card                                      # B34 потолок 4 лота в тесте


def _card_env(tmp_path, monkeypatch, enabled=True):
    monkeypatch.setattr(regime_watch, "DELIVERY_LOG", tmp_path / "d.jsonl")
    monkeypatch.setattr(regime_watch, "CARD_STATE", tmp_path / "card.json")
    monkeypatch.setattr(regime_watch, "_card_push_enabled", lambda: True)
    monkeypatch.setattr(regime_watch, "_tv_line_enabled", lambda: enabled)
    monkeypatch.setattr(regime_watch, "build_card", lambda now: "карточка")
    monkeypatch.setattr(tv_levels, "collect", lambda now, thr=None: _data(tmp_path))
    return datetime(2026, 10, 21, 6, 5, tzinfo=timezone.utc)


def test_tv_line_sent_after_card(tmp_path, monkeypatch):
    now = _card_env(tmp_path, monkeypatch)
    sent = []
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now)
    assert sent[0] == "карточка" and sent[1] == tv_levels.tv_line(_data(tmp_path)) and len(sent) == 2


def test_tv_line_failure_keeps_card_sent(tmp_path, monkeypatch):
    now = _card_env(tmp_path, monkeypatch)
    sent = []

    def send(text):
        if text != "карточка":
            raise RuntimeError("телеграм лёг")
        sent.append(text)
    assert regime_watch.maybe_send_regime_card(send_fn=send, now=now) is True
    assert sent == ["карточка"] and (tmp_path / "card.json").exists()


def test_tv_line_switch_reads_report_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(regime_watch, "ROOT", tmp_path)
    assert regime_watch._tv_line_enabled() is True                       # ключа нет — включено
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "report_delivery.json").write_text('{"regime_card": true, "tv_line": false}')
    assert regime_watch._tv_line_enabled() is False


def test_tv_line_can_be_switched_off(tmp_path, monkeypatch):
    now = _card_env(tmp_path, monkeypatch, enabled=False)
    sent = []
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now)
    assert sent == ["карточка"]
