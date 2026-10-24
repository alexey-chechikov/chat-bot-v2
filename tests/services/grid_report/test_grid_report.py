"""22.10: риск-пинги сеток и сводка (services/grid_report.py) — без сети и без учёта: синтетические строки сеток."""
from __future__ import annotations

from datetime import datetime, timezone

from services import grid_report as gr

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def row(name, sym="BTCUSDT", bag=0.0, blocked="", lots=1, closed=0.0, error=""):
    return {"name": name, "sym": sym, "step": 0.1, "target": 0.34, "sides": ["LONG"], "lots": lots, "qty": 0.001,
            "bag": bag, "closed": closed, "total": closed + bag, "cost": 100.0 * lots, "blocked": blocked,
            "error": error}


def test_cap_ping_once_per_day_per_grid():
    rows = [row("B34", blocked="достигнут потолок позиции"), row("B49")]
    ev, st = gr.risk_events(rows, {}, {}, NOW)
    assert len(ev) == 1 and "B34 на потолке" in ev[0]
    ev2, st2 = gr.risk_events(rows, {}, st, NOW)
    assert ev2 == []                                            # тот же день — молчит
    ev3, _ = gr.risk_events(rows, {}, st2, NOW.replace(day=23))
    assert len(ev3) == 1                                        # новый день — снова


def test_bag_levels_with_hysteresis():
    ev, st = gr.risk_events([row("B34", bag=-120)], {}, {}, NOW)
    assert any("ниже −100" in e for e in ev) and st["bag"] == [100.0]
    ev, st = gr.risk_events([row("B34", bag=-90)], {}, st, NOW)          # выше уровня, но ниже половины — уровень держится
    assert ev == [] and st["bag"] == [100.0]
    ev, st = gr.risk_events([row("B34", bag=-120)], {}, st, NOW)
    assert ev == []                                             # повторно не пингует
    ev, st = gr.risk_events([row("B34", bag=-40)], {}, st, NOW)          # вернулся выше половины — уровень снят
    assert st["bag"] == []
    ev, st = gr.risk_events([row("B34", bag=-300)], {}, st, NOW)         # сразу два уровня — одно сообщение о худшем
    assert len(ev) == 1 and "ниже −250" in ev[0] and st["bag"] == [100.0, 250.0]


def test_unreadable_grid_not_counted_in_bag():
    ev, _ = gr.risk_events([row("B34", bag=-500, error="JSONDecodeError")], {}, {}, NOW)
    assert ev == []


def test_threshold_levels_once_per_day():
    risk = {"BTCUSDT": {"thr": 79000.0, "px": 81000.0, "dist": -2.47, "bag": -400.0, "adds": 3}}
    ev, st = gr.risk_events([], risk, {}, NOW)
    assert len(ev) == 1 and "2.5% от порога выхода 79,000" in ev[0]
    ev, st = gr.risk_events([], risk, st, NOW)
    assert ev == []
    risk["BTCUSDT"]["dist"] = -1.2                              # ближе 1.5% — отдельное событие
    ev, _ = gr.risk_events([], risk, st, NOW)
    assert len(ev) == 1 and "1.2%" in ev[0]


def test_far_from_threshold_silent():
    risk = {"ETHUSDT": {"thr": 2300.0, "px": 2400.0, "dist": -4.17, "bag": -40.0, "adds": 6}}
    ev, _ = gr.risk_events([], risk, {}, NOW)
    assert ev == []


def test_report_text_totals_and_cap_mark():
    rows = [row("BTC", bag=-9.0, closed=55.0, lots=6), row("B34", bag=-58.0, closed=39.0, lots=29,
                                                            blocked="достигнут потолок позиции")]
    data = {"now": NOW, "cap": 15000.0, "syms": {"BTCUSDT": {"grid": None, "day": None, "thr": None, "px": 81906.0}}}
    text = gr.report_text(now=NOW, rows=rows, data=data, eq=(3385.0, -163.0))
    assert "счёт $3,385" in text and "BTC 81,906" in text
    assert "B34 0.1/0.34: лотов 29 ⛔ на потолке" in text
    assert "Всего: мешок −67$ · итог +27$" in text and "занято $3,500 из $15,000" in text


def test_ping_symbols():
    rows = [row("BTC"), row("B34"), row("ETH", sym="ETHUSDT")]
    assert gr.ping_symbols(["⛔ B34 на потолке позиции"], rows) == ["BTCUSDT"]
    assert gr.ping_symbols(["🛑 ETH в 2.0% от порога"], rows) == ["ETHUSDT"]
    assert gr.ping_symbols(["📉 Мешок всех лонг-сеток −120$ — ниже −100$"], rows) == ["BTCUSDT"]


def test_resume_ping_after_long_cap_and_rate_limited():
    """24.10: «снова ставит входы» — после упора ≥1 ч, не чаще раза в 6 ч; короткое качание у потолка молчит."""
    from datetime import timedelta
    capped = [row("B34", blocked="достигнут потолок позиции", lots=31)]
    free = [row("B34", lots=30)]
    _, st = gr.risk_events(capped, {}, {}, NOW)
    ev, st = gr.risk_events(free, {}, st, NOW + timedelta(minutes=20))
    assert ev == []                                              # 20 мин на потолке — не событие
    _, st = gr.risk_events(capped, {}, st, NOW + timedelta(minutes=30))
    ev, st = gr.risk_events(free, {}, st, NOW + timedelta(hours=2))
    assert len(ev) == 1 and ev[0].startswith("✅ B34 снова ставит входы") and "стояла 1.5 ч" in ev[0]
    _, st = gr.risk_events(capped, {}, st, NOW + timedelta(hours=2, minutes=5))
    ev, st = gr.risk_events(free, {}, st, NOW + timedelta(hours=4))
    assert ev == []                                              # второй раз за 6 ч — молчит
    _, st = gr.risk_events(capped, {}, st, NOW + timedelta(hours=7))
    ev, _ = gr.risk_events(free, {}, st, NOW + timedelta(hours=9))
    assert len(ev) == 1                                         # прошло 6 ч — снова можно
