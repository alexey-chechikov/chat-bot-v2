"""Alt-momentum: отбор топ/низ по excess + market-neutral доход с комиссией."""
from __future__ import annotations

from services.alt_momentum_shadow.signal import select, portfolio_return


def test_select_top_and_bottom():
    excess = {"A": 8.0, "B": 5.0, "C": 3.0, "D": 1.0, "E": -1.0,
              "F": -3.0, "G": -5.0, "H": -8.0}
    longs, shorts = select(excess, k=2)
    assert longs == ["A", "B"]          # обогнавшие BTC
    assert set(shorts) == {"G", "H"}    # отставшие


def test_select_too_few():
    longs, shorts = select({"A": 1.0, "B": -1.0}, k=4)
    assert longs == [] and shorts == []


def test_portfolio_return_net_of_fee():
    # лонги обогнали +4% в среднем, шорты отстали −3% → gross 7%, fee 2×10bp=0.2%
    pr = portfolio_return([5.0, 3.0], [-2.0, -4.0], fee_bp_leg=10.0)
    assert pr["gross_pct"] == 7.0
    assert pr["net_pct"] == 6.8


def test_portfolio_return_momentum_loss():
    # если обогнавшие развернулись (forward отрицательный) — net в минус (регим-инверсия)
    pr = portfolio_return([-2.0, -1.0], [1.0, 2.0], fee_bp_leg=10.0)
    assert pr["gross_pct"] < 0
    assert pr["net_pct"] < pr["gross_pct"]
