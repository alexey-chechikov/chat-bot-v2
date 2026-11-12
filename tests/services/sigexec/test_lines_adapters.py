"""Линии без заглядывания, адаптеры бирж на поддельном HTTP (форма запросов, разбор ответов, отказ/неизвестно),
бумажный запуск, прогон истории (если на машине есть frozen-минутки)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from services.sigexec import lines, strategy
from services.sigexec.exchange.base import Incomplete, OrderReq, Rejected, Unknown
from services.sigexec.exchange.bybit import BybitExchange
from services.sigexec.exchange.okx import OkxExchange


def synth(n=24000, seed=7):
    rng = np.random.default_rng(seed)
    t = (np.arange(n) + 1) * 3600 + 1_600_000_000 // 3600 * 3600
    c = 30000 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n))
    return t, o, h, l, c


def test_lines_no_lookahead():
    t, o, h, l, c = synth()
    a, lay = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    n = 17003                                            # обрезка посреди свечи 4ч
    b, lb = lines.build(t[:n], o[:n], h[:n], l[:n], c[:n], i0_t=int(t[0]))
    for k in ("j", "B4p", "atr4", "f_close", "f_G", "f_Y", "f_R", "f_B", "f_run_G", "f_run_Y", "f_run_R"):
        np.testing.assert_array_equal(np.asarray(a[k])[:n], np.asarray(b[k]), err_msg=k)
    np.testing.assert_array_equal(lay[1][:n], lb[1])
    np.testing.assert_array_equal(np.isfinite(lay[0][:n]), np.isfinite(lb[0]))


def test_lines_reject_bad_hours():
    t, o, h, l, c = synth(500)
    with pytest.raises(ValueError):
        lines.build(t[::-1], o, h, l, c)
    c2 = c.copy()
    c2[10] = np.nan
    with pytest.raises(ValueError):
        lines.build(t, o, h, l, c2)


def test_strategy_evaluate_shapes():
    t, o, h, l, c = synth()
    r = strategy.evaluate(t, o, h, l, c)
    assert r["t"] == int(t[-1]) and set(r["desired"]) == {"system", "432"}
    for d in r["desired"].values():
        assert d is None or (d.entry_t <= r["t"] and d.main_frac > 0)


# ---------------------------------------------------------------- Bybit
class FakeHttp:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def __call__(self, method, url, headers, data):
        self.sent.append((method, url, headers, json.loads(data) if data else None))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_bybit_post_only_limit_body_and_ok():
    http = FakeHttp([{"retCode": 0, "result": {"list": [{"priceFilter": {"tickSize": "0.1"}, "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}}]}},
                     {"retCode": 0, "result": {"orderId": "abc"}}])
    ex = BybitExchange("k", "s", http=http)
    info = ex.place(OrderReq("b7xse1", "BTCUSDT", "BUY", "LONG", "LIMIT", 0.0123, price=70000.05, post_only=True))
    body = http.sent[1][3]
    assert body["timeInForce"] == "PostOnly" and body["positionIdx"] == 1 and body["qty"] == "0.012" and body["orderLinkId"] == "b7xse1"
    assert body["price"] == "70000.0" and info.status == "NEW" and info.oid == "abc"
    assert "X-BAPI-SIGN" in http.sent[1][2]


def test_bybit_reject_vs_unknown():
    inst = {"retCode": 0, "result": {"list": [{"priceFilter": {"tickSize": "0.1"}, "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}}]}}
    ex = BybitExchange("k", "s", http=FakeHttp([inst, {"retCode": 110007, "retMsg": "insufficient"}, {"retCode": 10016, "retMsg": "server"}, TimeoutError()]))
    req = OrderReq("c1", "BTCUSDT", "SELL", "SHORT", "MARKET", 0.01)
    with pytest.raises(Rejected):
        ex.place(req)
    with pytest.raises(Unknown):
        ex.place(req)
    with pytest.raises(Unknown):
        ex.place(req)


def test_bybit_stop_direction_and_lookup():
    inst = {"retCode": 0, "result": {"list": [{"priceFilter": {"tickSize": "0.1"}, "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}}]}}
    http = FakeHttp([inst, {"retCode": 0, "result": {"orderId": "s1"}},
                     {"retCode": 0, "result": {"list": []}},
                     {"retCode": 0, "result": {"list": [{"orderLinkId": "k1", "orderStatus": "Filled", "cumExecQty": "0.01", "avgPrice": "61600", "cumExecFee": "0.33", "orderId": "s1"}]}},
                     {"retCode": 0, "result": {"list": []}}, {"retCode": 0, "result": {"list": []}}])
    ex = BybitExchange("k", "s", http=http)
    ex.place(OrderReq("k1", "BTCUSDT", "SELL", "LONG", "STOP", 0.01, trigger=61600.0, reduce_only=True))
    assert http.sent[1][3]["triggerDirection"] == 2 and http.sent[1][3]["reduceOnly"] is True
    info = ex.order("BTCUSDT", "k1", "STOP")
    assert info.status == "FILLED" and info.filled == pytest.approx(0.01) and info.fee == pytest.approx(0.33)
    assert ex.order("BTCUSDT", "zz", "LIMIT") is None


# ---------------------------------------------------------------- OKX
OKX_INST = {"code": "0", "data": [{"tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01", "ctVal": "0.01"}]}


def test_okx_contracts_and_algo_stop():
    http = FakeHttp([OKX_INST, {"code": "0", "data": [{"sCode": "0", "algoId": "A1"}]}])
    ex = OkxExchange("k", "s", "p", http=http)
    ex.place(OrderReq("b7xsk1", "BTCUSDT", "SELL", "LONG", "STOP", 0.0123, trigger=61600.0, reduce_only=True))
    m, url, h, body = http.sent[1]
    assert url.endswith("/api/v5/trade/order-algo") and body["sz"] == "1.23" and body["ordType"] == "trigger" and body["orderPx"] == "-1"
    assert body["posSide"] == "long" and body["algoClOrdId"] == "b7xsk1" and "OK-ACCESS-SIGN" in h


def test_okx_order_not_found_and_fill():
    http = FakeHttp([OKX_INST, {"code": "51603", "msg": "Order does not exist", "data": []},
                     {"code": "0", "data": [{"clOrdId": "c2", "state": "filled", "accFillSz": "2", "avgPx": "70000", "fee": "-0.0224", "ordId": "9"}]},
                     {"code": "50013", "msg": "busy", "data": []}])
    ex = OkxExchange("k", "s", "p", http=http)
    assert ex.order("BTCUSDT", "c1", "LIMIT") is None
    info = ex.order("BTCUSDT", "c2", "LIMIT")
    assert info.filled == pytest.approx(0.02) and info.fee == pytest.approx(0.0224) and info.status == "FILLED"
    with pytest.raises(Incomplete):
        ex.order("BTCUSDT", "c3", "LIMIT")


def test_okx_post_only_reject():
    http = FakeHttp([OKX_INST, {"code": "1", "msg": "failed", "data": [{"sCode": "51026", "sMsg": "post only would take"}]}])
    ex = OkxExchange("k", "s", "p", http=http)
    with pytest.raises(Rejected):
        ex.place(OrderReq("c1", "BTCUSDT", "BUY", "LONG", "LIMIT", 0.01, price=70000.0, post_only=True))
    assert http.sent[1][3]["ordType"] == "post_only"


# ---------------------------------------------------------------- WEEX (поддельный клиент)
class FakeWeex:
    def __init__(self):
        self.resp = {}
        self.hist = []

    def place_market(self, *a, **k):
        return self.resp.get("market", {})

    def open_orders(self, symbol):
        return []

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        return self.hist

    def order_info(self, oid):
        return {}

    def user_trades(self, symbol, oid):
        return [{"commission": "0.03"}]


def test_weex_empty_reply_is_unknown_and_history_lookup():
    from services.sigexec.exchange.weex import WeexExchange
    c = FakeWeex()
    ex = WeexExchange(c)
    with pytest.raises(Unknown):
        ex.place(OrderReq("b7xqe1", "BTCUSDT", "BUY", "LONG", "MARKET", 0.01))     # {} — исход неизвестен
    c.hist = [{"clientOrderId": "b7xqe1", "status": "FILLED", "executedQty": "0.01", "avgPrice": "70010", "orderId": 5, "symbol": "BTCUSDT"}]
    info = ex.order("BTCUSDT", "b7xqe1", "MARKET", placed_at=1.8e9)
    assert info.status == "FILLED" and info.avg == pytest.approx(70010) and info.fee == pytest.approx(0.03)
    c.hist = [{"clientOrderId": f"x{i}", "status": "FILLED", "executedQty": "0"} for i in range(100)]
    with pytest.raises(Incomplete):                                                 # 100 строк до 1 с — поиск неполный
        ex.order("BTCUSDT", "b7xqe9", "MARKET", placed_at=1.8e9)


# ---------------------------------------------------------------- бумажный запуск
class FakeFeed:
    def __init__(self, arrays):
        self.t, self._a = arrays[0], arrays

    def update(self, now=None):
        return 0

    def fresh(self, now=None):
        return True

    def arrays(self):
        return self._a


def test_runner_paper_tick(tmp_path):
    from services.sigexec.exchange.paper import PaperExchange
    from services.sigexec.run import Runner
    t, o, h, l, c = synth()
    px = float(c[-1])
    ex = PaperExchange("BTCUSDT", venue="okx", state_file=tmp_path / "paper.json",
                       getter=lambda url: {"data": [{"bidPx": str(px - 0.1), "askPx": str(px)}]})
    cfg = {"exchange": {"name": "okx", "paper": True}, "feed": {"symbol": "BTCUSDT"}, "executor": {"enabled": True, "base_usd": 500.0, "max_signal_age_s": 10 ** 10}}
    r = Runner(cfg, tmp_path, exchange=ex, feed=FakeFeed((t, o, h, l, c)), notify=lambda s: None)
    out = r.tick(now=float(t[-1]) + 5)
    assert out["fresh"] is True
    r.ex.save()
    assert (tmp_path / "paper.json").exists()


# ---------------------------------------------------------------- прогон истории (только где есть данные)
FROZEN = Path(os.environ.get("SIGEXEC_FROZEN", Path(__file__).resolve().parents[3] / "backtests" / "frozen"))


@pytest.mark.skipif(not (FROZEN / "BTCUSDT_1m_2y.csv").exists(), reason="нет frozen-минуток на этой машине")
def test_replay_half_year_matches_engine(tmp_path):
    import pandas as pd

    from services.btc_signals import engine as en
    from services.sigexec.replay import replay
    d = pd.read_csv(FROZEN / "BTCUSDT_1m_2y.csv", usecols=["ts", "open", "high", "low", "close"])
    d = d.iloc[: len(d) // 60 * 60 - 120]
    t, o, h, l, c = lines.hours_from_minutes(d["ts"].to_numpy() // 1000, d["open"], d["high"], d["low"], d["close"])
    R = replay(t, o, h, l, c, int(t[-1]) - 180 * 86400, tmp_path / "rp")
    tr = {(x["slot"], x["entry_t"]): x for x in R["trades"]}
    pairs = [((("432" if e["tag"] == en.TAG432 else "system"), e["pos"]["entry_t"]), e["res"] * 10) for e in R["engine"]]
    assert pairs and all(k in tr for k, _ in pairs)
    diff = [tr[k]["pnl_usd"] - v for k, v in pairs]
    assert max(abs(x) for x in diff) < 2.0                  # издержки исполнителя и движка различаются на центы
