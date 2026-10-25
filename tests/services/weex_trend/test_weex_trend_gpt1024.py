"""Аудит GPT 481385e (24.10), E3: неизвестный ответ на заявку тренда ({} / None) не равен отказу — намерение и эпизод
остаются; неполный поиск по истории (WEEX игнорирует page, полные 100 строк) не доказывает, что заявка не дошла."""
import json
from datetime import datetime, timezone

import pytest

from services.weex_trend import engine as te


class Px:
    def __init__(self, mid=2500.0):
        self.mid = mid

    def __call__(self):
        return round(self.mid - 0.01, 2), round(self.mid + 0.01, 2)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class LostReply(te.DryTrendExchange):
    """Рыночный вход принят, но ответ потерян ({} или None); история — как у WEEX: page игнорируется."""
    reply = {}
    foreign = 0

    def place_market(self, symbol, side, position_side, qty, cid, reduce_only=False):
        r = super().place_market(symbol, side, position_side, qty, cid, reduce_only)
        return self.reply if not reduce_only else r

    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        if self.foreign:                                       # окно забито чужими ордерами, своего на «странице» нет
            return [{"orderId": f"x{i}", "clientOrderId": f"other{i}", "status": "FILLED"} for i in range(limit)]
        return super().order_history(symbol, limit, page, start_ms, end_ms)


def setup(tmp_path, reply, foreign=0):
    clock = {"t": 1_800_000_000.0}
    px = Px()
    ex = LostReply(px, now_fn=lambda: clock["t"])
    ex.reply, ex.foreign = reply, foreign
    conf = {**te.DEFAULT, "enabled": True, "dry_run": True, "poll_sec": 0, "risk_usd": 33.0, "max_notional_usd": 1500.0}
    sig = tmp_path / "sig.json"
    sig.write_text(json.dumps({"ETHUSDT": {"side": "SHORT", "entry_px": px.mid, "stop": 2600.0,
                                           "entry_ts": iso(clock["t"]), "exh_sent": False}}))

    def make():
        return te.Trend(ex, conf, state_path=tmp_path / "st.json", journal_path=tmp_path / "j.jsonl", signals_path=sig,
                        now_fn=lambda: clock["t"])
    return clock, ex, make


@pytest.mark.parametrize("reply", [{}, None])
def test_unknown_entry_reply_keeps_pending_and_episode(tmp_path, reply):
    clock, ex, make = setup(tmp_path, reply)
    clock["t"] += 60
    make().tick()
    st = json.loads((tmp_path / "st.json").read_text())
    assert st.get("pending") and st["pending"]["kind"] == "entry"        # исход неизвестен — намерение живо
    assert st.get("episode") and st["episode"]["status"] == "opening"


def test_explicit_reject_clears_pending_once(tmp_path):
    clock, ex, make = setup(tmp_path, {"success": False, "errorCode": "SYNTHETIC"})
    clock["t"] += 60
    make().tick()
    st = json.loads((tmp_path / "st.json").read_text())
    assert not st.get("pending") and not st.get("episode")


def test_incomplete_history_does_not_prove_absence(tmp_path):
    clock, ex, make = setup(tmp_path, {}, foreign=1)
    clock["t"] += 60
    make().tick()                                               # вход ушёл, ответ потерян
    ex.orders.clear()                                          # в открытых нет; в истории — только 100 чужих строк
    clock["t"] += te.PENDING_TTL + 60
    make().tick()
    st = json.loads((tmp_path / "st.json").read_text())
    assert st.get("pending"), "полный ответ истории (100 строк) — поиск неполный, намерение снимать нельзя"
    assert st.get("episode")
