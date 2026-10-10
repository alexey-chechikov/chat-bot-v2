"""Общий потолок счёта: сетка и тренд не открывают вход сверх свободного места."""
import json

from services.weex_grid import engine as eg
from services.weex_grid import portfolio
from services.weex_trend import engine as te
from tests.services.weex_grid.test_weex_grid_engine import Px, bot_open, make


def test_grid_entry_blocked_by_portfolio(tmp_path):
    g, ex = make(tmp_path, Px(), sides=["LONG"], portfolio_free_usd=5.0)   # свободно $5, ордер ~$10
    g.tick()
    assert not bot_open(ex) and "общий потолок" in g.st["LONG"]["blocked"]


def test_grid_entry_allowed_with_room(tmp_path):
    g, ex = make(tmp_path, Px(), sides=["LONG"], portfolio_free_usd=50.0)
    g.tick()
    assert len(bot_open(ex)) == 1


def test_used_counts_live_grid_lots_and_trend(tmp_path):
    gs = tmp_path / "g.json"
    gs.write_text(json.dumps({"LONG": {"lots": [{"qty": "0.01", "entry": 80000.0}]},
                              "SHORT": {"lots": [{"qty": "0.02", "entry": 81000.0}]}}))
    ts = tmp_path / "t.json"
    ts.write_text(json.dumps({"episode": {"qty": "0.5", "entry_px": 2500.0}}))
    assert portfolio.used_usd([gs], [ts]) == 800 + 1620 + 1250


def test_trend_size_cut_by_portfolio(tmp_path):
    clock = {"t": 1_800_000_000.0}
    ex = te.DryTrendExchange(lambda: (2499.99, 2500.01), now_fn=lambda: clock["t"])
    from datetime import datetime, timezone
    sig = tmp_path / "sig.json"
    sig.write_text(json.dumps({"ETHUSDT": {"side": "SHORT", "stop": 2600.0, "entry_px": 2500.0,
                                           "entry_ts": datetime.fromtimestamp(clock["t"], timezone.utc).isoformat()}}))
    conf = {**te.DEFAULT, "enabled": True, "dry_run": True, "poll_sec": 0, "portfolio_free_usd": 250.0}
    for _ in range(2):
        clock["t"] += 60
        te.Trend(ex, conf, state_path=tmp_path / "s.json", journal_path=tmp_path / "j.jsonl", signals_path=sig,
                 now_fn=lambda: clock["t"]).tick()
    assert abs(ex.pos["SHORT"] - 0.1) < 1e-9           # по риску 0.33, но свободно $250 → 0.1 ETH
