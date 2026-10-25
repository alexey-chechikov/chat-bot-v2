"""Аудит GPT 481385e (24.10): E1/E2 — явный отказ тейка (лимит заявок счёта) не должен давать «здоровый проход» и
не должен сопровождаться новым входом; E3 — неизвестный ответ на заявку тренда не снимает pending."""
from __future__ import annotations

from services.weex_grid import engine as eg

LIVE = eg.LIVE


class MovePx:
    def __init__(self, p: float = 100000.0):
        self.p = p

    def __call__(self):
        return self.p - 0.05, self.p + 0.05


class CapTP(eg.DryExchange):
    """Как WEEX на лимите открытых заявок счёта: явный отказ (success=false) на тейк."""
    reject_tp = False

    def place_limit(self, symbol, side, position_side, qty, price, cid, reduce_only=False, post_only=True):
        if self.reject_tp and reduce_only:
            return {"success": False, "errorCode": "SYNTHETIC_ACCOUNT_ORDER_CAP", "orderId": None}
        return super().place_limit(symbol, side, position_side, qty, price, cid, reduce_only, post_only)


def make(tmp_path, **cfg):
    px = MovePx()
    clock = {"t": 1_800_000_000.0}
    ex = CapTP(px, now_fn=lambda: clock["t"])
    conf = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"], "step_pct": 0.6, "target_pct": 1.4,
            "order_qty": "0.0012", "max_notional_usd": 100000.0, **cfg}

    def now():
        clock["t"] += 10
        return clock["t"]
    g = eg.Grid(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", now_fn=now)
    return g, ex, px


def entries_live(ex):
    return [o for o in ex.orders.values() if not o["reduceOnly"] and o["status"] in LIVE]


def test_tp_reject_is_not_healthy_and_blocks_new_entry(tmp_path):
    g, ex, px = make(tmp_path)
    g.tick()                                                    # вход на шаг ниже
    assert len(entries_live(ex)) == 1
    ok_before = g.st.get("last_tick_ok_ts")
    px.p = 99300.0                                              # вход исполняется
    ex.reject_tp = True                                         # а тейк биржа отклоняет: лимит заявок
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert len(lots) == 1 and lots[0].get("tp_order") is None   # лот без тейка
    assert g.st.get("last_tick_ok_ts") == ok_before             # проход НЕ здоровый
    assert g.st.get("last_tick_error")                          # и это видно
    assert entries_live(ex) == []                               # новый вход при долге по тейкам не ставится
    assert g.st.get("exit_debt", {}).get("LONG") == 1           # долг по выходам считается явно


def test_tp_debt_clears_and_entries_resume(tmp_path):
    g, ex, px = make(tmp_path)
    g.tick()
    px.p = 99300.0
    ex.reject_tp = True
    g.tick()
    ex.reject_tp = False                                        # место освободилось
    g.tick()
    lots = g.st["LONG"]["lots"]
    assert lots[0].get("tp_order") is not None
    assert not g.st.get("exit_debt", {}).get("LONG")
    g.tick()                                                    # долга нет — вход снова ставится
    assert len(entries_live(ex)) == 1


def test_neighbour_exit_debt_drops_own_entry(tmp_path):
    """E1: у соседней сетки счёта лот без тейка — эта сетка снимает свой вход и новых не ставит."""
    g, ex, px = make(tmp_path)
    g.tick()
    assert len(entries_live(ex)) == 1
    g.cfg["account_exit_debt"] = ["B34"]
    g.tick()
    assert entries_live(ex) == [] and "долг по тейкам у B34" in g.st["LONG"]["blocked"]


def test_order_budget_gates_new_entry(tmp_path):
    """E1: бюджет заявок счёта — новый вход только при месте; подсчёт не прочитан — входов нет."""
    g, ex, px = make(tmp_path, order_budget=5, other_open_orders=5)
    g.tick()
    assert entries_live(ex) == [] and "бюджет заявок счёта: 5 из 5" in g.st["LONG"]["blocked"]
    g.cfg["other_open_orders"] = None
    g.tick()
    assert entries_live(ex) == [] and "не прочитан" in g.st["LONG"]["blocked"]
    g.cfg["other_open_orders"] = 0
    g.tick()
    assert len(entries_live(ex)) == 1
    g.cfg["other_open_orders"] = 4                              # вход уже стоит: 1 + 4 = 5 — новый не нужен, стоящий остаётся
    g.tick()
    assert len(entries_live(ex)) == 1


def test_runner_passes_budget_and_neighbour_debts(tmp_path, monkeypatch):
    """E1: цикл передаёт живой сетке бюджет заявок, заявки ДРУГИХ символов счёта и долги ДРУГИХ сеток."""
    from services.weex_grid import loop
    monkeypatch.setattr(loop, "AUDIT_FILE", tmp_path / "audit.json")
    seen = {}

    class FakeGrid:
        def __init__(self, client, cfg, **kw):
            seen.update(cfg)

        def tick(self):
            pass
    live = {**eg.DEFAULT, "symbol": "BTCUSDT", "dry_run": False, "enabled": True}
    monkeypatch.setattr(loop, "grid_config", lambda name: dict(live))
    monkeypatch.setattr(loop, "run_files", lambda name, dry: (tmp_path / f"{name}.json", tmp_path / f"{name}.jsonl"))
    monkeypatch.setattr(loop.eg, "Grid", FakeGrid)
    r = loop.Runner()
    monkeypatch.setattr(r, "_client", lambda: object())
    r.tick_one("B34", None, acct={"BTCUSDT": 150, "ETHUSDT": 20}, debts=["B49", "B34"])
    assert seen["order_budget"] == loop.ORDER_BUDGET and seen["other_open_orders"] == 20
    assert seen["account_exit_debt"] == ["B49"]
    seen.clear()
    r.tick_one("B34", None, acct=None, debts=[])
    assert seen["other_open_orders"] is None                   # подсчёт не прочитан — сетка входов не ставит
