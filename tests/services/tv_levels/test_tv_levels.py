"""Уровни для TradingView (21.10): сборка из учёта сеток и прогноза дня, строка для индикатора, отправка после карточки,
сценарии сеток на краях коридора. Разбор GPT 8252cc0 (F1–F4): сценарий доборов сверен с самим движком."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services import regime_watch, tv_levels
from services.weex_grid import engine as eg

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
COLLECT = tv_levels.collect                                     # до подмены в тестах отправки
GRID = {"step_pct": 0.6, "target_pct": 1.4, "order_qty": "0.0012", "max_lots_per_side": 50,
        "max_notional_usd": 12000.0, "price_tick": 0.1, "stress_budget_frac": 0.0}


def _lot(entry, qty, tp, parent=None):
    return {"entry": entry, "qty": qty, "tp": tp, "tp_order": {}, "t": 0.0, "parent": parent or f"o{entry}"}


def _grids(tmp_path: Path, extra_states=None, extra_cfgs=None, blocks=None):
    cfgs = {"BTC": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID},
            "B34": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID, "step_pct": 0.1,
                    "max_lots_per_side": 4},
            "XAU": {"symbol": "XAUUSDT", "enabled": True, "dry_run": True, **GRID},     # холостая — не показывать
            "B49": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID},    # учёт битый
            "ETH": {"symbol": "ETHUSDT", "enabled": False, "dry_run": False, **GRID},   # выключена
            **(extra_cfgs or {})}
    states = {
        "BTC": {"LONG": {"entry": {"id": "eb", "price": 83127.2}, "lots": [_lot(84000.0, "0.0012", 85176.0)]},
                "last_tick_ok_ts": NOW.timestamp() - 20},
        "B34": {"LONG": {"entry": {"id": "e3", "price": 83316.3}, "lots": [_lot(83400.0, "0.0012", 83683.3),
                                                                         _lot(83500.0, "0.0024", 83784.0)]},
                "last_tick_ok_ts": NOW.timestamp() - 45},
        "XAU": {"LONG": {"entry": {"price": 4000.0}, "lots": [_lot(4100.0, "0.023", 4112.3)]}},
        **(extra_states or {})}
    for name, st in states.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "B49.json").write_text("{битый", encoding="utf-8")
    return tv_levels.grid_levels(names=list(cfgs), peek=cfgs.get, state_path=lambda n: tmp_path / f"{n}.json",
                                 blocks=blocks or {})


def test_grid_levels_live_only_weighted_avg_and_nearest_tp(tmp_path):
    g = _grids(tmp_path)
    assert set(g) == {"BTCUSDT"}                                  # XAU холостая, ETH выключена
    b = g["BTCUSDT"]
    assert b["grids"] == ["BTC", "B34"] and [n for n, _ in b["skipped"]] == ["B49"] and b["expected"] == 3
    assert b["skipped"][0][1] == "JSONDecodeError"
    assert b["entries"] == [83127.2, 83316.3]
    assert b["tps"] == [83683.3, 85176.0]                         # ближайший тейк КАЖДОЙ сетки
    assert b["lots"] == 3
    assert abs(b["avg"] - (84000 * 0.0012 + 83400 * 0.0012 + 83500 * 0.0024) / 0.0048) < 1e-9


def test_f4_bad_number_skips_only_that_grid(tmp_path):
    """F4: синтаксически верный JSON с qty 'bad' — сетка пропущена с причиной, остальные видны, итог не испорчен."""
    bad = {"LONG": {"entry": {"id": "e9", "price": 83000.0}, "lots": [_lot(83100.0, "bad", 84000.0)]}}
    g = _grids(tmp_path, extra_states={"B89": bad},
               extra_cfgs={"B89": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID}})["BTCUSDT"]
    assert g["grids"] == ["BTC", "B34"] and ("B89", "ValueError") in g["skipped"] and g["expected"] == 4
    assert g["lots"] == 3 and 83000.0 not in g["entries"]          # куски битой сетки в итог не попали


@pytest.mark.parametrize("st, why", [
    ({"LONG": {"entry": None, "lots": [_lot(83100.0, "nan", 84000.0)]}}, "ValueError"),       # NaN объём
    ({"LONG": {"entry": None, "lots": [_lot(float("inf"), "0.0012", 84000.0)]}}, "ValueError"),  # ∞ цена
    ({"LONG": {"entry": None, "lots": [_lot(83100.0, "0.0012", "Infinity")]}}, "ValueError"),     # ∞ тейк
    ({"LONG": {"entry": None, "lots": [_lot(83100.0, True, 84000.0)]}}, "TypeError"),            # bool — не число
    ({"LONG": {"entry": {"id": "e", "price": 83000.0, "qty": "0.0012", "filled": "0.002"}, "lots": []}},
     "ValueError"),                                                                              # исполнено > объёма
    ({"LONG": {"entry": {"id": "e", "price": "nan"}, "lots": []}}, "ValueError"),                 # NaN цена входа
    ({}, "TypeError"),                                                                           # нет LONG
    ({"LONG": []}, "TypeError"),                                                                 # LONG не объект
    ({"LONG": {"lots": {}}}, "TypeError"),                                                       # lots не список
    ({"LONG": {"entry": None}}, "TypeError"),                                                    # нет lots
    ({"LONG": {"entry": None, "lots": ["x"]}}, "TypeError"),                                     # лот не объект
    ([], "TypeError"),                                                                           # учёт не объект
])
def test_f4_nonfinite_and_bad_structures_skip_grid(tmp_path, st, why):
    """Разбор GPT к a25c763: NaN/∞ проходили float() и срывали сценарий и /tv; неверные пустые структуры принимались
    за корректный учёт. Теперь — пропуск сетки с причиной, остальные видны, сценарий и строка считаются."""
    g = _grids(tmp_path, extra_states={"B89": st},
               extra_cfgs={"B89": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID}})
    b = g["BTCUSDT"]
    assert ("B89", why) in b["skipped"] and b["grids"] == ["BTC", "B34"] and b["lots"] == 3
    data = COLLECT(NOW, grids=g, corridor=CORR, thr={"BTCUSDT": 74738.75}, px={"BTCUSDT": 83388.0}, cap=None)
    line = tv_levels.tv_line(data)
    assert "nan" not in line.lower() and "inf" not in line.lower() and " g2/4 " in line
    r = tv_levels.scenarios(data)["BTCUSDT"]
    assert all(math.isfinite(v) for v in (r["closed"], r["bag_lo"], r["notional_lo"]))


def test_f4_bad_forecast_numbers_dropped():
    fcs = [_fc("BTCUSDT", "2026-10-21T06:02", MS - 3_600_000, MS + 80_000_000, float("nan"), 84665.5),
           _fc("ETHUSDT", "2026-10-21T06:02", MS - 3_600_000, MS + 80_000_000, 2500.0, 2400.0)]   # низ ≥ верха
    assert tv_levels.day_corridor(NOW, forecasts=fcs) == {}


def test_f4_no_grid_read_is_reported_not_zero(tmp_path):
    cfgs = {"B49": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID}}
    (tmp_path / "B49.json").write_text("{битый", encoding="utf-8")
    g = tv_levels.grid_levels(names=["B49"], peek=cfgs.get, state_path=lambda n: tmp_path / f"{n}.json", blocks={})
    data = COLLECT(NOW, grids=g, corridor={}, thr={"BTCUSDT": 74738.75}, px={"BTCUSDT": 83388.0}, cap=None)
    lines = tv_levels.level_lines(data)
    assert any("учёт прочитан 0 из 1" in x and "B49 (JSONDecodeError)" in x for x in lines)
    assert " g0/1 " in tv_levels.tv_line(data) and " xB49" in tv_levels.tv_line(data)
    assert " n0" not in tv_levels.tv_line(data)                    # нечитаемое не подменено нулём лотов


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
    assert d["BTCUSDT"]["end"] == (MS + 80_000_000) / 1000
    assert d["BTCUSDT"]["zones"] == [(83442.7, 0.38, "up"), (81194.4, 0.2, "dn")]


CORR = {"BTCUSDT": {"issued_utc": "x", "lo": 80683.9, "hi": 84665.5, "end": NOW.timestamp() + 70_000,
                    "zones": [(83442.7, 0.38, "up"), (81194.4, 0.2, "dn")]},
        "ETHUSDT": {"issued_utc": "x", "lo": 2349.4189, "hi": 2533.861, "end": NOW.timestamp() + 70_000, "zones": []}}


def _data(tmp_path):
    return COLLECT(NOW, grids=_grids(tmp_path), corridor=CORR, thr={"BTCUSDT": 74738.75, "ETHUSDT": 2296.62},
                   cap=None)


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
        elif pre == "g":
            out["g"] = tuple(int(v) for v in body.split("/"))
        elif pre == "x":
            out["x"] = body.split(",")
        elif pre in "uanswv":
            out[pre] = float(body)
    return out


def test_tv_line_round_trips_through_pine_parser(tmp_path):
    data = _data(tmp_path)
    line = tv_levels.tv_line(data)
    for tok in line.replace("|", " ").split():                          # цены без разделителей тысяч («83,443»)
        assert re.fullmatch(r"[A-Z]{3}|[uanswv][\d.]+|g\d+/\d+|x[A-Z0-9,]+|k[\d.]+-[\d.]+|z[\d.]+:\d+(,[\d.]+:\d+)*"
                            r"|[et][\d.]+(,[\d.]+)*", tok), tok
    btc = _pine_parse(line, "BTC")
    assert btc["u"] == NOW.timestamp() and btc["g"] == (2, 3) and btc["x"] == ["B49"]
    assert btc["v"] == NOW.timestamp() - 45                              # старейшая сверка прочитанных сеток
    assert btc["k"] == (80683.9, 84665.5) and btc["w"] == int(NOW.timestamp() + 70_000)
    assert btc["z"] == [(83442.7, 38.0), (81194.4, 20.0)]
    assert btc["e"] == [83127.2, 83316.3] and btc["t"] == [83683.3, 85176.0]
    assert btc["n"] == 3 and btc["s"] == 74738.8 and abs(btc["a"] - 83600.0) < 0.05
    eth = _pine_parse(line, "ETH")
    assert eth["k"] == (2349.42, 2533.86) and eth["s"] == 2296.62
    assert eth["e"] == [] and "a" not in eth and "g" not in eth          # живых сеток ETH нет — нет и полноты
    assert _pine_parse(line, "XAU") == {"z": [], "e": [], "t": []}      # чужая монета ничего не берёт


def test_card_lines_and_message(tmp_path):
    data = _data(tmp_path)
    cl = tv_levels.card_lines(data)
    assert len(cl) == 1 and cl[0].startswith("📍 BTC: средняя открытых лотов, без комиссий 83,600 (3 лот.)")
    assert "входы 83,127–83,316 (2)" in cl[0] and "ближайшие тейки 83,683–85,176" in cl[0]
    assert "учёт прочитан 2 из 3 сеток — не прочитаны: B49 (JSONDecodeError)" in cl[0]
    msg = tv_levels.tv_message(data)
    assert f"<code>{tv_levels.tv_line(data)}</code>" in msg
    assert "зоны CG, касание по ATR ↑83,443 (38%) ↓81,194 (20%)" in msg
    assert "лонги закроются, если день UTC закроется ниже 74,739" in msg
    assert "безубыток" not in msg                                     # средняя без комиссий — не безубыток


def _gd(entry=None, lots=(), cap=3, max_notional=1e9, tick=0.01, step=1.0, qty=0.01, **kw):
    return {"name": "G", "entry": entry, "lots": [dict(x) for x in lots], "step": step, "target": 1.0, "qty": qty,
            "cap": cap, "max_notional": max_notional, "tick": tick, "stress": 0.0, "halted": False, "blocked": "", **kw}


def _L(entry, qty, tp, parent):
    return {"entry": entry, "qty": qty, "tp": tp, "parent": parent}


def _one(gd, lo=97.0, hi=100.0, px=99.5):
    g = {"grids": ["G"], "skipped": [], "expected": 1, "detail": [gd], "entries": [], "tps": [], "lots": 0, "avg": None}
    return {"now": NOW, "cap": None,
            "syms": {"BTCUSDT": {"grid": g, "day": {"issued_utc": "x", "lo": lo, "hi": hi, "zones": []},
                                 "thr": 90.0, "px": px}}}


TWO = (_L(100.0, 0.01, 101.0, "a"), _L(99.0, 0.01, 99.99, "b"))


def test_scenarios_arithmetic_capped():
    r = tv_levels.scenarios(_one(_gd({"id": "e", "price": 98.01, "qty": 0.01, "filled": 0.0}, TWO)))["BTCUSDT"]
    assert r["takes"] == 1                                               # тейк 99.99 ≤ верха 100, тейк 101 — нет
    assert abs(r["closed"] - ((99.99 - 99) * 0.01 - 99.99 * 0.01 * tv_levels.FEE_MAKER)) < 1e-12
    assert r["adds"] == 1 and r["stops"] == {"G": "потолок ордеров"}      # 2 слота + вход = потолок 3
    bag = (97 - 100 + 97 - 99 + 97 - 98.01) * 0.01 - 98.01 * 0.01 * tv_levels.FEE_MAKER
    assert abs(r["bag_lo"] - bag) < 1e-12 and abs(r["notional_lo"] - (100 + 99 + 98.01) * 0.01) < 1e-12


def test_scenarios_adds_step_down_to_corridor_low():
    r = tv_levels.scenarios(_one(_gd({"id": "e", "price": 98.01, "qty": 0.01, "filled": 0.0}, TWO, cap=50),
                                 lo=96.5))["BTCUSDT"]
    assert r["adds"] == 2 and r["stops"] == {}                           # 98.01, 97.02; 96.04 < низа 96.5


def test_f1_notional_cap_stops_adds_before_slots():
    """F1: потолок позиции движка — max(себестоимость, стоимость) + вход ≤ max_notional_usd."""
    gd = _gd({"id": "e", "price": 98.01, "qty": 0.01, "filled": 0.0}, TWO, cap=50, max_notional=3.0)
    adds, _, why = tv_levels._sim_down(gd, 90.0, 99.5)
    assert len(adds) == 1 and why == "потолок позиции"                  # 1.99 + 0.98 ≤ 3; + 0.97 > 3


def test_f2_partial_fills_share_one_slot_and_remainder_not_doubled():
    """F2: три куска частичного исполнения одного входа — один слот; остаток входа добирается без удвоения объёма."""
    parts = [_L(99.0, 0.003, 99.99, "e1") for _ in range(3)]
    gd = _gd({"id": "e1", "price": 99.0, "qty": 0.01, "filled": 0.009}, parts, cap=3)
    adds, pos, why = tv_levels._sim_down(gd, 96.0, 99.5)
    assert adds[0] == (99.0, pytest.approx(0.001)) and why == "потолок ордеров"
    assert [p for p, _ in adds] == [99.0, 98.01, 97.02]                   # остаток + 2 новых слота (потолок 3)
    assert sum(q for _, q in pos) == pytest.approx(0.009 + 0.001 + 0.02)


def test_f3_entry_price_rounded_down_to_tick():
    """F3: 98.01 × 0.99 = 97.0299 → движок ставит 97.02 — до края 97.025 цена не дошла: один добор, не два."""
    adds, _, _ = tv_levels._sim_down(_gd({"id": "e", "price": 98.01, "qty": 0.01, "filled": 0.0}, cap=50), 97.025, 99.0)
    assert [p for p, _ in adds] == [98.01]


def test_blocked_or_halted_grid_adds_nothing():
    for kw, why in (({"halted": True}, "сетка остановлена"), ({"blocked": "нехватка"}, "сверка позиции: входы стоят")):
        adds, _, w = tv_levels._sim_down(_gd({"id": "e", "price": 98.0, "qty": 0.01, "filled": 0.0}, **kw), 90.0, 99.0)
        assert adds == [] and w == why


class _Px:
    def __init__(self, mid):
        self.mid = mid

    def __call__(self):
        return self.mid - 0.05, self.mid + 0.05


@pytest.mark.parametrize("over", [{"max_notional_usd": 300.0, "max_lots_per_side": 50},
                                  {"max_notional_usd": 10000.0, "max_lots_per_side": 2},
                                  {"max_notional_usd": 10000.0, "max_lots_per_side": 50}])
def test_scenario_matches_engine_on_falling_price(tmp_path, over):
    """Приёмка GPT: на одном снимке движок (имитатор биржи, плавное падение) и сценарий допускают одинаковые доборы
    по тем же ценам — потолок позиции, потолок ордеров и округление тика."""
    conf = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "step_pct": 1.0, "target_pct": 1.0,
            "order_qty": "0.001", "daily_loss_stop_usd": 0.0, "stress_budget_frac": 0.0, **over}
    px, clock = _Px(100_000.0), {"t": 1_800_000_000.0}
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])

    def now():
        clock["t"] += 10
        return clock["t"]

    g = eg.Grid(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=now)
    g.tick()                                                            # первый вход стоит
    snap = json.loads(json.dumps(g.st))
    lo = 95_500.0
    while px.mid > lo:
        px.mid = max(lo, px.mid - 20.0)
        g.tick()
    g.tick()
    engine_fills = sorted((l["entry"] for l in g.st["LONG"]["lots"]), reverse=True)
    gd = tv_levels._parse_grid("G", {**conf, "symbol": "BTCUSDT"}, snap, {})
    adds, _, _ = tv_levels._sim_down(gd, lo, 100_000.0)
    assert [p for p, _ in adds] == pytest.approx(engine_fills) and len(engine_fills) >= 2


def test_level_lines_sorted_from_price():
    gd = _gd({"id": "e", "price": 98.01, "qty": 0.01, "filled": 0.0}, TWO)
    data = _one(gd)
    g = data["syms"]["BTCUSDT"]["grid"]
    g.update(entries=[98.01], tps=[99.99, 101.0], lots=2, avg=99.5)
    lines = tv_levels.level_lines(data)
    assert lines[0] == "📍 Уровни BTC · цена 99.50"
    prices = [float(x.split()[1].replace(",", "")) for x in lines[1:]]
    assert prices == sorted(prices, reverse=True)
    assert any("вход сетки" in x and "98.01" in x for x in lines)            # один вход — без перечня
    assert any("порог дневного закрытия" in x and "-9.5%" in x for x in lines)
    assert any("средняя открытых лотов, без комиссий (2)" in x for x in lines)


def test_card_order_scenarios_and_levels_on_top(tmp_path, monkeypatch):
    monkeypatch.setattr(regime_watch, "_sma_exit",
                        lambda s: {"BTCUSDT": (83388.0, 74738.75), "ETHUSDT": (2462.24, 2296.62)}[s])
    monkeypatch.setattr(regime_watch, "_regime", lambda s: "ЛОНГ")
    monkeypatch.setattr(regime_watch, "_grid_rows", lambda prices, since: [("BTC 0.6/1.4", 13.7, 4, -0.29, 1)])
    monkeypatch.setattr(regime_watch, "_market_brief", lambda: "\n\n📏 РЫНОК")
    monkeypatch.setattr(regime_watch, "_funding_24h", lambda now: -0.4)             # 25.10: без сети WEEX
    monkeypatch.setattr(regime_watch, "BAG_SNAPSHOT", tmp_path / "bags.json")      # и не в живой state/
    monkeypatch.setattr(tv_levels, "collect", lambda now, thr=None, px=None: COLLECT(
        now, grids=_grids(tmp_path), corridor=CORR, thr=thr, px=px, cap=None))
    card = regime_watch.build_card(NOW)
    first = card.splitlines()[0]
    assert "BTC 83,388" in first and "ETH 2,462.24" in first and "BTC ЛОНГ, ETH ЛОНГ" in first
    assert card.splitlines()[1].startswith("🛡 Лонги закроются")
    pos = [card.index(m) for m in ("🎯 Сетки на сутки", "📍 Уровни BTC", "📊 Сетки WEEX", "BTC 0.6/1.4: +13.70$",
                                   "📏 РЫНОК")]
    assert pos == sorted(pos)
    assert "B34 — потолок ордеров" in card                               # B34 потолок 4 слота в тесте
    assert "Не гарантированная граница потерь" in card and "худший случай" not in card


def test_card_day_result_includes_bag_change_and_funding(tmp_path, monkeypatch):
    """25.10 (перепроверка GPT): закрытые циклы — не прибыль счёта. Итог суток = закрыто + изменение мешка + фандинг;
    без вчерашнего снимка изменение мешка не выдумывается (не 0)."""
    import json as _json
    from datetime import timedelta
    monkeypatch.setattr(regime_watch, "_sma_exit", lambda s: None)
    monkeypatch.setattr(regime_watch, "_regime", lambda s: "ЛОНГ")
    monkeypatch.setattr(regime_watch, "_market_brief", lambda: "")
    monkeypatch.setattr(regime_watch, "_funding_24h", lambda now: -0.4)
    monkeypatch.setattr(regime_watch, "BAG_SNAPSHOT", tmp_path / "bags.json")
    monkeypatch.setattr(tv_levels, "collect", lambda now, thr=None, px=None: COLLECT(
        now, grids={}, corridor={}, thr={}, px={}, cap=None))
    monkeypatch.setattr(regime_watch, "_grid_rows", lambda prices, since: [("B34 0.1/0.34", 12.0, 30, -150.0, 40)])
    first = regime_watch.build_card(NOW)
    total = [ln for ln in first.splitlines() if ln.startswith("Итого")][0]
    assert "нет вчерашнего снимка" in total and "итог суток" not in total
    snap = _json.loads((tmp_path / "bags.json").read_text())
    assert snap["bags"] == {"B34 0.1/0.34": -150.0}
    monkeypatch.setattr(regime_watch, "_grid_rows", lambda prices, since: [("B34 0.1/0.34", 9.0, 25, -170.0, 44)])
    nxt = regime_watch.build_card(NOW + timedelta(hours=24))
    assert "мешок -170.00$ (44 лот.) · -20.00$ за сутки → итог -11.00$" in nxt
    assert "закрыто +9.00$ · мешок за сутки -20.00$ · фандинг -0.40$" in nxt and "итог суток -11.40$" in nxt


def test_gross_cap_note_when_total_exceeds():
    data = _one(_gd({"id": "e", "price": 98.01, "qty": 0.01, "filled": 0.0}, TWO, cap=50), lo=96.5)
    data["cap"] = 2.0
    r = tv_levels.scenarios(data)["BTCUSDT"]
    assert any("общий потолок $2" in n for n in r["notes"])


def _card_env(tmp_path, monkeypatch, enabled=True):
    monkeypatch.setattr(regime_watch, "DELIVERY_LOG", tmp_path / "d.jsonl")
    monkeypatch.setattr(regime_watch, "CARD_STATE", tmp_path / "card.json")
    monkeypatch.setattr(regime_watch, "_card_push_enabled", lambda: True)
    monkeypatch.setattr(regime_watch, "_tv_line_enabled", lambda: enabled)
    monkeypatch.setattr(regime_watch, "build_card", lambda now: "карточка")
    monkeypatch.setattr(regime_watch, "_send_story", lambda send_fn, now, day: None)   # 22.10: без сети
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


def test_day_maps_sent_after_card_and_failure_keeps_card(tmp_path, monkeypatch):
    """22.10: карты BTC и ETH картинками после карточки и строки TV; сбой карты не отменяет карточку."""
    from services import grid_report
    now = _card_env(tmp_path, monkeypatch)
    monkeypatch.setattr(grid_report, "enabled", lambda key: True)
    monkeypatch.setattr(grid_report, "render_map", lambda sym, data=None, now=None: sym.encode())
    from services.coinglass_web import compare_view            # 28.10: метрики вместе — после карт, без сети
    monkeypatch.setattr(compare_view, "deliver", lambda photo_fn, doc_fn=None, **k: [
        photo_fn(f"lens {s}".encode(), "cap") for s in ("BTCUSDT", "ETHUSDT")])
    monkeypatch.setattr(regime_watch, "_doc_sender", lambda: None)
    sent, photos = [], []
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now, photo_fn=lambda png, cap: photos.append(png))
    assert sent[0] == "карточка" and photos == [b"BTCUSDT", b"ETHUSDT", b"lens BTCUSDT", b"lens ETHUSDT"]
    (tmp_path / "card.json").unlink()
    def boom(sym, data=None, now=None):
        raise RuntimeError("matplotlib лёг")
    monkeypatch.setattr(grid_report, "render_map", boom)
    sent.clear()
    assert regime_watch.maybe_send_regime_card(send_fn=sent.append, now=now, photo_fn=lambda png, cap: None) is True
    assert sent[0] == "карточка" and (tmp_path / "card.json").exists()


def test_a5_stale_or_unknown_sync_is_marked(tmp_path):
    """25.10 (аудит GPT 481385e A5): u — время сборки строки, а не сверки с биржей. Сверка старше 5 мин или неизвестна
    (у сетки нет last_tick_ok_ts) — предупреждение в тексте и v0 в строке (индикатор красит уровни серым)."""
    fresh = _data(tmp_path)
    assert not any("сверка с биржей" in x for x in tv_levels.level_lines(fresh))
    old = {"LONG": {"entry": {"id": "e8", "price": 83000.0}, "lots": []}, "last_tick_ok_ts": NOW.timestamp() - 1800}
    cfg89 = {"B89": {"symbol": "BTCUSDT", "enabled": True, "dry_run": False, **GRID}}
    g = _grids(tmp_path, extra_states={"B89": old}, extra_cfgs=cfg89)
    data = COLLECT(NOW, grids=g, corridor=CORR, thr={"BTCUSDT": 74738.75}, px={"BTCUSDT": 83388.0}, cap=None)
    assert any("сверка с биржей 30 мин назад" in x for x in tv_levels.level_lines(data))
    assert _pine_parse(tv_levels.tv_line(data), "BTC")["v"] == NOW.timestamp() - 1800
    unknown = {"LONG": {"entry": {"id": "e8", "price": 83000.0}, "lots": []}}
    g = _grids(tmp_path, extra_states={"B89": unknown}, extra_cfgs=cfg89)
    data = COLLECT(NOW, grids=g, corridor=CORR, thr={"BTCUSDT": 74738.75}, px={"BTCUSDT": 83388.0}, cap=None)
    assert any("время сверки с биржей неизвестно" in x for x in tv_levels.card_lines(data))
    assert " v0" in tv_levels.tv_line(data)
