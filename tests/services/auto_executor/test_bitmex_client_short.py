"""Order-body correctness for SHORT methods (mock _request — no live calls)."""
from __future__ import annotations

from services.auto_executor.bitmex_client import BitMEXClient


def _client(captured):
    c = BitMEXClient(api_key="k", api_secret="s")

    def fake_request(verb, path, params=None, body=None, signed=True):
        captured.append({"verb": verb, "path": path, "body": body})
        return {"orderID": "fake", "ordStatus": "New"}

    c._request = fake_request  # type: ignore
    return c


def test_place_limit_sell_body():
    cap = []
    _client(cap).place_limit_sell("XBTUSDT", 100, 74000.0, cl_ord_id="x")
    b = cap[0]["body"]
    assert b["side"] == "Sell"
    assert b["ordType"] == "Limit"
    assert b["execInst"] == "ParticipateDoNotInitiate"  # post-only maker
    assert b["orderQty"] == 100 and b["price"] == 74000.0
    assert b["clOrdID"] == "x"


def test_place_limit_sell_not_post_only():
    cap = []
    _client(cap).place_limit_sell("XBTUSDT", 100, 74000.0, post_only=False)
    assert "execInst" not in cap[0]["body"]


def test_place_market_exit_short_body():
    cap = []
    _client(cap).place_market_exit_short("XBTUSDT", 100, cl_ord_id="y")
    b = cap[0]["body"]
    assert b["side"] == "Buy"          # buy-to-close a short
    assert b["ordType"] == "Market"
    assert b["execInst"] == "Close"    # position-aware flatten
    assert b["clOrdID"] == "y"


def test_long_methods_unchanged():
    cap = []
    c = _client(cap)
    c.place_limit_buy("XBTUSDT", 100, 74000.0)
    c.place_market_exit_long("XBTUSDT", 100)
    assert cap[0]["body"]["side"] == "Buy"
    assert cap[1]["body"]["side"] == "Sell"
    assert cap[1]["body"]["execInst"] == "Close"
